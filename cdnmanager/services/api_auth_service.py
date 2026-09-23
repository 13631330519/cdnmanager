"""External API signature verification with per-project/environment keys."""

import hmac
import hashlib
from datetime import datetime

from flask import current_app

import cdnmanager.db as db



def default_api_secret():
    return current_app.config.get('EXTERNAL_API_SECRET', 'cdn_manager_external_secret')


def _sign(secret, message):
    return hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()


def resolve_domain_auth_context(domain_record):
    project = None
    environment = None
    if domain_record.get('project_id'):
        project = db.get_project(domain_record['project_id'])
    if domain_record.get('environment_id'):
        environment = db.get_environment(domain_record['environment_id'])
        if environment and not project:
            project = db.get_project(environment['project_id'])

    has_custom_key = bool(
        (project and project.get('api_key_secret'))
        or (environment and environment.get('api_key_secret'))
    )

    effective_secret = None
    if environment and environment.get('api_key_secret'):
        effective_secret = environment['api_key_secret']
    elif project and project.get('api_key_secret'):
        effective_secret = project['api_key_secret']
    else:
        effective_secret = default_api_secret()

    return {
        'project': project,
        'environment': environment,
        'has_custom_key': has_custom_key,
        'effective_secret': effective_secret,
    }


def validate_timestamp(timestamp, window_seconds=300):
    try:
        timestamp = int(timestamp)
    except (ValueError, TypeError):
        return False, 'timestamp 格式不正确'
    now_ts = int(datetime.now().timestamp())
    if abs(now_ts - timestamp) > window_seconds:
        return False, '请求已过期'
    return True, timestamp


def verify_domain_signature(domain_record, message, timestamp, signature):
    ok, timestamp_or_error = validate_timestamp(timestamp)
    if not ok:
        return False, timestamp_or_error

    ctx = resolve_domain_auth_context(domain_record)
    default_secret = default_api_secret()

    if ctx['has_custom_key'] and _sign(default_secret, message) == signature:
        return False, '该项目/环境已配置独立 API Key，不可使用公共默认 Key'

    if _sign(ctx['effective_secret'], message) == signature:
        return True, None

    return False, '验签失败'


def verify_message_signature(message, timestamp, signature, secret):
    ok, timestamp_or_error = validate_timestamp(timestamp)
    if not ok:
        return False, timestamp_or_error
    if _sign(secret, message) == signature:
        return True, None
    return False, '验签失败'


def verify_domain_job_signature(domain_record, job_id, timestamp, signature):
    ok, timestamp_or_error = validate_timestamp(timestamp)
    if not ok:
        return False, timestamp_or_error

    message = f"{domain_record['domain']}{job_id}{timestamp_or_error}"
    ctx = resolve_domain_auth_context(domain_record)
    default_secret = default_api_secret()

    if ctx['has_custom_key'] and _sign(default_secret, message) == signature:
        return False, '该项目/环境已配置独立 API Key，不可使用公共默认 Key'

    return verify_message_signature(message, timestamp_or_error, signature, ctx['effective_secret'])
