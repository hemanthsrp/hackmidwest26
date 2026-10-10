import psycopg
from pgvector.psycopg import register_vector

from ..config import Settings


def connect(settings: Settings) -> psycopg.Connection:
    # TLS enforcement lives in the URL itself (sslmode=require), validated
    # at config load time -- not a separate connect()-time default that
    # could silently downgrade.
    conn = psycopg.connect(settings.database_url, autocommit=True)
    register_vector(conn)
    return conn
