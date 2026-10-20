import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import DEV_SECRET, get_settings
from .db import Base, SessionLocal, engine
from .routers import auth, club_admin, fan, master, sponsor
from .seed import seed

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if not s.database_url.startswith("sqlite") and (s.jwt_secret == DEV_SECRET or len(s.jwt_secret) < 32):
        raise RuntimeError("Defina JWT_SECRET (32+ caracteres) antes de subir com Postgres.")
    # Cria as tabelas que faltam. Quando o esquema começar a mudar com dados reais, trocar por migrações (Alembic).
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


settings = get_settings()
app = FastAPI(
    title="Super Fãs API",
    version="0.1.0",
    description="API dos fã clubes. Faça login em /auth/login e use o token no botão Authorize.",
    root_path=settings.root_path,
    lifespan=lifespan,
)

for r in (auth.router, fan.router, club_admin.router, master.router, sponsor.router):
    app.include_router(r)

Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.get("/health", tags=["Sistema"])
def health():
    return {"ok": True}
