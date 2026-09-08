from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from app.config import settings

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine_kwargs = {"echo": False}
if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

if is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if is_sqlite:
            from sqlalchemy import text, inspect
            def _check_and_migrate(sync_conn):
                insp = inspect(sync_conn)
                if insp.has_table("novels"):
                    cols = [c["name"] for c in insp.get_columns("novels")]
                    if "knowledge_base_id" not in cols:
                        sync_conn.execute(text("ALTER TABLE novels ADD COLUMN knowledge_base_id INTEGER"))
                    if "ordinary_knowledge_base_id" not in cols:
                        sync_conn.execute(text("ALTER TABLE novels ADD COLUMN ordinary_knowledge_base_id INTEGER"))
                if insp.has_table("llm_providers"):
                    cols = [c["name"] for c in insp.get_columns("llm_providers")]
                    if "purpose" not in cols:
                        sync_conn.execute(text("ALTER TABLE llm_providers ADD COLUMN purpose VARCHAR(32) NOT NULL DEFAULT 'common'"))
                if insp.has_table("knowledge_bases"):
                    cols = [c["name"] for c in insp.get_columns("knowledge_bases")]
                    if "volumes" not in cols:
                        sync_conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN volumes JSON"))
                    if "volume_relations" not in cols:
                        sync_conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN volume_relations JSON"))
                    if "import_status" not in cols:
                        sync_conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN import_status VARCHAR(20) DEFAULT 'idle'"))
                    if "import_progress" not in cols:
                        sync_conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN import_progress JSON"))
                if insp.has_table("knowledge_entries"):
                    cols = [c["name"] for c in insp.get_columns("knowledge_entries")]
                    if "volume" not in cols:
                        sync_conn.execute(text("ALTER TABLE knowledge_entries ADD COLUMN volume INTEGER"))
                    if "volume_title" not in cols:
                        sync_conn.execute(text("ALTER TABLE knowledge_entries ADD COLUMN volume_title VARCHAR(200)"))
                    if "chapter_number" not in cols:
                        sync_conn.execute(text("ALTER TABLE knowledge_entries ADD COLUMN chapter_number INTEGER"))
                    if "chapter_title" not in cols:
                        sync_conn.execute(text("ALTER TABLE knowledge_entries ADD COLUMN chapter_title VARCHAR(200)"))
            await conn.run_sync(_check_and_migrate)
