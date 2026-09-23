import json
import os
import socket
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from cdnmanager.common import DATA_DIR, DATABASE_FILE

JSON_FIELDS = {'allowed_users', 'projects', 'environments', 'refresh_task_detail', 'log_entry', 'target_config'}
POLLING_LOCK_NAME = 'task_polling'
POLLING_LEASE_SECONDS = 90
DB_RETRY_ATTEMPTS = 5


def dict_factory(cursor, row):
    result = {}
    for idx, col in enumerate(cursor.description):
        key = col[0]
        value = row[idx]
        if key in JSON_FIELDS and value is not None:
            try:
                value = json.loads(value)
            except Exception:
                pass
        result[key] = value
    return result


def get_connection():
    conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False, timeout=30)
    conn.row_factory = dict_factory
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute('PRAGMA synchronous = NORMAL')
    conn.execute('PRAGMA busy_timeout = 5000')
    return conn


def _holder_id():
    return f'{socket.gethostname()}:{os.getpid()}'


def _retry_on_locked(operation):
    last_error = None
    for attempt in range(DB_RETRY_ATTEMPTS):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            last_error = exc
            if 'locked' in str(exc).lower() and attempt < DB_RETRY_ATTEMPTS - 1:
                time.sleep(0.05 * (2 ** attempt))
                continue
            raise
    raise last_error


@contextmanager
def db_connection(*, write=False):
    conn = get_connection()
    try:
        if write:
            conn.execute('BEGIN IMMEDIATE')
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def query_all(query, params=None):
    if params is None:
        params = ()

    def run():
        with db_connection() as conn:
            return conn.execute(query, params).fetchall()

    return _retry_on_locked(run)


def query_one(query, params=None):
    if params is None:
        params = ()

    def run():
        with db_connection() as conn:
            return conn.execute(query, params).fetchone()

    return _retry_on_locked(run)


def run_write(work):
    def run():
        with db_connection(write=True) as conn:
            return work(conn)

    return _retry_on_locked(run)


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
