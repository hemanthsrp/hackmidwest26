"""Research-owned persistence. No chat transcripts or raw prompts are stored."""
import os
from functools import lru_cache
from sqlalchemy import create_engine, MetaData, Table, Column, String, JSON, DateTime, delete, select
from datetime import datetime, timezone

metadata = MetaData(schema=None)
records = Table('research_user_records', metadata,
    Column('user_id', String, primary_key=True), Column('kind', String, primary_key=True),
    Column('key', String, primary_key=True), Column('value', JSON, nullable=False),
    Column('updated_at', DateTime(timezone=True), nullable=False))

@lru_cache
def engine():
    url = os.environ.get('RESEARCH_DATABASE_URL', '')
    if not url:
        raise RuntimeError('RESEARCH_DATABASE_URL is required')
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    return create_engine(url, pool_pre_ping=True)

def migrate():
    metadata.create_all(engine())

def read(user_id, kind):
    with engine().connect() as conn:
        return [{'key': r.key, 'value': r.value, 'updated_at': r.updated_at.isoformat()} for r in conn.execute(select(records).where(records.c.user_id == user_id, records.c.kind == kind))]

def write(user_id, kind, key, value):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert = sqlite_insert if engine().dialect.name == 'sqlite' else pg_insert
    row = {'user_id':user_id,'kind':kind,'key':key,'value':value,'updated_at':datetime.now(timezone.utc)}
    with engine().begin() as conn:
        conn.execute(insert(records).values(**row).on_conflict_do_update(index_elements=['user_id','kind','key'],set_={'value':value,'updated_at':row['updated_at']}))

def remove(user_id, kind=None, key=None):
    query = delete(records).where(records.c.user_id == user_id)
    if kind is not None: query = query.where(records.c.kind == kind)
    if key is not None: query = query.where(records.c.key == key)
    with engine().begin() as conn: conn.execute(query)

if __name__ == '__main__':
    migrate()
