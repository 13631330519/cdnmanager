import secrets
from datetime import datetime

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from cdnmanager.common import USER_ROLES
from cdnmanager.db import (
    delete_user, 
    get_user, 
    load_users, 
    remove_user_from_domains,
    upsert_user,
    remove_user_from_projects,
    sync_user_project_authorization,
)
from cdnmanager.routes.common import get_session_user, require_admin, require_login

user_bp = Blueprint('user_bp', __name__)


def _parse_project_ids(raw_value):
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(',') if item.strip()]


@user_bp.route('/save_user', methods=['POST'])
def save_user_route():
    denied = require_admin()
    if denied:
        return denied
    current_user = get_session_user()
    if not current_user or current_user.get('role') != 'admin':
        return jsonify({"error": "无权限保存用户"}), 403

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'user').strip()
    project_ids = _parse_project_ids(request.form.get('project_ids', '').strip())
    if not username:
        return jsonify({"error": "用户名不能为空"}), 400
    if role not in USER_ROLES:
        return jsonify({"error": "无效的角色"}), 400

    existing = get_user(username)
    generated_password = None
    if not existing:
        if not password:
            password = secrets.token_urlsafe(12)
            generated_password = password
        message = "用户已添加"
    else:
        message = "用户已更新"

    upsert_user({
        'username': username,
        'password': generate_password_hash(password) if password else existing.get('password'),
        'role': role,
        'created_at': existing.get('created_at') if existing else datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
    })
    if role != 'admin':
        sync_user_project_authorization(username, project_ids)
    else:
        remove_user_from_projects(username)

    response = {"success": True, "message": message}
    if generated_password:
        response['generated_password'] = generated_password
    return jsonify(response)


@user_bp.route('/change_password', methods=['POST'])
def change_password_route():
    login_error = require_login()
    if login_error is not None:
        return login_error
    current_user = get_session_user()
    if not current_user:
        return jsonify({"error": "用户不存在"}), 404

    old_password = request.form.get('old_password', '').strip()
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()

    if not old_password or not new_password:
        return jsonify({"error": "请填写当前密码和新密码"}), 400
    if new_password != confirm_password:
        return jsonify({"error": "两次输入的新密码不一致"}), 400
    if len(new_password) < 6:
        return jsonify({"error": "新密码至少 6 位"}), 400
    if not check_password_hash(current_user['password'], old_password):
        return jsonify({"error": "当前密码不正确"}), 400

    upsert_user({
        **current_user,
        'password': generate_password_hash(new_password),
        'updated_at': datetime.now().isoformat(),
    })
    return jsonify({"success": True, "message": "密码已更新"})


@user_bp.route('/delete_user', methods=['POST'])
def delete_user_route():
    denied = require_admin()
    if denied:
        return denied
    current_user = get_session_user()
    if not current_user or current_user.get('role') != 'admin':
        return jsonify({"error": "无权限删除用户"}), 403

    username = request.form.get('username', '').strip()
    if not username:
        return jsonify({"error": "用户名不能为空"}), 400
    if username == current_user['username']:
        return jsonify({"error": "无法删除当前登录用户"}), 400
    if username == 'admin':
        return jsonify({"error": "无法删除超级管理员"}), 400

    users = load_users()
    if not any(u['username'] == username for u in users):
        return jsonify({"error": "用户不存在"}), 404

    delete_user(username)
    remove_user_from_domains(username)
    remove_user_from_projects(username)
    return jsonify({"success": True, "message": "用户已删除"})
