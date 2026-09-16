import requests

from cdnmanager.common import log

X7HOST_REFRESH_URL = 'https://open.x7sy.com/h5/v1/cdn-refresh-tasks'


def refresh_x7host(domain, credentials, url=None):
    app_key = (credentials.get('access_key') or '').strip()
    if not app_key:
        return {'success': False, 'message': '请先配置小7托管 AppKey', 'provider': 'x7host'}
    if len(app_key) > 32:
        return {'success': False, 'message': 'AppKey 最大长度为 32', 'provider': 'x7host'}

    if url and not url.endswith('/'):
        refresh_type = 'file'
        urls = [url]
    else:
        refresh_type = 'directory'
        urls = [url] if url else [f'https://{domain}/', f'http://{domain}/']

    payload = {
        'urls': urls,
        'type': refresh_type,
        'appKey': app_key,
    }

    try:
        response = requests.post(
            X7HOST_REFRESH_URL,
            json=payload,
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            timeout=30,
        )
        log({'provider': 'x7host', 'payload': payload, 'status_code': response.status_code, 'body': response.text})

        if response.status_code == 200:
            return {
                'success': True,
                'message': f'小7托管 CDN 刷新已提交: {url or domain}',
                'provider': 'x7host',
            }

        data = {}
        if response.content:
            try:
                data = response.json()
            except ValueError:
                data = {'message': response.text}

        message = data.get('message') or f'小7托管刷新失败: HTTP {response.status_code}'
        if data.get('code'):
            message = f'{message} ({data.get("code")})'
        return {'success': False, 'message': message, 'provider': 'x7host', 'response': data}
    except Exception as exc:
        return {'success': False, 'message': f'小7托管刷新请求异常: {exc}', 'provider': 'x7host'}
