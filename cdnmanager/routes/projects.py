import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request

from cdnmanager.db import (
    _normalize_allowed_users,
    delete_environment,
    delete_project,
    generate_api_key,
    get_environment,
    get_project,
    get_environment_by_name,
    get_project_by_name,
    list_storage_targets_for_environment,
    load_projects_tree,
    resolve_storage_target_for_domain,
    sync_domain_tags_from_ids,
    upsert_environment,
    upsert_project,
    get_storage_target,
    load_domains,
    update_domain_fields,
)

from cdnmanager.routes.common import get_session_user, require_admin

project_bp = Blueprint('project_bp', __name__)


def _require_admin():
    denied = require_admin()
    if denied:
        return None, denied[0], denied[1]
    return get_session_user(), None, None


@project_bp.route('/api/projects', methods=['GET'])
def list_projects_route():
    user, err, status = _require_admin()
    if err:
        return err, status
    return jsonify({'success': True, 'projects': load_projects_tree()})


@project_bp.route('/api/projects', methods=['POST'])
def create_project_route():
    user, err, status = _require_admin()
    if err:
        return err, status

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip() or None
    allowed_users = _normalize_allowed_users(data.get('allowed_users'))
    if not name:
        return jsonify({'error': '项目名称必填'}), 400
    if get_project_by_name(name):
        return jsonify({'error': '项目名称已存在'}), 400

    now = datetime.now().isoformat()
    project_id = uuid.uuid4().hex[:12]
    upsert_project({
        'id': project_id,
        'name': name,
        'description': description,
        'api_key_secret': None,
        'allowed_users': allowed_users,
        'created_at': now,
        'updated_at': now,
    })
    return jsonify({'success': True, 'project': get_project(project_id)})


@project_bp.route('/api/projects/<project_id>', methods=['PUT'])
def update_project_route(project_id):
    user, err, status = _require_admin()
    if err:
        return err, status

    project = get_project(project_id)
    if not project:
        return jsonify({'error': '项目不存在'}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or project['name']).strip()
    description = data.get('description', project.get('description'))
    allowed_users = data.get('allowed_users', project.get('allowed_users'))
    if not name:
        return jsonify({'error': '项目名称必填'}), 400

    existing = get_project_by_name(name)
    if existing and existing['id'] != project_id:
        return jsonify({'error': '项目名称已存在'}), 400

    upsert_project({
        **project,
        'name': name,
        'description': description,
        'allowed_users': allowed_users,
        'updated_at': datetime.now().isoformat(),
    })
    _sync_domains_for_project(project_id)
    return jsonify({'success': True, 'project': get_project(project_id)})


@project_bp.route('/api/projects/<project_id>', methods=['DELETE'])
def delete_project_route(project_id):
    user, err, status = _require_admin()
    if err:
        return err, status
    if not get_project(project_id):
        return jsonify({'error': '项目不存在'}), 404

    for domain in load_domains():
        if domain.get('project_id') == project_id:
            update_domain_fields(domain['domain'], {
                'project_id': None,
                'environment_id': None,
                'projects': [],
                'environments': [],
            })

    delete_project(project_id)
    return jsonify({'success': True, 'message': '项目已删除'})


@project_bp.route('/api/projects/<project_id>/regenerate-key', methods=['POST'])
def regenerate_project_key_route(project_id):
    user, err, status = _require_admin()
    if err:
        return err, status
    project = get_project(project_id)
    if not project:
        return jsonify({'error': '项目不存在'}), 404

    api_key = generate_api_key()
    upsert_project({
        **project,
        'api_key_secret': api_key,
        'updated_at': datetime.now().isoformat(),
    })
    return jsonify({'success': True, 'api_key': api_key})


@project_bp.route('/api/projects/<project_id>/environments', methods=['POST'])
def create_environment_route(project_id):
    user, err, status = _require_admin()
    if err:
        return err, status
    if not get_project(project_id):
        return jsonify({'error': '项目不存在'}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': '环境名称必填'}), 400

    if get_environment_by_name(project_id, name):
        return jsonify({'error': '环境名称已存在'}), 400

    now = datetime.now().isoformat()
    environment_id = uuid.uuid4().hex[:12]
    upsert_environment({
        'id': environment_id,
        'project_id': project_id,
        'name': name,
        'api_key_secret': None,
        'created_at': now,
        'updated_at': now,
    })
    return jsonify({'success': True, 'environment': get_environment(environment_id)})


@project_bp.route('/api/projects/<project_id>/environments/<environment_id>', methods=['PUT'])
def update_environment_route(project_id, environment_id):
    user, err, status = _require_admin()
    if err:
        return err, status

    environment = get_environment(environment_id)
    if not environment or environment['project_id'] != project_id:
        return jsonify({'error': '环境不存在'}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or environment['name']).strip()
    if not name:
        return jsonify({'error': '环境名称必填'}), 400

    existing = get_environment_by_name(project_id, name)
    if existing and existing['id'] != environment_id:
        return jsonify({'error': '环境名称已存在'}), 400

    upsert_environment({
        **environment,
        'name': name,
        'updated_at': datetime.now().isoformat(),
    })
    _sync_domains_for_environment(environment_id)
    return jsonify({'success': True, 'environment': get_environment(environment_id)})


@project_bp.route('/api/projects/<project_id>/environments/<environment_id>', methods=['DELETE'])
def delete_environment_route(project_id, environment_id):
    user, err, status = _require_admin()
    if err:
        return err, status

    environment = get_environment(environment_id)
    if not environment or environment['project_id'] != project_id:
        return jsonify({'error': '环境不存在'}), 404

    for domain in load_domains():
        if domain.get('environment_id') == environment_id:
            projects, environments = sync_domain_tags_from_ids(domain.get('project_id'), None)
            update_domain_fields(domain['domain'], {
                'environment_id': None,
                'projects': projects,
                'environments': [],
            })

    delete_environment(environment_id)
    return jsonify({'success': True, 'message': '环境已删除'})


@project_bp.route('/api/projects/<project_id>/environments/<environment_id>/regenerate-key', methods=['POST'])
def regenerate_environment_key_route(project_id, environment_id):
    user, err, status = _require_admin()
    if err:
        return err, status

    environment = get_environment(environment_id)
    if not environment or environment['project_id'] != project_id:
        return jsonify({'error': '环境不存在'}), 404

    api_key = generate_api_key()
    upsert_environment({
        **environment,
        'api_key_secret': api_key,
        'updated_at': datetime.now().isoformat(),
    })
    return jsonify({'success': True, 'api_key': api_key})


def _sync_domains_for_project(project_id):
    project = get_project(project_id)
    if not project:
        return
    for domain in load_domains():
        if domain.get('project_id') == project_id:
            projects, environments = sync_domain_tags_from_ids(project_id, domain.get('environment_id'))
            update_domain_fields(domain['domain'], {'projects': projects, 'environments': environments})


def _sync_domains_for_environment(environment_id):
    environment = get_environment(environment_id)
    if not environment:
        return
    for domain in load_domains():
        if domain.get('environment_id') == environment_id:
            projects, environments = sync_domain_tags_from_ids(domain.get('project_id'), environment_id)
            update_domain_fields(domain['domain'], {'projects': projects, 'environments': environments})
