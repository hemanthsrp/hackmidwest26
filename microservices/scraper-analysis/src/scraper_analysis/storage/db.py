import psycopg
from pgvector.psycopg import register_vector

from ..config import Settings


def connect(settings: Settings) -> psycopg.Connection:
    conn = psycopg.connect(
        host=settings.akamai_db_host,
        port=settings.akamai_db_port,
        dbname=settings.akamai_db_name,
        user=settings.akamai_db_user,
        password=settings.akamai_db_password,
        autocommit=True,
    )
    register_vector(conn)
    return conn
