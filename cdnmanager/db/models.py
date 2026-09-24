from datetime import datetime
from werkzeug.security import generate_password_hash
from cdnmanager.db.users import load_users,upsert_user
from cdnmanager.db.connection import ensure_data_dir,run_write

def ensure_database():
    ensure_data_dir()
    initialize_database()
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

        columns = {row['name'] for row in conn.execute('PRAGMA table_info(domains)').fetchall()}
        if 'cpcode' not in columns:
            conn.execute('ALTER TABLE domains ADD COLUMN cpcode TEXT')
        if 'projects' not in columns:
            conn.execute('ALTER TABLE domains ADD COLUMN projects TEXT')
        if 'environments' not in columns:
            conn.execute('ALTER TABLE domains ADD COLUMN environments TEXT')

        columns = {row['name'] for row in conn.execute('PRAGMA table_info(provider_credentials)').fetchall()}
        if 'extra_key' not in columns:
            conn.execute('ALTER TABLE provider_credentials ADD COLUMN extra_key TEXT')
        if 'extra_secret' not in columns:
            conn.execute('ALTER TABLE provider_credentials ADD COLUMN extra_secret TEXT')

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
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(storage_targets)').fetchall()}
        if 'allow_user_delete' not in columns:
            conn.execute('ALTER TABLE storage_targets ADD COLUMN allow_user_delete INTEGER DEFAULT 0')

        columns = {row['name'] for row in conn.execute('PRAGMA table_info(urls)').fetchall()}
        if 'domain' not in columns:
            conn.execute('ALTER TABLE urls ADD COLUMN domain TEXT')

        columns = {row['name'] for row in conn.execute('PRAGMA table_info(upload_files)').fetchall()}
        if 'last_heartbeat_at' not in columns:
            conn.execute('ALTER TABLE upload_files ADD COLUMN last_heartbeat_at TEXT')

        from cdnmanager.common import infer_domain_from_url
        rows = conn.execute('SELECT id, url, domain FROM urls WHERE domain IS NULL OR domain = ""').fetchall()
        for row in rows:
            domain = infer_domain_from_url(row['url'])
            if domain:
                conn.execute('UPDATE urls SET domain = ? WHERE id = ?', (domain, row['id']))

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
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                api_key_secret TEXT,
                allowed_users TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS project_environments (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                api_key_secret TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(project_id, name),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS project_env_storage_targets (
                environment_id TEXT NOT NULL,
                storage_target_id TEXT NOT NULL,
                PRIMARY KEY (environment_id, storage_target_id),
                FOREIGN KEY (environment_id) REFERENCES project_environments(id) ON DELETE CASCADE
            )
            '''
        )
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(domains)').fetchall()}
        if 'project_id' not in columns:
            conn.execute('ALTER TABLE domains ADD COLUMN project_id TEXT')
        if 'environment_id' not in columns:
            conn.execute('ALTER TABLE domains ADD COLUMN environment_id TEXT')

        columns = {row['name'] for row in conn.execute('PRAGMA table_info(storage_targets)').fetchall()}
        if 'project_id' not in columns:
            conn.execute('ALTER TABLE storage_targets ADD COLUMN project_id TEXT')
        if 'environment_id' not in columns:
            conn.execute('ALTER TABLE storage_targets ADD COLUMN environment_id TEXT')

    run_write(work)


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

