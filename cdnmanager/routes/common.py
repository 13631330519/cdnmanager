from flask import jsonify

from cdnmanager.db import get_user


def get_session_user():
    from flask import session

    username = session.get('username')
    if not username:
        return None
    user = get_user(username)
    if not user:
        return None
    return user


def require_login():
    from flask import session

    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401
    user = get_session_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    return None


def require_admin():
    login_error = require_login()
    if login_error is not None:
        return login_error
    user = get_session_user()
    if not user or user.get('role') != 'admin':
        return jsonify({'error': '无权限'}), 403
    return None


def require_admin_or_domain_admin():
    login_error = require_login()
    if login_error is not None:
        return login_error
    user = get_session_user()
    if not user or user.get('role') not in {'admin', 'domain_admin'}:
        return jsonify({'error': '无权限'}), 403
    return None


def require_role(*allowed_roles):
    login_error = require_login()
    if login_error is not None:
        return login_error
    user = get_session_user()
    if not user or user.get('role') not in allowed_roles:
        return jsonify({'error': '无权限'}), 403
    return None


