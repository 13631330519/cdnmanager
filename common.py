import os
import json

DATA_DIR = os.environ.get('DATA_DIR', 'data')
DATABASE_FILE = os.environ.get('DATABASE_FILE', os.path.join(DATA_DIR, 'cdn_manager.db'))
USER_FILE = os.path.join(DATA_DIR, 'users.json')
DOMAIN_FILE = os.path.join(DATA_DIR, 'domains.json')
CREDENTIALS_FILE = os.path.join(DATA_DIR, 'provider_credentials.json')
URL_FILE = os.path.join(DATA_DIR, 'urls.json')

LOG_DIR = os.environ.get('LOG_DIR', 'logs')

VALID_PROVIDERS = ['alicdn', 'tencent', 'lingzhi', 'akamai']
PROVIDER_LABELS = {
    'alicdn': '阿里云CDN',
    'tencent': '腾讯云CDN',
    'lingzhi': '灵知开放平台',
    'akamai': 'Akamai CDN',
}

CREDENTIAL_FIELD_LABELS = {
    'alicdn': [
        {'name': 'access_key', 'label': 'AccessKey', 'type': 'text', 'placeholder': 'AccessKey'},
        {'name': 'secret_key', 'label': 'SecretKey', 'type': 'password', 'placeholder': 'SecretKey'},
    ],
    'tencent': [
        {'name': 'access_key', 'label': 'SecretId', 'type': 'text', 'placeholder': 'SecretId'},
        {'name': 'secret_key', 'label': 'SecretKey', 'type': 'password', 'placeholder': 'SecretKey'},
    ],
    'lingzhi': [
        {'name': 'access_key', 'label': 'AccessKey', 'type': 'text', 'placeholder': 'AccessKey'},
        {'name': 'secret_key', 'label': 'SecretKey', 'type': 'password', 'placeholder': 'SecretKey'},
    ],
    'akamai': [
        {'name': 'extra_key', 'label': 'Client Token', 'type': 'text', 'placeholder': 'Client Token'},
        {'name': 'secret_key', 'label': 'Client Secret', 'type': 'password', 'placeholder': 'Client Secret'},
        {'name': 'access_key', 'label': 'Access Token', 'type': 'text', 'placeholder': 'Access Token'},
        {'name': 'extra_secret', 'label': 'API Host', 'type': 'text', 'placeholder': 'https://akab-xxx.luna.akamaiapis.net'},
    ],
}

REFRESH_STATUS_NONE = '--'
REFRESH_STATUS_REFRESHING = '正在刷新'
REFRESH_STATUS_COMPLETE = '已完成'
REFRESH_STATUS_FAILED = '刷新失败'


def log(log_entry):
    os.makedirs(DATA_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, "refresh_log.json")
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    else:
        logs = []
    logs.append(log_entry)
    logs = logs[-80:]
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)


