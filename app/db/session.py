from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Pool sizing and timeouts: measurements and reasoning are in doc/performance.md.
engine = create_engine(
  settings.database_url,
  pool_size=5,          # connections kept open per app process
  max_overflow=10,      # extra connections under bursts, closed when idle
  pool_timeout=10,      # seconds to wait for a free connection before failing
  pool_pre_ping=True,   # test a connection before use: survives a Postgres restart
  connect_args={
    "connect_timeout": 5,                       # seconds to open a connection
    "options": "-c statement_timeout=10000",    # Postgres cancels any query after 10 s
  },
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def get_db() -> Generator[Session, None, None]:
  db = SessionLocal()
  try:
    yield db
  finally:
    db.close()
