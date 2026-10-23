import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from . import instagram
from .config import DEV_SECRET, get_settings
from .db import SessionLocal, engine
from .migrations import upgrade
from .routers import analytics, auth, club_admin, clubs, drops, fan, master, photos, ranking, sponsor
from .seed import seed

logging.basicConfig(level=logging.INFO)


def _sync_instagram() -> None:
    from sqlalchemy import select

    from . import models as m

    with SessionLocal() as db:
        artist = db.scalar(select(m.Artist).where(m.Artist.slug == get_settings().instagram_artist))
        if artist:
            r = instagram.sync(db, artist)
            logging.getLogger("superfas.instagram").info("Instagram: %d posts lidos, %d novos compartilhamentos", r.found, r.verified)


async def _instagram_loop() -> None:
    """Confere a hashtag de tempos em tempos (a API só devolve as últimas 24 horas, então não pode ficar muito espaçado)."""
    while True:
        try:
            await asyncio.to_thread(_sync_instagram)
        except Exception:  # noqa: BLE001
            logging.getLogger("superfas.instagram").exception("Falha na conferência do Instagram")
        await asyncio.sleep(max(5, get_settings().instagram_sync_minutes) * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if not s.database_url.startswith("sqlite") and (s.jwt_secret == DEV_SECRET or len(s.jwt_secret) < 32):
        raise RuntimeError("Defina JWT_SECRET (32+ caracteres) antes de subir com Postgres.")
    # Cria/atualiza as tabelas e converte dados antigos (ver migrations.py).
    upgrade(engine)
    with SessionLocal() as db:
        seed(db)
    task = asyncio.create_task(_instagram_loop()) if instagram.enabled() else None
    yield
    if task:
        task.cancel()


settings = get_settings()
app = FastAPI(
    title="Super Fãs API",
    version="0.1.0",
    description="API dos fã clubes. Faça login em /auth/login e use o token no botão Authorize.",
    root_path=settings.root_path,
    lifespan=lifespan,
)

for r in (auth.router, fan.router, clubs.router, club_admin.router, analytics.router, drops.router, photos.router, ranking.router, master.router, sponsor.router):
    app.include_router(r)

Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)


@app.get("/uploads/{name}", include_in_schema=False)
def uploaded_file(name: str):
    """Entrega as fotos enviadas. É uma rota comum (e não um StaticFiles montado) porque o StaticFiles dá 404
    quando a API roda atrás de um prefixo (ROOT_PATH=/api), que é como ela sobe no servidor."""
    folder = Path(settings.upload_dir).resolve()
    path = (folder / name).resolve()
    if path.parent != folder or name.startswith(".") or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/health", tags=["Sistema"])
def health():
    return {"ok": True}
