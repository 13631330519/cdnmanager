import hmac
import hashlib
from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify, current_app
from cdnmanager.routes.cdn.credentials import get_credential
from cdnmanager.routes.cdn.domains import find_bound_domain
from cdnmanager.common import REFRESH_STATUS_NONE
from cdnmanager.db.models import get_domain, get_url_by_id, load_urls
from cdnmanager.services.refresh_service import record_url_refresh, refresh_and_record, submit_refresh

external_bp = Blueprint('external_bp', __name__)

def verify_external_signature(url, timestamp, signature):
    secret = current_app.config.get('EXTERNAL_API_SECRET', 'cdn_manager_external_secret')
    message = f"{url}{timestamp}".encode('utf-8')
    expected = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()
    return expected == signature


@external_bp.route('/api/task_status', methods=['GET'])
def api_task_status():
    domain = request.args.get('domain')
    url_idx = request.args.get('url_idx')
    if not domain and not url_idx:
        return jsonify({"success": False, "error": "domain 或 url_idx 参数必填"}), 400

    if domain:
        target = get_domain(domain)
        if not target:
            return jsonify({"success": False, "error": "域名不存在"}), 404

        return jsonify({
            "success": True,
            "domain": target['domain'],
            "provider": target.get('provider'),
            "refresh_status": target.get('refresh_status', REFRESH_STATUS_NONE),
            "last_refreshed_at": target.get('last_refreshed_at'),
            "task_id": target.get('task_id'),
            "task_status": target.get('refresh_task_status'),
            "status_detail": target.get('refresh_task_detail')
        })

    if url_idx is not None:
        try:
            url_id = int(url_idx)
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "url_idx 格式不正确"}), 400
        target = get_url_by_id(url_id)
    else:
        url = request.args.get('url')
        if not url:
            return jsonify({"success": False, "error": "url 或 url_idx 必填"}), 400
        target = next((u for u in load_urls() if u.get('url') == url), None)

    if not target:
        return jsonify({"success": False, "error": "URL 记录不存在"}), 404

    return jsonify({
        "success": True,
        "url": target.get('url'),
        "provider": target.get('provider'),
        "refresh_status": target.get('refresh_status', REFRESH_STATUS_NONE),
        "submitted_at": target.get('submitted_at'),
        "completed_at": target.get('completed_at'),
        "task_id": target.get('task_id'),
        "status_detail": target.get('refresh_task_detail')
    })


@external_bp.route('/api/refresh_url', methods=['POST'])
def api_refresh_url():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体必须为JSON"}), 400

    url = data.get('url')
    timestamp = data.get('timestamp')
    signature = data.get('signature')

    if not url or not timestamp or not signature:
        return jsonify({"success": False, "error": "url/timestamp/signature 均为必填字段"}), 400

    try:
        timestamp = int(timestamp)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "timestamp 格式不正确"}), 400

    now_ts = int(datetime.now().timestamp())
    if abs(now_ts - timestamp) > 300:
        return jsonify({"success": False, "error": "请求已过期"}), 400

    if not verify_external_signature(url, timestamp, signature):
        return jsonify({"success": False, "error": "验签失败"}), 403

    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return jsonify({"success": False, "error": "URL 域名解析失败"}), 400

    domain_record = find_bound_domain(host)
    if not domain_record:
        return jsonify({"success": False, "error": "未找到对应的已绑定域名"}), 404

    provider = domain_record.get('provider')
    credential_id = domain_record.get('credential_id')
    credential = get_credential(provider, credential_id)
    if not credential:
        return jsonify({"success": False, "error": "域名绑定的凭据不存在或已删除"}), 400

    result = submit_refresh(
        provider,
        domain_record['domain'],
        credential,
        url=url,
        cpcode=domain_record.get('cpcode'),
    )
    if result.get('error') and not result.get('success'):
        return jsonify({"success": False, "error": result.get('error', '刷新失败')}), 400

    record_url_refresh(domain_record['domain'], provider, credential_id, result, url)
    return jsonify(result)
