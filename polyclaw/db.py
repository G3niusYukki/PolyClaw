from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from polyclaw.config import settings


class Base(DeclarativeBase):
    pass


def _build_engine(url: str):
    if url.startswith('postgresql'):
        return create_engine(url, future=True, pool_size=5, max_overflow=10)
    return create_engine(url, future=True)


engine = _build_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
