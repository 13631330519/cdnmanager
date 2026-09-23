"""Project / environment persistence and access control."""

import json
import secrets
import uuid
from datetime import datetime

from cdnmanager.common import can_manage_all_domains
from cdnmanager.db.connection import query_all, query_one, run_write


def generate_api_key():
    return secrets.token_hex(32)


def _normalize_allowed_users(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return sorted(set(u.strip() for u in raw if u and str(u).strip()))
    if isinstance(raw, str):
        if not raw.strip():
            return []
        return sorted(set(u.strip() for u in raw.split(',') if u.strip()))
    return []


def user_can_access_project(username, role, project):
    if can_manage_all_domains(role):
        return True
    if not project:
        return True
    allowed_users = _normalize_allowed_users(project.get('allowed_users'))
    if not allowed_users:
        return True
    if '*' in allowed_users:
        return True
    return username in allowed_users


def load_projects():
    return query_all(
        '''
        SELECT id, name, description, api_key_secret, allowed_users, created_at, updated_at
        FROM projects ORDER BY name
        '''
    )


def get_project(project_id):
    return query_one(
        '''
        SELECT id, name, description, api_key_secret, allowed_users, created_at, updated_at
        FROM projects WHERE id = ?
        ''',
        (project_id,),
    )


def get_project_by_name(name):
    return query_one(
        '''
        SELECT id, name, description, api_key_secret, allowed_users, created_at, updated_at
        FROM projects WHERE name = ?
        ''',
        (name,),
    )


def upsert_project(project):
    allowed_users = _normalize_allowed_users(project.get('allowed_users'))

    def work(conn):
        conn.execute(
            '''
            INSERT INTO projects
            (id, name, description, api_key_secret, allowed_users, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                api_key_secret = excluded.api_key_secret,
                allowed_users = excluded.allowed_users,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            ''',
            (
                project['id'],
                project['name'],
                project.get('description'),
                project.get('api_key_secret'),
                json.dumps(allowed_users, ensure_ascii=False),
                project.get('created_at'),
                project.get('updated_at'),
            ),
        )

    run_write(work)


def delete_project(project_id):
    def work(conn):
        conn.execute('DELETE FROM projects WHERE id = ?', (project_id,))

    run_write(work)


def load_environments(project_id=None):
    if project_id:
        return query_all(
            '''
            SELECT id, project_id, name, api_key_secret, created_at, updated_at
            FROM project_environments
            WHERE project_id = ?
            ORDER BY name
            ''',
            (project_id,),
        )
    return query_all(
        '''
        SELECT id, project_id, name, api_key_secret, created_at, updated_at
        FROM project_environments ORDER BY project_id, name
        '''
    )


def get_environment(environment_id):
    return query_one(
        '''
        SELECT id, project_id, name, api_key_secret, created_at, updated_at
        FROM project_environments WHERE id = ?
        ''',
        (environment_id,),
    )


def get_environment_by_name(project_id, name):
    return query_one(
        '''
        SELECT id, project_id, name, api_key_secret, created_at, updated_at
        FROM project_environments
        WHERE project_id = ? AND name = ?
        ''',
        (project_id, name),
    )


def upsert_environment(environment):
    def work(conn):
        conn.execute(
            '''
            INSERT INTO project_environments
            (id, project_id, name, api_key_secret, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                project_id = excluded.project_id,
                name = excluded.name,
                api_key_secret = excluded.api_key_secret,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            ''',
            (
                environment['id'],
                environment['project_id'],
                environment['name'],
                environment.get('api_key_secret'),
                environment.get('created_at'),
                environment.get('updated_at'),
            ),
        )

    run_write(work)


def delete_environment(environment_id):
    def work(conn):
        conn.execute('DELETE FROM project_environments WHERE id = ?', (environment_id,))

    run_write(work)


def list_storage_targets_for_environment(environment_id):
    return query_all(
        '''
        SELECT id, name, provider, credential_id, target_config, cdn_domain,
               project_id, environment_id, allow_user_delete, created_at, updated_at
        FROM storage_targets
        WHERE environment_id = ?
        ORDER BY name
        ''',
        (environment_id,),
    )


def load_projects_tree():
    projects = load_projects()
    environments = load_environments()
    env_by_project = {}
    for env in environments:
        env_by_project.setdefault(env['project_id'], []).append(env)

    tree = []
    for project in projects:
        tree.append({
            **project,
            'environments': env_by_project.get(project['id'], []),
        })
    return tree


def filter_projects_tree(tree, username, role):
    if can_manage_all_domains(role):
        return tree
    return [project for project in tree if user_can_access_project(username, role, project)]


def get_user_project_ids(username):
    return [
        project['id']
        for project in load_projects()
        if username in _normalize_allowed_users(project.get('allowed_users'))
    ]


def sync_user_project_authorization(username, selected_project_ids):
    selected = set(selected_project_ids or [])
    now = datetime.now().isoformat()
    for project in load_projects():
        allowed = _normalize_allowed_users(project.get('allowed_users'))
        has_user = username in allowed
        should_have = project['id'] in selected
        if should_have and not has_user:
            allowed.append(username)
            allowed = sorted(set(allowed))
            upsert_project({**project, 'allowed_users': allowed, 'updated_at': now})
        elif not should_have and has_user:
            allowed = [user for user in allowed if user != username]
            upsert_project({**project, 'allowed_users': allowed, 'updated_at': now})


def remove_user_from_projects(username):
    now = datetime.now().isoformat()
    for project in load_projects():
        allowed = _normalize_allowed_users(project.get('allowed_users'))
        if username in allowed:
            allowed = [user for user in allowed if user != username]
            upsert_project({**project, 'allowed_users': allowed, 'updated_at': now})


def sync_domain_tags_from_ids(project_id, environment_id):
    projects = []
    environments = []
    if project_id:
        project = get_project(project_id)
        if project:
            projects = [project['name']]
    if environment_id:
        environment = get_environment(environment_id)
        if environment:
            environments = [environment['name']]
    return projects, environments


