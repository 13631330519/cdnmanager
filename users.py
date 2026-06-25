from datetime import datetime
from flask import Blueprint, jsonify, request, session
from werkzeug.security import generate_password_hash
from models import load_users, upsert_user, delete_user, get_user, remove_user_from_domains

user_bp = Blueprint('user_bp', __name__)


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

    existing = get_user(username)
    if not existing and not password:
        return jsonify({"error": "新用户必须设置密码"}), 400
    message = "用户已更新" if existing else "用户已添加"


    # apply single upsert
    upsert_user({
        'username': username,
        'password': generate_password_hash(password) if password else (get_user(username) or {}).get('password'),
        'role': role,
        'created_at': datetime.now().isoformat() if not get_user(username) else (get_user(username) or {}).get('created_at'),
        'updated_at': datetime.now().isoformat()
    })
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

    delete_user(username)
    remove_user_from_domains(username)
    return jsonify({"success": True, "message": "用户已删除"})
