"""
PostgreSQL connection layer with sqlite-dialect translation.

The codebase was written against sqlite3. Rather than hand-editing hundreds of
SQL strings (error-prone), this module wraps psycopg2 and translates the few
sqlite-only constructs at execute() time:

  - "?" placeholders            -> "%s"
  - INSERT OR IGNORE            -> INSERT ... ON CONFLICT DO NOTHING
  - datetime('now', '+5 hours') -> to_char(utc now + 5h, sqlite text format)
  - PRAGMA table_info(t)        -> information_schema query (same column order)
  - other PRAGMAs               -> no-op

Usage:  from db_compat import connect_db, DBError
Connections behave like sqlite3.connect(): `with conn:` commits/rolls back,
close() must be called (or the object garbage-collects the socket).
"""
import os
import re
import psycopg2
import psycopg2.extensions
import psycopg2.pool
from dotenv import load_dotenv

load_dotenv()

DBError = psycopg2.Error
IntegrityError = psycopg2.IntegrityError

_DSN = {
    "host": os.getenv("PG_HOST", "localhost"),
    "port": int(os.getenv("PG_PORT", "5432")),
    "dbname": os.getenv("PG_DB", "liars_fortune"),
    "user": os.getenv("PG_USER", "postgres"),
    "password": os.getenv("PG_PASSWORD", ""),
}

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=20, **_DSN)
    return _pool

# sqlite's datetime('now', '+5 hours') returns UTC+5 as 'YYYY-MM-DD HH:MM:SS' text
_DT_NOW_RE = re.compile(r"datetime\(\s*'now'\s*,\s*'\+5 hours'\s*\)", re.IGNORECASE)
_DT_NOW_PG = "to_char((now() at time zone 'utc') + interval '5 hours', 'YYYY-MM-DD HH24:MI:SS')"
_PRAGMA_TABLE_INFO_RE = re.compile(r"PRAGMA\s+table_info\(\s*(\w+)\s*\)\s*;?", re.IGNORECASE)
_INSERT_OR_IGNORE_RE = re.compile(r"INSERT\s+OR\s+IGNORE\s+INTO", re.IGNORECASE)


def translate_sql(sql: str) -> str:
    m = _PRAGMA_TABLE_INFO_RE.search(sql)
    if m:
        # sqlite returns (cid, name, type, notnull, dflt_value, pk); callers use [1]
        return (
            "SELECT ordinal_position - 1, column_name, data_type, 0, NULL::text, 0 "
            "FROM information_schema.columns WHERE table_name = '{}' "
            "ORDER BY ordinal_position".format(m.group(1).lower())
        )
    if sql.lstrip().upper().startswith("PRAGMA"):
        return "SELECT 1 WHERE FALSE"  # journal_mode etc. — meaningless on PG

    sql = sql.replace("?", "%s")
    sql = _DT_NOW_RE.sub(_DT_NOW_PG, sql)

    if _INSERT_OR_IGNORE_RE.search(sql):
        sql = _INSERT_OR_IGNORE_RE.sub("INSERT INTO", sql)
        if "ON CONFLICT" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


class CompatCursor:
    def __init__(self, cursor):
        self._cur = cursor

    def execute(self, sql, params=None):
        self._cur.execute(translate_sql(sql), params)
        return self

    def executemany(self, sql, seq_of_params):
        self._cur.executemany(translate_sql(sql), seq_of_params)
        return self

    def executescript(self, script):
        self._cur.execute(script)  # psycopg2 runs ';'-separated statements fine
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size=None):
        return self._cur.fetchmany(size) if size else self._cur.fetchmany()

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def close(self):
        self._cur.close()


class CompatConnection:
    def __init__(self, conn, pool=None):
        self._conn = conn
        self._pool = pool
        self._returned = False

    def cursor(self):
        return CompatCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        """Return the connection to the pool (putconn rolls back if needed)."""
        if self._returned:
            return
        self._returned = True
        if self._pool is not None:
            try:
                self._pool.putconn(self._conn)
            except Exception:
                try:
                    self._conn.close()
                except Exception:
                    pass
        elif not self._conn.closed:
            self._conn.close()

    # Match sqlite3 semantics: `with conn:` commits on success, rolls back on
    # error, and does NOT close the connection.
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False

    # Safety net: code paths that forget close() (early returns) would
    # otherwise leak pooled connections; GC returns them promptly.
    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def connect_db() -> CompatConnection:
    pool = _get_pool()
    return CompatConnection(pool.getconn(), pool)


def raw_connect():
    """Unwrapped psycopg2 connection (for setup/migration scripts)."""
    return psycopg2.connect(**_DSN)
