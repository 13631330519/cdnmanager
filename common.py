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
DNS_PROVIDERS = ['aliyun', 'tencent']
USER_ROLES = ['admin', 'domain_admin', 'user']
USER_ROLE_LABELS = {
    'admin': '管理员',
    'domain_admin': '域名管理员',
    'user': '普通用户',
}


def is_admin_role(role):
    return role == 'admin'


def can_edit_domain_provider(role):
    return role in ('admin', 'domain_admin')


def can_manage_all_domains(role):
    return role in ('admin', 'domain_admin')
PROVIDER_LABELS = {
    'alicdn': '阿里云CDN',
    'tencent': '腾讯云CDN',
    'lingzhi': '灵知开放平台',
    'akamai': 'Akamai CDN',
}

DNS_PROVIDER_LABELS = {
    'aliyun': '阿里云 DNS',
    'tencent': '腾讯云 DNSPod',
}

DNS_CREDENTIAL_FIELD_LABELS = {
    'aliyun': [
        {'name': 'access_key', 'label': 'AccessKey ID', 'type': 'text', 'placeholder': 'AccessKey ID'},
        {'name': 'secret_key', 'label': 'AccessKey Secret', 'type': 'password', 'placeholder': 'AccessKey Secret'},
    ],
    'tencent': [
        {'name': 'access_key', 'label': 'SecretId', 'type': 'text', 'placeholder': 'SecretId'},
        {'name': 'secret_key', 'label': 'SecretKey', 'type': 'password', 'placeholder': 'SecretKey'},
    ],
}

PROVIDER_LABELS_CDN = PROVIDER_LABELS

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

# CDN 提供商对应的 DNS CNAME 后缀（不含末尾点）
CDN_CNAME_SUFFIXES = {
    'lingzhi': 'xmdqkj.cn',
    'tencent': 'cdn.dnsv1.com',
}
KNOWN_CDN_CNAME_SUFFIXES = list(CDN_CNAME_SUFFIXES.values())


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


