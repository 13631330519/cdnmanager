import json

from cdnmanager.common import DNS_PROVIDERS, STORAGE_PROVIDERS, VALID_PROVIDERS
from cdnmanager.db.connection import query_all, query_one, run_write


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


def upsert_credential(provider, item):
    def work(conn):
        conn.execute(
            '''
            INSERT INTO provider_credentials
            (provider, id, name, access_key, secret_key, extra_key, extra_secret, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, id) DO UPDATE SET
                name = excluded.name,
                access_key = excluded.access_key,
                secret_key = excluded.secret_key,
                extra_key = excluded.extra_key,
                extra_secret = excluded.extra_secret,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
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
            INSERT INTO dns_credentials
            (provider, id, name, access_key, secret_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, id) DO UPDATE SET
                name = excluded.name,
                access_key = excluded.access_key,
                secret_key = excluded.secret_key,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
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
            INSERT INTO root_domains
            (domain, domain_name, dns_provider, dns_credential_id, added_by, added_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                domain_name = excluded.domain_name,
                dns_provider = excluded.dns_provider,
                dns_credential_id = excluded.dns_credential_id,
                added_by = excluded.added_by,
                added_at = excluded.added_at,
                updated_at = excluded.updated_at
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
            INSERT INTO storage_credentials
            (provider, id, name, access_key, secret_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, id) DO UPDATE SET
                name = excluded.name,
                access_key = excluded.access_key,
                secret_key = excluded.secret_key,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
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
               project_id, environment_id,
               allow_user_delete, created_at, updated_at
        FROM storage_targets ORDER BY name
        '''
    )


def get_storage_target(target_id):
    return query_one(
        '''
        SELECT id, name, provider, credential_id, target_config, cdn_domain,
               project_id, environment_id,
               allow_user_delete, created_at, updated_at
        FROM storage_targets WHERE id = ?
        ''',
        (target_id,),
    )


def upsert_storage_target(item):
    def work(conn):
        conn.execute(
            '''
            INSERT INTO storage_targets
            (id, name, provider, credential_id, target_config, cdn_domain,
             project_id, environment_id,
             allow_user_delete, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                provider = excluded.provider,
                credential_id = excluded.credential_id,
                target_config = excluded.target_config,
                cdn_domain = excluded.cdn_domain,
                project_id = excluded.project_id,
                environment_id = excluded.environment_id,
                allow_user_delete = excluded.allow_user_delete,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            ''',
            (
                item.get('id'),
                item.get('name'),
                item.get('provider'),
                item.get('credential_id'),
                json.dumps(item.get('target_config') or {}, ensure_ascii=False),
                item.get('cdn_domain'),
                item.get('project_id'),
                item.get('environment_id'),
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
