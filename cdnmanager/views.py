import json
from datetime import datetime

from flask import current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from cdnmanager.common import (
    CREDENTIAL_FIELD_LABELS,
    DNS_CREDENTIAL_FIELD_LABELS,
    DNS_PROVIDER_LABELS,
    PROVIDER_LABELS,
    STORAGE_CREDENTIAL_FIELD_LABELS,
    STORAGE_PROVIDER_LABELS,
    USER_ROLE_LABELS,
    VALID_PROVIDERS,
)
from cdnmanager.db.models import (
    load_credentials,
    load_dns_credentials,
    load_root_domains,
    load_storage_credentials,
    load_storage_targets,
    load_url_records,
    load_users,
)
from cdnmanager.db.projects import (
    filter_projects_tree,
    get_environment,
    get_project,
    get_user_project_ids,
    load_projects,
    load_projects_tree,
    user_can_access_project,
)
from cdnmanager.routes.cdn.domains import get_visible_domains


def register_views(app):
    @app.template_filter('datetimeformat')
    def datetimeformat(value, fmt='%Y-%m-%d %H:%M:%S'):
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return value.strftime(fmt)

    @app.route('/')
    def index():
        if 'username' not in session:
            return redirect(url_for('login'))
        users = load_users()
        user = next((u for u in users if u['username'] == session['username']), None)
        domains = get_visible_domains(user['username'], user['role'])
        credentials = load_credentials()
        dns_credentials = load_dns_credentials()
        root_domains = load_root_domains() if user['role'] == 'admin' else []
        all_usernames = [u['username'] for u in users]
        credential_lookup = {
            provider: {cred['id']: cred for cred in credentials.get(provider, [])}
            for provider in VALID_PROVIDERS
        }
        dns_credential_lookup = {
            provider: {cred['id']: cred for cred in dns_credentials.get(provider, [])}
            for provider in dns_credentials.keys()
        }
        provider_credentials_json = json.dumps(credentials, ensure_ascii=False)
        dns_credentials_json = json.dumps(dns_credentials, ensure_ascii=False)
        storage_credentials = load_storage_credentials()
        all_storage_targets = load_storage_targets()
        if user['role'] == 'admin':
            storage_targets = all_storage_targets
        else:
            storage_targets = [
                target for target in all_storage_targets
                if not target.get('project_id')
                or user_can_access_project(
                    user['username'],
                    user['role'],
                    next((p for p in load_projects() if p['id'] == target.get('project_id')), None),
                )
            ]
        storage_credentials_json = json.dumps({
            provider: [{'id': cred['id'], 'name': cred['name']} for cred in items]
            for provider, items in storage_credentials.items()
        }, ensure_ascii=False)
        refresh_records = [dict(item, _idx=item['id']) for item in load_url_records()]
        refresh_domain_options = sorted({d['domain'] for d in domains})
        all_projects_tree = load_projects_tree()
        projects_tree = filter_projects_tree(all_projects_tree, user['username'], user['role'])
        default_api_key = current_app.config.get('EXTERNAL_API_SECRET', 'cdn_manager_external_secret')
        projects_json = json.dumps(projects_tree, ensure_ascii=False)
        all_projects_list = load_projects() if user['role'] == 'admin' else []
        project_name_map = {project['id']: project['name'] for project in all_projects_list}
        user_project_map = {
            usr['username']: get_user_project_ids(usr['username'])
            for usr in users
        }
        user_project_map_json = json.dumps(user_project_map, ensure_ascii=False)

        def _storage_binding_label(target):
            project = get_project(target.get('project_id')) if target.get('project_id') else None
            environment = get_environment(target.get('environment_id')) if target.get('environment_id') else None
            if project and environment:
                return f"{project['name']}/{environment['name']}"
            if project:
                return project['name']
            return '-'

        storage_targets = [
            {**target, 'binding_label': _storage_binding_label(target)}
            for target in storage_targets
        ]
        all_projects_tree_json = json.dumps(all_projects_tree, ensure_ascii=False)

        return render_template(
            'index.html',
            user=user,
            domains=domains,
            credentials=credentials,
            dns_credentials=dns_credentials,
            root_domains=root_domains,
            credential_lookup=credential_lookup,
            dns_credential_lookup=dns_credential_lookup,
            provider_labels=PROVIDER_LABELS,
            dns_provider_labels=DNS_PROVIDER_LABELS,
            credential_field_labels=CREDENTIAL_FIELD_LABELS,
            dns_credential_field_labels=DNS_CREDENTIAL_FIELD_LABELS,
            provider_credentials_json=provider_credentials_json,
            dns_credentials_json=dns_credentials_json,
            users=users,
            all_usernames=all_usernames,
            refresh_records=refresh_records,
            refresh_domain_options=refresh_domain_options,
            user_role_labels=USER_ROLE_LABELS,
            storage_credentials=storage_credentials,
            storage_targets=storage_targets,
            storage_provider_labels=STORAGE_PROVIDER_LABELS,
            storage_credential_field_labels=STORAGE_CREDENTIAL_FIELD_LABELS,
            storage_credentials_json=storage_credentials_json,
            projects_tree=projects_tree,
            projects_json=projects_json,
            default_api_key=default_api_key,
            all_projects=all_projects_list,
            project_name_map=project_name_map,
            all_projects_tree=all_projects_tree if user['role'] == 'admin' else [],
            all_projects_tree_json=all_projects_tree_json if user['role'] == 'admin' else '[]',
            user_project_map=user_project_map if user['role'] == 'admin' else {},
            user_project_map_json=user_project_map_json,
        )

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            users = load_users()
            user = next((u for u in users if u['username'] == username), None)
            if user and check_password_hash(user['password'], password):
                session.permanent = True
                session['username'] = username
                return redirect(url_for('index'))
            flash('用户名或密码错误')
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))
