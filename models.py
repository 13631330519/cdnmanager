import json
import os
import socket
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

from common import (
    DATA_DIR,
    DATABASE_FILE,
    USER_FILE,
    DOMAIN_FILE,
    CREDENTIALS_FILE,
    URL_FILE,
    VALID_PROVIDERS,
    DNS_PROVIDERS,
    REFRESH_STATUS_REFRESHING,
)

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


def _ensure_column(conn, table, column, coltype):
    columns = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
    if column not in columns:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {coltype}')


def migrate_schema(conn):
    _ensure_column(conn, 'domains', 'cpcode', 'TEXT')
    _ensure_column(conn, 'domains', 'projects', 'TEXT')
    _ensure_column(conn, 'domains', 'environments', 'TEXT')
    _ensure_column(conn, 'provider_credentials', 'extra_key', 'TEXT')
    _ensure_column(conn, 'provider_credentials', 'extra_secret', 'TEXT')
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS storage_credentials (
            provider TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            access_key TEXT NOT NULL,
            secret_key TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT,
            PRIMARY KEY (provider, id)
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS storage_targets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            provider TEXT NOT NULL,
            credential_id TEXT NOT NULL,
            target_config TEXT,
            cdn_domain TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS upload_jobs (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            storage_target_id TEXT NOT NULL,
            remote_prefix TEXT,
            status TEXT NOT NULL,
            total_files INTEGER DEFAULT 0,
            total_bytes INTEGER DEFAULT 0,
            done_files INTEGER DEFAULT 0,
            done_bytes INTEGER DEFAULT 0,
            failed_files INTEGER DEFAULT 0,
            refresh_after INTEGER DEFAULT 0,
            created_at TEXT,
            finished_at TEXT
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS upload_files (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            size INTEGER NOT NULL,
            mime TEXT,
            status TEXT NOT NULL,
            bytes_uploaded INTEGER DEFAULT 0,
            storage_key TEXT,
            upload_id TEXT,
            etag TEXT,
            error TEXT,
            retry_count INTEGER DEFAULT 0,
            started_at TEXT,
            finished_at TEXT
        )
        '''
    )
    _ensure_column(conn, 'storage_targets', 'allow_user_delete', 'INTEGER DEFAULT 0')
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS upload_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT NOT NULL,
            part_number INTEGER NOT NULL,
            size INTEGER NOT NULL,
            etag TEXT,
            status TEXT NOT NULL,
            UNIQUE(file_id, part_number)
        )
        '''
    )


def ensure_database():
    os.makedirs(DATA_DIR, exist_ok=True)
    initialize_database()
    if not load_users():
        migrate_json_data()
    if not load_users():
        create_default_users()


def initialize_database():
    def work(conn):
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS provider_credentials (
                provider TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                access_key TEXT NOT NULL,
                secret_key TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (provider, id)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS domains (
                domain TEXT PRIMARY KEY,
                domain_name TEXT NOT NULL,
                provider TEXT NOT NULL,
                credential_id TEXT NOT NULL,
                allowed_users TEXT,
                added_by TEXT,
                added_at TEXT,
                refresh_status TEXT,
                last_refreshed_at TEXT,
                task_id TEXT,
                refresh_task_status TEXT,
                refresh_task_detail TEXT
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                provider TEXT NOT NULL,
                credential_id TEXT NOT NULL,
                submitted_at TEXT,
                completed_at TEXT,
                task_id TEXT,
                refresh_status TEXT,
                refresh_task_detail TEXT
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS system_locks (
                lock_name TEXT PRIMARY KEY,
                holder_id TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS dns_credentials (
                provider TEXT NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                access_key TEXT NOT NULL,
                secret_key TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (provider, id)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS root_domains (
                domain TEXT PRIMARY KEY,
                domain_name TEXT NOT NULL,
                dns_provider TEXT NOT NULL,
                dns_credential_id TEXT NOT NULL,
                added_by TEXT,
                added_at TEXT,
                updated_at TEXT
            )
            '''
        )
        migrate_schema(conn)

    run_write(work)


def migrate_json_data():
    if os.path.exists(USER_FILE):
        with open(USER_FILE, 'r', encoding='utf-8') as f:
            users = json.load(f)
        for user in users:
            upsert_user(user)

    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
            credentials = json.load(f)
        for provider, items in credentials.items():
            if not isinstance(items, list):
                continue
            for item in items:
                upsert_credential(provider, item)

    if os.path.exists(DOMAIN_FILE):
        with open(DOMAIN_FILE, 'r', encoding='utf-8') as f:
            domains = json.load(f)
        for domain in domains:
            upsert_domain(domain)

    if os.path.exists(URL_FILE):
        with open(URL_FILE, 'r', encoding='utf-8') as f:
            urls = json.load(f)
        for url in urls:
            insert_url(url)


def create_default_users():
    now = datetime.now().isoformat()
    default_users = [
        {
            'username': 'admin',
            'password': generate_password_hash('admin123'),
            'role': 'admin',
            'created_at': now,
            'updated_at': None,
        },
        {
            'username': 'user1',
            'password': generate_password_hash('user123'),
            'role': 'user',
            'created_at': now,
            'updated_at': None,
        },
    ]
    for user in default_users:
        upsert_user(user)


def load_users():
    return query_all('SELECT username, password, role, created_at, updated_at FROM users ORDER BY username')


def get_user(username):
    return query_one(
        'SELECT username, password, role, created_at, updated_at FROM users WHERE username = ?',
        (username,),
    )


def load_credentials():
    rows = query_all(
        '''
        SELECT provider, id, name, access_key, secret_key, extra_key, extra_secret, created_at, updated_at
        FROM provider_credentials ORDER BY provider, id
        '''
    )
    data = {provider: [] for provider in VALID_PROVIDERS}
    for row in rows:
        data.setdefault(row['provider'], []).append(row)
    return data


def load_domains():
    return query_all(
        '''
        SELECT domain, domain_name, provider, credential_id, cpcode, projects, environments,
               allowed_users, added_by, added_at, refresh_status, last_refreshed_at, task_id,
               refresh_task_status, refresh_task_detail
        FROM domains ORDER BY domain
        '''
    )


def load_urls():
    urls = query_all(
        '''
        SELECT id, url, provider, credential_id, submitted_at, completed_at, task_id, refresh_status, refresh_task_detail
        FROM urls ORDER BY id
        '''
    )
    #只保留近200-300条记录，防止数据库过大
    if len(urls) >= 300:
        id = urls[100]['id']
        urls = urls[100:]
        def work(conn):
            conn.execute('DELETE FROM urls WHERE id <?', (id,))
        run_write(work)

    return urls

def load_refreshing_domains():
    return query_all(
        '''
        SELECT domain, domain_name, provider, credential_id, cpcode, projects, environments,
               allowed_users, added_by, added_at, refresh_status, last_refreshed_at, task_id,
               refresh_task_status, refresh_task_detail
        FROM domains
        WHERE refresh_status = ? AND task_id IS NOT NULL
        ''',
        (REFRESH_STATUS_REFRESHING,),
    )


def load_refreshing_urls():
    return query_all(
        '''
        SELECT id, url, provider, credential_id, submitted_at, completed_at, task_id, refresh_status, refresh_task_detail
        FROM urls
        WHERE refresh_status = ? AND task_id IS NOT NULL
        ''',
        (REFRESH_STATUS_REFRESHING,),
    )


def try_acquire_polling_lease():
    holder = _holder_id()
    now_iso = datetime.now().isoformat()
    expires_iso = (datetime.now() + timedelta(seconds=POLLING_LEASE_SECONDS)).isoformat()

    def work(conn):
        row = conn.execute(
            'SELECT holder_id, expires_at FROM system_locks WHERE lock_name = ?',
            (POLLING_LOCK_NAME,),
        ).fetchone()
        if row and row['expires_at'] > now_iso and row['holder_id'] != holder:
            return False
        conn.execute(
            '''
            INSERT INTO system_locks (lock_name, holder_id, acquired_at, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(lock_name) DO UPDATE SET
                holder_id = excluded.holder_id,
                acquired_at = excluded.acquired_at,
                expires_at = excluded.expires_at
            ''',
            (POLLING_LOCK_NAME, holder, now_iso, expires_iso),
        )
        return True

    return run_write(work)


def remove_user_from_domains(username):
    def work(conn):
        rows = conn.execute('SELECT domain, allowed_users FROM domains').fetchall()
        for row in rows:
            allowed_users = row.get('allowed_users') or '[]'
            try:
                allowed_users_list = json.loads(allowed_users)
            except Exception:
                allowed_users_list = []
            if username in allowed_users_list:
                updated_users = [u for u in allowed_users_list if u != username]
                conn.execute(
                    'UPDATE domains SET allowed_users = ? WHERE domain = ?',
                    (json.dumps(updated_users, ensure_ascii=False), row['domain']),
                )

    run_write(work)

def upsert_user(user):
    def work(conn):
        conn.execute(
            '''
            INSERT OR REPLACE INTO users (username, password, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (
                user.get('username'),
                user.get('password'),
                user.get('role', 'user'),
                user.get('created_at'),
                user.get('updated_at'),
            ),
        )

    run_write(work)


def delete_user(username):
    def work(conn):
        conn.execute('DELETE FROM users WHERE username = ?', (username,))

    run_write(work)


def upsert_credential(provider, item):
    def work(conn):
        conn.execute(
            '''
            INSERT OR REPLACE INTO provider_credentials
            (provider, id, name, access_key, secret_key, extra_key, extra_secret, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                provider,
                item.get('id'),
                item.get('name'),
                item.get('access_key'),
                item.get('secret_key'),
                item.get('extra_key'),
                item.get('extra_secret'),
                item.get('created_at'),
                item.get('updated_at'),
            ),
        )

    run_write(work)


def delete_credential(provider, credential_id):
    def work(conn):
        conn.execute(
            'DELETE FROM provider_credentials WHERE provider = ? AND id = ?',
            (provider, credential_id),
        )

    run_write(work)


def get_domain(domain):
    return query_one(
        '''
        SELECT domain, domain_name, provider, credential_id, cpcode, projects, environments,
               allowed_users, added_by, added_at, refresh_status, last_refreshed_at, task_id,
               refresh_task_status, refresh_task_detail
        FROM domains WHERE domain = ?
        ''',
        (domain,),
    )


def upsert_domain(domain):
    def work(conn):
        conn.execute(
            '''
            INSERT OR REPLACE INTO domains
            (domain, domain_name, provider, credential_id, cpcode, projects, environments, allowed_users,
             added_by, added_at, refresh_status, last_refreshed_at, task_id, refresh_task_status,
             refresh_task_detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                domain.get('domain'),
                domain.get('domain_name'),
                domain.get('provider'),
                domain.get('credential_id'),
                domain.get('cpcode'),
                json.dumps(domain.get('projects', []), ensure_ascii=False),
                json.dumps(domain.get('environments', []), ensure_ascii=False),
                json.dumps(domain.get('allowed_users', []), ensure_ascii=False),
                domain.get('added_by'),
                domain.get('added_at'),
                domain.get('refresh_status'),
                domain.get('last_refreshed_at'),
                domain.get('task_id'),
                domain.get('refresh_task_status'),
                json.dumps(domain.get('refresh_task_detail'), ensure_ascii=False)
                if domain.get('refresh_task_detail') is not None
                else None,
            ),
        )

    run_write(work)


def delete_domain_record(domain_name):
    def work(conn):
        conn.execute('DELETE FROM domains WHERE domain = ?', (domain_name,))

    run_write(work)


def update_domain_fields(domain_name, updates):
    if not updates:
        return False

    set_clauses = []
    params = []
    for key, value in updates.items():
        if key in {'allowed_users', 'projects', 'environments'}:
            set_clauses.append(f'{key} = ?')
            params.append(json.dumps(value, ensure_ascii=False))
        elif key == 'refresh_task_detail':
            set_clauses.append('refresh_task_detail = ?')
            params.append(json.dumps(value, ensure_ascii=False) if value is not None else None)
        else:
            set_clauses.append(f'{key} = ?')
            params.append(value)
    params.append(domain_name)
    sql = f"UPDATE domains SET {', '.join(set_clauses)} WHERE domain = ?"

    def work(conn):
        conn.execute(sql, params)

    run_write(work)
    return True


def acquire_domain_refresh(domain_name):
    def work(conn):
        row = conn.execute(
            'SELECT refresh_status FROM domains WHERE domain = ?',
            (domain_name,),
        ).fetchone()
        if not row:
            return False
        if row.get('refresh_status') == REFRESH_STATUS_REFRESHING:
            return False
        conn.execute(
            'UPDATE domains SET refresh_status = ? WHERE domain = ?',
            (REFRESH_STATUS_REFRESHING, domain_name),
        )
        return True

    return run_write(work)


def insert_url(url):
    def work(conn):
        cursor = conn.execute(
            '''
            INSERT INTO urls
            (url, provider, credential_id, submitted_at, completed_at, task_id, refresh_status, refresh_task_detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                url.get('url'),
                url.get('provider'),
                url.get('credential_id'),
                url.get('submitted_at'),
                url.get('completed_at'),
                url.get('task_id'),
                url.get('refresh_status'),
                json.dumps(url.get('refresh_task_detail'), ensure_ascii=False)
                if url.get('refresh_task_detail') is not None
                else None,
            ),
        )
        return cursor.lastrowid

    return run_write(work)


def update_url_by_id(url_id, updates):
    if not updates:
        return False

    set_clauses = []
    params = []
    for key, value in updates.items():
        if key == 'refresh_task_detail':
            set_clauses.append('refresh_task_detail = ?')
            params.append(json.dumps(value, ensure_ascii=False) if value is not None else None)
        else:
            set_clauses.append(f'{key} = ?')
            params.append(value)
    params.append(url_id)
    sql = f"UPDATE urls SET {', '.join(set_clauses)} WHERE id = ?"

    def work(conn):
        conn.execute(sql, params)

    run_write(work)
    return True


def get_url_by_id(url_id):
    return query_one(
        '''
        SELECT id, url, provider, credential_id, submitted_at, completed_at, task_id, refresh_status, refresh_task_detail
        FROM urls WHERE id = ?
        ''',
        (url_id,),
    )


def load_dns_credentials():
    rows = query_all(
        '''
        SELECT provider, id, name, access_key, secret_key, created_at, updated_at
        FROM dns_credentials ORDER BY provider, id
        '''
    )
    data = {provider: [] for provider in DNS_PROVIDERS}
    for row in rows:
        data.setdefault(row['provider'], []).append(row)
    return data


def get_dns_credential(provider, credential_id):
    return query_one(
        '''
        SELECT provider, id, name, access_key, secret_key, created_at, updated_at
        FROM dns_credentials WHERE provider = ? AND id = ?
        ''',
        (provider, credential_id),
    )


def upsert_dns_credential(provider, item):
    def work(conn):
        conn.execute(
            '''
            INSERT OR REPLACE INTO dns_credentials
            (provider, id, name, access_key, secret_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                provider,
                item.get('id'),
                item.get('name'),
                item.get('access_key'),
                item.get('secret_key'),
                item.get('created_at'),
                item.get('updated_at'),
            ),
        )

    run_write(work)


def delete_dns_credential(provider, credential_id):
    def work(conn):
        conn.execute(
            'DELETE FROM dns_credentials WHERE provider = ? AND id = ?',
            (provider, credential_id),
        )

    run_write(work)


def load_root_domains():
    return query_all(
        '''
        SELECT domain, domain_name, dns_provider, dns_credential_id, added_by, added_at, updated_at
        FROM root_domains ORDER BY domain
        '''
    )


def get_root_domain(domain):
    return query_one(
        '''
        SELECT domain, domain_name, dns_provider, dns_credential_id, added_by, added_at, updated_at
        FROM root_domains WHERE domain = ?
        ''',
        (domain,),
    )


def upsert_root_domain(item):
    def work(conn):
        conn.execute(
            '''
            INSERT OR REPLACE INTO root_domains
            (domain, domain_name, dns_provider, dns_credential_id, added_by, added_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                item.get('domain'),
                item.get('domain_name'),
                item.get('dns_provider'),
                item.get('dns_credential_id'),
                item.get('added_by'),
                item.get('added_at'),
                item.get('updated_at'),
            ),
        )

    run_write(work)


def delete_root_domain(domain):
    def work(conn):
        conn.execute('DELETE FROM root_domains WHERE domain = ?', (domain,))

    run_write(work)


def load_storage_credentials():
    rows = query_all(
        '''
        SELECT provider, id, name, access_key, secret_key, created_at, updated_at
        FROM storage_credentials ORDER BY provider, id
        '''
    )
    from common import STORAGE_PROVIDERS
    data = {provider: [] for provider in STORAGE_PROVIDERS}
    for row in rows:
        data.setdefault(row['provider'], []).append(row)
    return data


def get_storage_credential(provider, credential_id):
    return query_one(
        '''
        SELECT provider, id, name, access_key, secret_key, created_at, updated_at
        FROM storage_credentials WHERE provider = ? AND id = ?
        ''',
        (provider, credential_id),
    )


def upsert_storage_credential(provider, item):
    def work(conn):
        conn.execute(
            '''
            INSERT OR REPLACE INTO storage_credentials
            (provider, id, name, access_key, secret_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                provider,
                item.get('id'),
                item.get('name'),
                item.get('access_key'),
                item.get('secret_key'),
                item.get('created_at'),
                item.get('updated_at'),
            ),
        )

    run_write(work)


def delete_storage_credential(provider, credential_id):
    def work(conn):
        conn.execute(
            'DELETE FROM storage_credentials WHERE provider = ? AND id = ?',
            (provider, credential_id),
        )

    run_write(work)


def load_storage_targets():
    return query_all(
        '''
        SELECT id, name, provider, credential_id, target_config, cdn_domain,
               allow_user_delete, created_at, updated_at
        FROM storage_targets ORDER BY name
        '''
    )


def get_storage_target(target_id):
    return query_one(
        '''
        SELECT id, name, provider, credential_id, target_config, cdn_domain,
               allow_user_delete, created_at, updated_at
        FROM storage_targets WHERE id = ?
        ''',
        (target_id,),
    )


def upsert_storage_target(item):
    def work(conn):
        conn.execute(
            '''
            INSERT OR REPLACE INTO storage_targets
            (id, name, provider, credential_id, target_config, cdn_domain,
             allow_user_delete, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                item.get('id'),
                item.get('name'),
                item.get('provider'),
                item.get('credential_id'),
                json.dumps(item.get('target_config') or {}, ensure_ascii=False),
                item.get('cdn_domain'),
                1 if item.get('allow_user_delete') else 0,
                item.get('created_at'),
                item.get('updated_at'),
            ),
        )

    run_write(work)


def delete_storage_target(target_id):
    def work(conn):
        conn.execute('DELETE FROM storage_targets WHERE id = ?', (target_id,))

    run_write(work)


def insert_upload_job(job):
    def work(conn):
        conn.execute(
            '''
            INSERT INTO upload_jobs
            (id, username, storage_target_id, remote_prefix, status, total_files, total_bytes,
             done_files, done_bytes, failed_files, refresh_after, created_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                job.get('id'),
                job.get('username'),
                job.get('storage_target_id'),
                job.get('remote_prefix'),
                job.get('status'),
                job.get('total_files', 0),
                job.get('total_bytes', 0),
                job.get('done_files', 0),
                job.get('done_bytes', 0),
                job.get('failed_files', 0),
                job.get('refresh_after', 0),
                job.get('created_at'),
                job.get('finished_at'),
            ),
        )

    run_write(work)


def get_upload_job(job_id):
    return query_one(
        '''
        SELECT id, username, storage_target_id, remote_prefix, status, total_files, total_bytes,
               done_files, done_bytes, failed_files, refresh_after, created_at, finished_at
        FROM upload_jobs WHERE id = ?
        ''',
        (job_id,),
    )


def update_upload_job(job_id, updates):
    if not updates:
        return False
    set_clauses = []
    params = []
    for key, value in updates.items():
        set_clauses.append(f'{key} = ?')
        params.append(value)
    params.append(job_id)
    sql = f"UPDATE upload_jobs SET {', '.join(set_clauses)} WHERE id = ?"

    def work(conn):
        conn.execute(sql, params)

    run_write(work)
    return True


def insert_upload_files(files):
    def work(conn):
        for item in files:
            conn.execute(
                '''
                INSERT INTO upload_files
                (id, job_id, relative_path, size, mime, status, bytes_uploaded, storage_key,
                 upload_id, etag, error, retry_count, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    item.get('id'),
                    item.get('job_id'),
                    item.get('relative_path'),
                    item.get('size'),
                    item.get('mime'),
                    item.get('status'),
                    item.get('bytes_uploaded', 0),
                    item.get('storage_key'),
                    item.get('upload_id'),
                    item.get('etag'),
                    item.get('error'),
                    item.get('retry_count', 0),
                    item.get('started_at'),
                    item.get('finished_at'),
                ),
            )

    run_write(work)


def get_upload_file(file_id):
    return query_one(
        '''
        SELECT id, job_id, relative_path, size, mime, status, bytes_uploaded, storage_key,
               upload_id, etag, error, retry_count, started_at, finished_at
        FROM upload_files WHERE id = ?
        ''',
        (file_id,),
    )


def update_upload_file(file_id, updates):
    if not updates:
        return False
    set_clauses = []
    params = []
    for key, value in updates.items():
        set_clauses.append(f'{key} = ?')
        params.append(value)
    params.append(file_id)
    sql = f"UPDATE upload_files SET {', '.join(set_clauses)} WHERE id = ?"

    def work(conn):
        conn.execute(sql, params)

    run_write(work)
    return True


def list_upload_files(job_id, status=None, limit=500, offset=0):
    if status:
        return query_all(
            '''
            SELECT id, job_id, relative_path, size, mime, status, bytes_uploaded, storage_key,
                   upload_id, etag, error, retry_count, started_at, finished_at
            FROM upload_files WHERE job_id = ? AND status = ?
            ORDER BY relative_path LIMIT ? OFFSET ?
            ''',
            (job_id, status, limit, offset),
        )
    return query_all(
        '''
        SELECT id, job_id, relative_path, size, mime, status, bytes_uploaded, storage_key,
               upload_id, etag, error, retry_count, started_at, finished_at
        FROM upload_files WHERE job_id = ?
        ORDER BY relative_path LIMIT ? OFFSET ?
        ''',
        (job_id, limit, offset),
    )


def count_upload_files(job_id, status=None):
    if status:
        row = query_one(
            'SELECT COUNT(*) AS cnt FROM upload_files WHERE job_id = ? AND status = ?',
            (job_id, status),
        )
    else:
        row = query_one('SELECT COUNT(*) AS cnt FROM upload_files WHERE job_id = ?', (job_id,))
    return row['cnt'] if row else 0


def insert_upload_parts(parts):
    def work(conn):
        for item in parts:
            conn.execute(
                '''
                INSERT OR REPLACE INTO upload_parts
                (file_id, part_number, size, etag, status)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (
                    item.get('file_id'),
                    item.get('part_number'),
                    item.get('size'),
                    item.get('etag'),
                    item.get('status'),
                ),
            )

    run_write(work)


def list_upload_parts(file_id):
    return query_all(
        '''
        SELECT id, file_id, part_number, size, etag, status
        FROM upload_parts WHERE file_id = ? ORDER BY part_number
        ''',
        (file_id,),
    )


def update_upload_part(file_id, part_number, updates):
    if not updates:
        return False
    set_clauses = []
    params = []
    for key, value in updates.items():
        set_clauses.append(f'{key} = ?')
        params.append(value)
    params.extend([file_id, part_number])
    sql = f"UPDATE upload_parts SET {', '.join(set_clauses)} WHERE file_id = ? AND part_number = ?"

    def work(conn):
        conn.execute(sql, params)

    run_write(work)
    return True


def recalculate_upload_job_stats(job_id):
    def work(conn):
        rows = conn.execute(
            'SELECT status, size, bytes_uploaded FROM upload_files WHERE job_id = ?',
            (job_id,),
        ).fetchall()
        done_files = failed_files = 0
        done_bytes = 0
        for row in rows:
            status = row['status']
            if status == 'completed':
                done_files += 1
                done_bytes += row['size'] or 0
            elif status == 'failed':
                failed_files += 1
        total = len(rows)
        pending = total - done_files - failed_files
        if pending > 0 and done_files + failed_files > 0:
            job_status = 'running'
        elif done_files == total:
            job_status = 'completed'
        elif failed_files == total:
            job_status = 'failed'
        elif done_files > 0 and failed_files > 0 and pending == 0:
            job_status = 'partial'
        elif done_files == 0 and failed_files == 0:
            job_status = 'pending'
        else:
            job_status = 'running'
        finished_at = datetime.now().isoformat() if pending == 0 and total > 0 else None
        conn.execute(
            '''
            UPDATE upload_jobs
            SET done_files = ?, done_bytes = ?, failed_files = ?, status = ?,
                finished_at = COALESCE(?, finished_at)
            WHERE id = ?
            ''',
            (done_files, done_bytes, failed_files, job_status, finished_at, job_id),
        )

    run_write(work)


def delete_upload_job_cascade(job_id):
    def work(conn):
        file_rows = conn.execute(
            'SELECT id FROM upload_files WHERE job_id = ?',
            (job_id,),
        ).fetchall()
        for row in file_rows:
            conn.execute('DELETE FROM upload_parts WHERE file_id = ?', (row['id'],))
        conn.execute('DELETE FROM upload_files WHERE job_id = ?', (job_id,))
        conn.execute('DELETE FROM upload_jobs WHERE id = ?', (job_id,))

    run_write(work)


def cleanup_finished_upload_job(job_id):
    job = get_upload_job(job_id)
    if not job:
        return False
    if job.get('status') not in {'completed', 'partial', 'failed', 'cancelled'}:
        return False
    active = count_upload_files(job_id, status='uploading')
    active += count_upload_files(job_id, status='verifying')
    active += count_upload_files(job_id, status='pending')
    if active > 0:
        return False
    delete_upload_job_cascade(job_id)
    return True
