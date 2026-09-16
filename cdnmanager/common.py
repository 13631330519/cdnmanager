import os
import json

DATA_DIR = os.environ.get('DATA_DIR', 'data')
DATABASE_FILE = os.environ.get('DATABASE_FILE', os.path.join(DATA_DIR, 'cdn_manager.db'))
USER_FILE = os.path.join(DATA_DIR, 'users.json')
DOMAIN_FILE = os.path.join(DATA_DIR, 'domains.json')
CREDENTIALS_FILE = os.path.join(DATA_DIR, 'provider_credentials.json')
URL_FILE = os.path.join(DATA_DIR, 'urls.json')

LOG_DIR = os.environ.get('LOG_DIR', 'logs')

VALID_PROVIDERS = ['alicdn', 'tencent', 'lingzhi', 'akamai', 'ctyun', 'volcengine', 'x7host']
STORAGE_PROVIDERS = ['oss', 'cos', 'oos']
DNS_PROVIDERS = ['aliyun', 'tencent']

# 直传上传：超过此大小走分片（100MB）
UPLOAD_MULTIPART_THRESHOLD = 100 * 1024 * 1024
UPLOAD_PART_SIZE = 8 * 1024 * 1024
UPLOAD_PRESIGN_EXPIRES = 3600
UPLOAD_BATCH_INIT_SIZE = 1000
UPLOAD_PRESIGN_BATCH_MAX = 50
UPLOAD_JOB_MAX_FILES = 50000
UPLOAD_HEARTBEAT_TIMEOUT = 15 * 60
UPLOAD_VIRTUAL_LIST_THRESHOLD = 500
URL_RECORDS_PER_DOMAIN = 10

UPLOAD_JOB_PENDING = 'pending'
UPLOAD_JOB_RUNNING = 'running'
UPLOAD_JOB_COMPLETED = 'completed'
UPLOAD_JOB_PARTIAL = 'partial'
UPLOAD_JOB_FAILED = 'failed'
UPLOAD_JOB_CANCELLED = 'cancelled'

UPLOAD_FILE_PENDING = 'pending'
UPLOAD_FILE_UPLOADING = 'uploading'
UPLOAD_FILE_VERIFYING = 'verifying'
UPLOAD_FILE_COMPLETED = 'completed'
UPLOAD_FILE_FAILED = 'failed'
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


def can_storage_delete(user, storage_target=None):
    if not user:
        return False
    role = user.get('role')
    if role in ('admin', 'domain_admin'):
        return True
    if storage_target and storage_target.get('allow_user_delete'):
        return True
    return False
PROVIDER_LABELS = {
    'alicdn': '阿里云CDN',
    'tencent': '腾讯云CDN',
    'lingzhi': '灵知开放平台',
    'akamai': 'Akamai CDN',
    'ctyun': '天翼云CDN',
    'volcengine': '火山云CDN',
    'x7host': '小7托管CDN',
}

DNS_PROVIDER_LABELS = {
    'aliyun': '阿里云 DNS',
    'tencent': '腾讯云 DNSPod',
}

STORAGE_PROVIDER_LABELS = {
    'oss': '阿里云 OSS',
    'cos': '腾讯云 COS',
    'oos': '天翼云 OOS',
}

STORAGE_CREDENTIAL_FIELD_LABELS = {
    'oss': [
        {'name': 'access_key', 'label': 'AccessKey ID', 'type': 'text'},
        {'name': 'secret_key', 'label': 'AccessKey Secret', 'type': 'password'},
    ],
    'cos': [
        {'name': 'access_key', 'label': 'SecretId', 'type': 'text'},
        {'name': 'secret_key', 'label': 'SecretKey', 'type': 'password'},
    ],
    'oos': [
        {'name': 'access_key', 'label': 'AccessKey', 'type': 'text'},
        {'name': 'secret_key', 'label': 'SecretKey', 'type': 'password'},
    ],
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
    'ctyun': [
        {'name': 'access_key', 'label': 'AccessKey', 'type': 'text', 'placeholder': 'AccessKey（AK）'},
        {'name': 'secret_key', 'label': 'SecretKey', 'type': 'password', 'placeholder': 'SecretKey（SK）'},
    ],
    'volcengine': [
        {'name': 'access_key', 'label': 'AccessKey', 'type': 'text', 'placeholder': 'AccessKey ID'},
        {'name': 'secret_key', 'label': 'SecretKey', 'type': 'password', 'placeholder': 'Secret Access Key'},
    ],
    'x7host': [
        {'name': 'access_key', 'label': 'AppKey', 'type': 'text', 'placeholder': '游戏方 AppKey（最长 32 位）'},
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


def infer_domain_from_url(url):
    from urllib.parse import urlparse
    if not url:
        return None
    if url.startswith('https://') or url.startswith('http://'):
        return urlparse(url).hostname
    if '/' not in url and '.' in url:
        return url.split('/')[0]
    return None


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


