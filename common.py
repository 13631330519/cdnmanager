import os
import json
import threading
from werkzeug.security import generate_password_hash

DATA_DIR = "data"
USER_FILE = os.path.join(DATA_DIR, "users.json")
DOMAIN_FILE = os.path.join(DATA_DIR, "domains.json")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "provider_credentials.json")
URL_FILE = os.path.join(DATA_DIR, "urls.json")

LOG_DIR = "logs"

VALID_PROVIDERS = ["alicdn", "tencent", "lingzhi", "akamai"]
PROVIDER_LABELS = {
    "alicdn": "阿里云CDN",
    "tencent": "腾讯云CDN",
    "lingzhi": "灵知开放平台",
    "akamai": "Akamai CDN"
}

DOMAINS_LOCK = threading.Lock()
URL_LOCK = threading.Lock()
REFRESH_STATUS_NONE = '--'
REFRESH_STATUS_REFRESHING = '正在刷新'
REFRESH_STATUS_COMPLETE = '已完成'
REFRESH_STATUS_FAILED = '刷新失败'


def ensure_data_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(USER_FILE):
        with open(USER_FILE, 'w', encoding='utf-8') as f:
            json.dump([
                {"username": "admin", "password": generate_password_hash("admin123"), "role": "admin", "created_at": "2026-06-09T16:00:00"},
                {"username": "user1", "password": generate_password_hash("user123"), "role": "user", "created_at": "2026-06-09T16:00:00"}
            ], f, indent=2, ensure_ascii=False)
    if not os.path.exists(DOMAIN_FILE):
        with open(DOMAIN_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=2, ensure_ascii=False)
    if not os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "alicdn": [],
                "tencent": [],
                "lingzhi": []
            }, f, indent=2, ensure_ascii=False)

def log(log_entry):
    os.makedirs(DATA_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, "refresh_log.json")
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    else:
        logs = []
    logs.append(log_entry)
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)


def load_urls():
    with URL_LOCK:
        with open(URL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

def safe_save_urls(function):
    with URL_LOCK:
        with open(URL_FILE, 'r', encoding='utf-8') as f:
            urls = json.load(f)

        ret,urls = function(urls)
        if not ret:
            return False

        with open(URL_FILE, 'w', encoding='utf-8') as f:
            json.dump(urls, f, indent=2, ensure_ascii=False)