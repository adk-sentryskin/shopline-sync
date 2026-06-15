import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(settings.DB_DSN, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Ensure the shopline_sync schema and ORM tables exist.

    The authoritative DDL lives in migrations/001_create_shopline_sync.sql
    (it also creates the IVFFlat index and chekout_chatbot grants that
    SQLAlchemy's create_all cannot). This is a dev-convenience fallback so the
    service can boot against a fresh local DB. Strictly additive — it never
    drops or alters existing objects.
    """
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS shopline_sync"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    logger.info("shopline_sync schema and tables ensured")
