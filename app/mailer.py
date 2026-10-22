"""Envio de e-mail por SMTP (convites). Sem SMTP_HOST configurado, não envia: só registra no log."""

import logging
import smtplib
from email.message import EmailMessage

from .config import get_settings

log = logging.getLogger("superfas.mailer")


def send_mail(to: str, subject: str, body: str) -> bool:
    """Devolve True quando o servidor SMTP aceitou a mensagem."""
    s = get_settings()
    if not s.smtp_host:
        log.warning("SMTP não configurado: e-mail para %s não enviado (%s).", to, subject)
        return False
    msg = EmailMessage()
    msg["From"] = s.smtp_from or s.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException):
        log.exception("Falha ao enviar e-mail para %s.", to)
        return False


def send_owner_invite(to: str, name: str, club_name: str, artist_name: str, artist_slug: str, temp_password: str | None) -> bool:
    """Convite para a pessoa se tornar dona de um fã clube do ambiente de um artista."""
    url = f"{get_settings().app_url.rstrip('/')}/{artist_slug}/login"
    lines = [
        f"Olá, {name or to}!",
        "",
        f"Você foi escolhido(a) para ser dono(a) do fã clube “{club_name}”, no ambiente de {artist_name}.",
        "",
        f"Entre em: {url}",
        f"Login: {to}",
    ]
    if temp_password:
        lines += [f"Senha provisória: {temp_password}", "", "No primeiro acesso você escolhe uma senha só sua."]
    else:
        lines += ["", "Use a senha da sua conta atual."]
    return send_mail(to, f"Você é o dono do fã clube {club_name}", "\n".join(lines) + "\n")
