import json

from cdnmanager.common import REFRESH_STATUS_REFRESHING, URL_RECORDS_PER_DOMAIN, can_manage_all_domains, infer_domain_from_url
from cdnmanager.db.connection import query_all,query_one,run_write
from cdnmanager.db.projects import get_project, user_can_access_project

def _url_select_columns():
    return 'id, domain, url, provider, credential_id, submitted_at, completed_at, task_id, refresh_status, refresh_task_detail'


def _slice_url_records(rows, limit):
    if not rows:
        return []
    sliced = rows[:limit]
    for row in rows[limit:]:
        if row.get('refresh_status') == REFRESH_STATUS_REFRESHING:
            sliced.append(row)
    return sliced


def user_can_access_domain(username, role, domain):
    if can_manage_all_domains(role):
        return True
    if domain.get('project_id'):
        project = get_project(domain['project_id'])
        if project:
            return user_can_access_project(username, role, project)
        return False
    allowed_users = domain.get('allowed_users')
    if allowed_users is None:
        return True
    if isinstance(allowed_users, list) and ('*' in allowed_users or username in allowed_users):
        return True
    if domain.get('added_by') == username:
        return True
    return False


def get_visible_domains(username, role):
    visible = []
    for domain in load_domains():
        if not can_manage_all_domains(role) and not user_can_access_domain(username, role, domain):
            continue
        visible.append(domain)
    return visible


def find_bound_domain(host):
    host = (host or '').lower().strip()
    if not host:
        return None
    domains = load_domains()
    candidates = [d for d in domains if d.get('domain') and (host == d['domain'].lower() or host.endswith('.' + d['domain'].lower()))]
    if not candidates:
        return None
    return max(candidates, key=lambda d: len(d['domain']))


def load_domains():
    return query_all(
        '''
        SELECT domain, domain_name, provider, credential_id, cpcode, projects, environments,
               project_id, environment_id,
               allowed_users, added_by, added_at, refresh_status, last_refreshed_at, task_id,
               refresh_task_status, refresh_task_detail
        FROM domains ORDER BY domain
        '''
    )


def get_domain(domain):
    return query_one(
        '''
        SELECT domain, domain_name, provider, credential_id, cpcode, projects, environments,
               project_id, environment_id,
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
            INSERT INTO domains
            (domain, domain_name, provider, credential_id, cpcode, projects, environments,
             project_id, environment_id, allowed_users,
             added_by, added_at, refresh_status, last_refreshed_at, task_id, refresh_task_status,
             refresh_task_detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                domain_name = excluded.domain_name,
                provider = excluded.provider,
                credential_id = excluded.credential_id,
                cpcode = excluded.cpcode,
                projects = excluded.projects,
                environments = excluded.environments,
                project_id = excluded.project_id,
                environment_id = excluded.environment_id,
                allowed_users = excluded.allowed_users,
                added_by = excluded.added_by,
                added_at = excluded.added_at,
                refresh_status = excluded.refresh_status,
                last_refreshed_at = excluded.last_refreshed_at,
                task_id = excluded.task_id,
                refresh_task_status = excluded.refresh_task_status,
                refresh_task_detail = excluded.refresh_task_detail
            ''',
            (
                domain.get('domain'),
                domain.get('domain_name'),
                domain.get('provider'),
                domain.get('credential_id'),
                domain.get('cpcode'),
                json.dumps(domain.get('projects', []), ensure_ascii=False),
                json.dumps(domain.get('environments', []), ensure_ascii=False),
                domain.get('project_id'),
                domain.get('environment_id'),
                json.dumps(domain.get('allowed_users', []), ensure_ascii=False),
                domain.get('added_by'),
                domain.get('added_at'),
                domain.get('refresh_status'),
                domain.get('last_refreshed_at'),
                domain.get('task_id'),
                domain.get('refresh_task_status'),
                json.dumps(domain.get('refresh_task_detail'), ensure_ascii=False)
                if domain.get('refresh_task_detail') is not None else None,
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
        elif key in {'project_id', 'environment_id'}:
            set_clauses.append(f'{key} = ?')
            params.append(value)
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


def insert_url_record(url):
    domain = url.get('domain') or infer_domain_from_url(url.get('url'))

    def work(conn):
        cursor = conn.execute(
            '''
            INSERT INTO urls
            (domain, url, provider, credential_id, submitted_at, completed_at, task_id, refresh_status, refresh_task_detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                domain,
                url.get('url'),
                url.get('provider'),
                url.get('credential_id'),
                url.get('submitted_at'),
                url.get('completed_at'),
                url.get('task_id'),
                url.get('refresh_status'),
                json.dumps(url.get('refresh_task_detail'), ensure_ascii=False)
                if url.get('refresh_task_detail') is not None else None,
            ),
        )
        return cursor.lastrowid

    row_id = run_write(work)
    if domain:
        prune_urls_for_domain(domain)
    return row_id

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
        f'''
        SELECT {_url_select_columns()}
        FROM urls WHERE id = ?
        ''',
        (url_id,),
    )


def load_url_records(domain=None, limit_per_domain=URL_RECORDS_PER_DOMAIN):
    columns = _url_select_columns()
    if domain:
        rows = query_all(
            f'SELECT {columns} FROM urls WHERE domain = ? ORDER BY id DESC',
            (domain,),
        )
        return list(reversed(_slice_url_records(rows, limit_per_domain)))

    rows = query_all(f'SELECT {columns} FROM urls ORDER BY id DESC')
    grouped = {}
    for row in rows:
        key = row.get('domain') or '__unknown__'
        grouped.setdefault(key, []).append(row)

    result = []
    for items in grouped.values():
        result.extend(_slice_url_records(items, limit_per_domain))
    result.sort(key=lambda item: item.get('id') or 0, reverse=True)
    return result

def prune_urls_for_domain(domain, keep=URL_RECORDS_PER_DOMAIN):
    if not domain:
        return

    def work(conn):
        rows = conn.execute(
            'SELECT id, refresh_status FROM urls WHERE domain = ? ORDER BY id DESC',
            (domain,),
        ).fetchall()
        if len(rows) <= keep:
            return
        keep_ids = {row['id'] for row in _slice_url_records(
            [{'id': row['id'], 'refresh_status': row['refresh_status']} for row in rows],
            keep,
        )}
        for row in rows:
            if row['id'] not in keep_ids:
                conn.execute('DELETE FROM urls WHERE id = ?', (row['id'],))

    run_write(work)


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
        f'''
        SELECT {_url_select_columns()}
        FROM urls
        WHERE refresh_status = ? AND task_id IS NOT NULL
        ''',
        (REFRESH_STATUS_REFRESHING,),
    )


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
