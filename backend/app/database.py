import asyncio
import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.base import Base
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Run Alembic migrations. Uses create_all only when TESTING=true."""
    if os.environ.get("TESTING", "").lower() in ("true", "1", "yes"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return

    from alembic import command
    from alembic.config import Config as AlembicConfig

    alembic_cfg = AlembicConfig(str(settings.alembic_ini_path))
    alembic_cfg.set_main_option("script_location", str(settings.migrations_dir))
    alembic_cfg.set_main_option("prepend_sys_path", str(settings.backend_dir))

    def run_upgrade():
        command.upgrade(alembic_cfg, "head")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, run_upgrade)
