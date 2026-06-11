import json
from datetime import datetime
from flask import Blueprint, jsonify, request, session
from werkzeug.security import generate_password_hash
from common import USER_FILE, DOMAIN_FILE, DOMAINS_LOCK

user_bp = Blueprint('user_bp', __name__)


def load_users():
    with open(USER_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_users(users):
    with open(USER_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


def get_user(username):
    return next((u for u in load_users() if u['username'] == username), None)


def remove_user_from_domains(username):
    with DOMAINS_LOCK:
        with open(DOMAIN_FILE, 'r', encoding='utf-8') as f:
            domains = json.load(f)

        updated = False
        for domain in domains:
            allowed_users = domain.get('allowed_users')
            if isinstance(allowed_users, list) and username in allowed_users:
                domain['allowed_users'] = [u for u in allowed_users if u != username]
                updated = True

        if updated:
            with open(DOMAIN_FILE, 'w', encoding='utf-8') as f:
                json.dump(domains, f, indent=2, ensure_ascii=False)


@user_bp.route('/save_user', methods=['POST'])
def save_user_route():
    if 'username' not in session:
        return jsonify({"error": "未登录"}), 401
    current_user = get_user(session['username'])
    if not current_user or current_user.get('role') != 'admin':
        return jsonify({"error": "无权限保存用户"}), 403

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'user').strip()
    if not username:
        return jsonify({"error": "用户名不能为空"}), 400
    if role not in ['admin', 'user']:
        role = 'user'

    users = load_users()
    existing = next((u for u in users if u['username'] == username), None)
    if existing:
        existing['role'] = role
        if password:
            existing['password'] = generate_password_hash(password)
        existing['updated_at'] = datetime.now().isoformat()
        message = "用户已更新"
    else:
        if not password:
            return jsonify({"error": "新用户必须设置密码"}), 400
        users.append({
            "username": username,
            "password": generate_password_hash(password),
            "role": role,
            "created_at": datetime.now().isoformat()
        })
        message = "用户已添加"

    save_users(users)
    return jsonify({"success": True, "message": message})


@user_bp.route('/delete_user', methods=['POST'])
def delete_user_route():
    if 'username' not in session:
        return jsonify({"error": "未登录"}), 401
    current_user = get_user(session['username'])
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
    users = [u for u in users if u['username'] != username]
    save_users(users)
    remove_user_from_domains(username)
    return jsonify({"success": True, "message": "用户已删除"})
