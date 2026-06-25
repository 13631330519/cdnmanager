# CDN Manager

CDN 管理后台，支持阿里云、腾讯云、灵知开放平台、Akamai。数据存储使用 SQLite（WAL 模式），支持 Gunicorn 多进程部署。

## 外部刷新接口

```
POST /api/refresh_url
Content-Type: application/json
```

必填字段：`url`、`timestamp`（秒）、`signature`

签名规则：

```
message = url + timestamp
signature = hmac.sha256(EXTERNAL_API_SECRET, message).hexdigest()
```

## Linux 自动启动（systemd）

### 方式一：一键安装（推荐）

在项目根目录执行：

```bash
sudo bash deploy/install.sh
```

默认安装路径 `/opt/cdnmanager`，数据目录 `/var/lib/cdnmanager`。

### 方式二：手动安装

```bash
# 1. 创建用户与目录
sudo useradd --system --home /opt/cdnmanager --shell /usr/sbin/nologin cdnmanager
sudo mkdir -p /opt/cdnmanager /var/lib/cdnmanager /etc/cdnmanager

# 2. 复制代码并安装依赖
sudo rsync -a --exclude '.git' --exclude 'venv' ./ /opt/cdnmanager/
cd /opt/cdnmanager
sudo python3 -m venv venv
sudo ./venv/bin/pip install -r requirements.txt

# 3. 配置环境变量
sudo cp deploy/cdnmanager.env.example /etc/cdnmanager/cdnmanager.env
sudo nano /etc/cdnmanager/cdnmanager.env   # 修改 SECRET_KEY、EXTERNAL_API_SECRET

# 4. 安装并启动 systemd 服务
sudo cp deploy/cdnmanager.service /etc/systemd/system/
sudo chown -R cdnmanager:cdnmanager /opt/cdnmanager /var/lib/cdnmanager
sudo systemctl daemon-reload
sudo systemctl enable cdnmanager
sudo systemctl start cdnmanager
```

### Nginx 反代（对外 80 端口）

Gunicorn 默认只监听 `127.0.0.1:8080`，推荐用 Nginx 对外：

```bash
sudo apt install nginx
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/cdnmanager
sudo ln -sf /etc/nginx/sites-available/cdnmanager /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 常用运维命令

```bash
systemctl status cdnmanager      # 查看状态
systemctl restart cdnmanager     # 重启
journalctl -u cdnmanager -f      # 查看日志
```

### 环境变量说明

| 变量 | 说明 | 默认 |
|------|------|------|
| `SECRET_KEY` | Flask Session 密钥 | 需修改 |
| `EXTERNAL_API_SECRET` | 外部 API 签名密钥 | 需修改 |
| `DATABASE_FILE` | SQLite 路径 | `/var/lib/cdnmanager/cdn_manager.db` |
| `GUNICORN_BIND` | 监听地址 | `127.0.0.1:8080` |
| `GUNICORN_WORKERS` | worker 数量 | CPU 核数 |
| `ENABLE_TASK_POLLING` | 后台轮询 | `true` |

### 更新部署

```bash
cd /path/to/cdnmanager
git pull
sudo bash deploy/install.sh
```

服务会自动重启，SQLite 数据库保留在 `/var/lib/cdnmanager`，不受影响。

## 本地开发

```bash
pip install -r requirements.txt
APP_PORT=8080 python app.py
```

默认账号：`admin / admin123`
