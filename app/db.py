from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Banco em outra máquina: cada ida e volta custa tempo, e o pre_ping manda um SELECT 1 extra a cada requisição.
        # Em vez dele, as conexões são renovadas a cada 4 minutos (antes de o banco derrubar as ociosas) e o TCP avisa se cair.
        kwargs.update(
            pool_recycle=240,
            pool_size=10,
            max_overflow=10,
            connect_args={"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3},
        )
    return create_engine(url, **kwargs)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
