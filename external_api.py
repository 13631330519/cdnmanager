import hmac
import hashlib
from datetime import datetime
import json
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify, current_app
from credentials import get_credential
from domains import load_domains, find_bound_domain, record_refresh_submission
from providers.akamai import refresh_akamai
from providers.alicdn import refresh_alicdn
from providers.tencent import refresh_tencentcdn
from providers.lingzhi import refresh_lingzhi
from common import REFRESH_STATUS_NONE,safe_save_urls

external_bp = Blueprint('external_bp', __name__)

def verify_external_signature(url, timestamp, signature):
    secret = current_app.config.get('EXTERNAL_API_SECRET', 'cdn_manager_external_secret')
    message = f"{url}{timestamp}".encode('utf-8')
    expected = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()
    return expected == signature


@external_bp.route('/api/task_status', methods=['GET'])
def api_task_status():
    domain = request.args.get('domain')
    if not domain:
        return jsonify({"success": False, "error": "domain 参数必填"}), 400

    domains = load_domains()
    target = next((d for d in domains if d['domain'] == domain), None)
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

    if provider == 'alicdn':
        result = refresh_alicdn(domain_record['domain'], credential, url=url)
    elif provider == 'tencent':
        result = refresh_tencentcdn(domain_record['domain'], credential, url=url)
    elif provider == 'lingzhi':
        result = refresh_lingzhi(domain_record['domain'], credential, url=url)
    elif provider == 'akamai':
        result = refresh_akamai(domain_record['domain'], credential, url=url)
    else:
        return jsonify({"success": False, "error": "不支持的提供商"}), 400
    
    safe_save_urls(lambda urls: (True,urls + [{
        "url": url,
        "provider": provider,
        "credential_id": credential_id,
        "submitted_at": datetime.now().isoformat(),
        "completed_at": None,
        "task_id": result.get('task_id'),
        "refresh_status": result.get('task_status')
    }]))

    return jsonify(result)
