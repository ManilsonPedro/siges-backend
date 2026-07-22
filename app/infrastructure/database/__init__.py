from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.config import settings
from app.infrastructure.database.models import (  # noqa: F401
    Base,
    UserModel,
    FornecedorModel,
    ConceptoModel,
    FundoModel,
    FundoCarregamentoModel,
    MovimentoFinanceiroModel,
    MovimentoHistoricoModel,
    AuditLogModel,
    CompanySettingsModel,
    SavedFilterModel,
    PeriodoFechadoModel,
    MovimentoPagamentoModel,
    OrcamentoModel,
    MovimentoComentarioModel,
    MovimentoAnexoModel,
    PasswordResetModel,
)


_is_sqlite = settings.database.url.startswith("sqlite")

_engine_kwargs: dict = dict(echo=settings.database.echo)
if _is_sqlite:
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update(
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        pool_pre_ping=settings.database.pool_pre_ping,
        poolclass=NullPool if settings.environment == "test" else None,
    )

engine = create_async_engine(settings.database.url, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    """Dependency para obter sessão de BD"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Inicializa a base de dados"""
    from app.infrastructure.database.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Fecha a conexão com a base de dados"""
    await engine.dispose()
