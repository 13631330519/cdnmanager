#!/usr/bin/env bash
# 若被 sh 调用则自动切换到 bash（Ubuntu 默认 sh 为 dash，不支持 pipefail）
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi
set -euo pipefail

# CDN Manager Linux 部署脚本
# 用法: sudo bash deploy/install.sh [/opt/cdnmanager]

APP_DIR="${1:-/opt/cdnmanager}"
APP_USER="cdnmanager"
APP_GROUP="cdnmanager"
ENV_DIR="/etc/cdnmanager"
ENV_FILE="${ENV_DIR}/cdnmanager.env"
DATA_DIR="/var/lib/cdnmanager"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行: sudo bash deploy/install.sh"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 python3，请先安装: apt install python3 python3-venv python3-pip rsync"
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "未找到 rsync，请先安装: apt install rsync"
  exit 1
fi

echo "==> 创建系统用户 ${APP_USER}"
if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
fi

echo "==> 部署代码到 ${APP_DIR}"
mkdir -p "${APP_DIR}"
rsync -a --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'data' \
  --exclude 'logs' \
  --exclude 'venv' \
  --exclude '.vscode' \
  ./ "${APP_DIR}/"

echo "==> 创建 Python 虚拟环境"
python3 -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "==> 校验 Python 依赖"
"${APP_DIR}/venv/bin/python" - <<'PY'
from alibabacloud_alidns20150109.client import Client as AlidnsClient
from Tea.core import TeaCore
print('DNS SDK OK')
PY

echo "==> 配置环境变量"
mkdir -p "${ENV_DIR}"
if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${APP_DIR}/deploy/cdnmanager.env.example" "${ENV_FILE}"
  echo "已生成 ${ENV_FILE}，请修改 SECRET_KEY 和 EXTERNAL_API_SECRET"
else
  echo "保留已有 ${ENV_FILE}"
fi

echo "==> 创建数据目录 ${DATA_DIR}"
mkdir -p "${DATA_DIR}"
chown -R "${APP_USER}:${APP_GROUP}" "${DATA_DIR}" "${APP_DIR}"

echo "==> 安装 systemd 服务"
cp "${APP_DIR}/deploy/cdnmanager.service" /etc/systemd/system/cdnmanager.service
systemctl daemon-reload
systemctl enable cdnmanager.service

echo "==> 启动服务"
systemctl restart cdnmanager.service
systemctl status cdnmanager.service --no-pager || true

cat <<EOF

部署完成。

常用命令:
  systemctl status cdnmanager
  systemctl restart cdnmanager
  journalctl -u cdnmanager -f

默认通过 Gunicorn 监听 127.0.0.1:8080。
如需对外提供 80 端口，安装 Nginx 并参考:
  deploy/nginx.conf.example

首次部署请编辑:
  ${ENV_FILE}

EOF
