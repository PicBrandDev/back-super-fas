from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "segredo-de-desenvolvimento-troque-em-producao"


class Settings(BaseSettings):
    """Configuração lida das variáveis de ambiente (ou de um arquivo .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Ex.: postgresql+psycopg://superfas:senha@db:5432/superfas
    database_url: str = "sqlite:///./superfas.db"

    # Segredo dos tokens de login. Precisa ser o MESMO no front (proxy.ts).
    jwt_secret: str = DEV_SECRET
    jwt_days: int = 7

    # Senha das contas de teste criadas na primeira subida. Vazio = gera uma aleatória e mostra no log.
    seed_password: str = ""

    # Prefixo quando a API fica atrás do Caddy em /api (para o /docs funcionar).
    root_path: str = ""

    # E-mail dos convites (dono de fã clube). Sem SMTP_HOST a API não envia e a tela mostra a senha provisória.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # ex.: Super Fãs <nao-responda@seudominio.com>

    # Endereço público do front, usado nos links dos e-mails.
    app_url: str = "http://localhost:3000"

    # Onde ficam as artes enviadas pelos patrocinadores.
    upload_dir: str = "./uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
