# 外部文件上传 API 接入文档

本文描述通过 **签名鉴权** 调用 CDN Manager 上传接口。存储目标由域名绑定的项目 / 环境决定，客户端按 init 返回的 `mode` 选择路径：

- `mode = presign`：对象存储（OSS / COS / OOS）。服务端签发 PUT URL，**客户端直传**对象存储。
- `mode = proxy`：FTP / SFTP / FTPS。客户端把文件 **POST 到 CDN Manager**，由服务器写入远程目录。

两条路径共用同一套 HMAC 签名，完成时都调用 `POST /api/upload/complete`。

> 页面版说明见 `templates/partials/tab_api_docs.html`。

---

## 1. 架构说明

### 对象存储（`mode = presign`）

```
┌─────────────┐    ① init / presign / complete     ┌──────────────┐
│  你的服务    │ ─────────────────────────────────► │ CDN Manager  │
└─────────────┘                                    └──────────────┘
       │                                                    │
       │  ② 返回预签名 PUT URL                               │ 解析域名 → 项目/环境 → 存储目标
       ▼                                                    ▼
┌─────────────┐    ③ PUT 文件（直传，不经 CDN Manager）   ┌──────────────┐
│  你的服务    │ ─────────────────────────────────► │  OSS/COS/OOS │
└─────────────┘                                    └──────────────┘
       │
       │  ④ complete + ETag
       ▼
┌─────────────┐                                    ┌──────────────┐
│ CDN Manager │ ── Job 结束后自动刷新成功文件 ──► │  CDN 边缘节点 │
└─────────────┘                                    └──────────────┘
```

- 文件 **不经过** CDN Manager 转发，适合大文件与批量上传。
- 仅用于 OSS / COS / OOS。FTP 系列不要 PUT 预签名地址。

### FTP / SFTP / FTPS（`mode = proxy`）

```
┌─────────────┐    ① init（mode=proxy，不返回 PUT URL）  ┌──────────────┐
│  你的服务    │ ─────────────────────────────────► │ CDN Manager  │
└─────────────┘                                    └──────────────┘
       │
       │  ② POST /api/upload/proxy（multipart，文件经 CDN Manager）
       ▼
┌─────────────┐    ③ 服务器写入 FTP/SFTP/FTPS        ┌──────────────┐
│ CDN Manager │ ─────────────────────────────────► │ 远程目录      │
└─────────────┘                                    └──────────────┘
       │
       │  ④ complete（不需要 ETag）
       ▼
┌─────────────┐                                    ┌──────────────┐
│ CDN Manager │ ── Job 结束后自动刷新成功文件 ──► │  CDN 边缘节点 │
└─────────────┘                                    └──────────────┘
```

- 文件经 CDN Manager 转发，一次请求一个文件，不做分片。建议客户端并发不超过 3。
- 鉴权与「刷新 URL」接口相同，基于 **域名 + HMAC-SHA256**。
- 存储目标由域名绑定的 **项目 / 环境** 自动解析，无需在请求中传 Bucket 或主机密钥。

---

## 2. 接入前准备（管理后台）

按顺序完成以下配置：

| 步骤 | 位置 | 说明 |
|------|------|------|
| 1 | 项目管理 | 创建项目与环境（如 `prod`） |
| 2 | 项目管理 | 为项目或环境生成 **API Key**（推荐用环境级 Key） |
| 3 | 存储凭据 | 配置 OSS / COS / OOS，或 FTP / SFTP / FTPS 账号 |
| 4 | 存储目标 | 创建存储目标，**绑定同一项目与环境**。对象存储填 Bucket / Region；FTP 系列三个输入框依次为 Host、端口、根路径 |
| 5 | 域名管理 | 添加 CDN 域名，**绑定同一项目与环境**（用于解析存储目标，并在上传完成后刷新） |

FTP / SFTP / FTPS 默认校验 TLS 证书和主机密钥。旧环境无法校验时，在存储目标上勾选「允许不安全连接」（`insecure_tls`）。

**解析规则：**

- 请求中的 `domain` 必须是已在「域名管理」中登记的域名（或其绑定的主域）。
- 系统根据域名的 `environment_id` 查找该环境下的存储目标。
- 若同一环境有多个存储目标，可在 `init` 时传 `storage_target_id` 指定；否则使用第一个。

---

## 3. 鉴权

### 3.1 API Key 优先级

| 优先级 | 来源 |
|--------|------|
| 1（最高） | 域名绑定环境的 **环境 API Key** |
| 2 | 域名绑定项目的 **项目 API Key** |
| 3（默认） | 服务端环境变量 `EXTERNAL_API_SECRET` |

若项目或环境已配置独立 Key，**禁止使用**公共默认 Key，否则返回 403。

### 3.2 签名算法

```text
signature = HMAC-SHA256(secret, message).hexdigest()
```

- `secret`：按上表解析的有效 Key（UTF-8 字符串）
- `message`：见各接口说明（字符串直接拼接，无分隔符）
- `timestamp`：Unix 秒级时间戳，与服务器时差 **≤ 300 秒**

### 3.3 两类签名消息

| 场景 | message 组成 |
|------|----------------|
| 创建上传任务 `init` | `{domain}{timestamp}` |
| 任务内操作 `presign` / `proxy` / `complete` | `{domain}{job_id}{timestamp}` |

`proxy` 使用 `multipart/form-data`，签名字段仍是表单里的 `domain`、`job_id`、`timestamp`、`signature`，算法与 JSON 接口相同。

其中 `domain` 为系统中登记的**规范域名**（如 `cdn.example.com`），与请求里的 `domain` 字段一致（大小写不敏感，服务端会规范化）。

---

## 4. 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/upload/init` | 创建 Job、登记文件清单。对象存储批量签发小文件 PUT URL；FTP 系列返回 `mode=proxy` |
| `POST` | `/api/upload/presign` | 为尚未签发 URL 的对象存储小文件补签 PUT URL |
| `POST` | `/api/upload/proxy` | FTP / SFTP / FTPS：上传一个文件（multipart） |
| `POST` | `/api/upload/complete` | 上报上传完成、服务端校验、可选 CDN 刷新 |

**公共约定：**

- `init` / `presign` / `complete` 使用 `Content-Type: application/json`
- `/api/upload/proxy` 使用 `multipart/form-data`
- 响应均为 JSON；HTTP 4xx/5xx 时 `success` 为 `false`（若 body 可解析）
- Base URL 示例：`https://cdn-manager.example.com`

先看 init 响应里的 `mode`，再决定走 presign 还是 proxy。

---

## 5. 创建上传任务 — `POST /api/upload/init`

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `domain` | string | 是 | 已绑定的 CDN 域名 |
| `timestamp` | int/string | 是 | Unix 秒 |
| `signature` | string | 是 | 见 §3.3 init 消息 |
| `files` | array | 是 | 文件清单，见下表 |
| `remote_prefix` | string | 否 | 对象路径前缀，如 `2026/09/`（不要前导 `/`） |
| `storage_target_id` | string | 否 | 指定存储目标 ID；省略则取环境下第一个 |

**`files[]` 元素：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `relative_path` | string | 是 | 相对路径，如 `assets/app.js`（可用 `/` 或 `\`，服务端归一化） |
| `size` | int | 是 | 文件字节大小，≥ 0 |
| `mime` | string | 否 | MIME，默认 `application/octet-stream` |

**限制：** 首批最多 **1000** 个文件。

### 对象存储响应示例（`mode = presign`）

```json
{
  "success": true,
  "mode": "presign",
  "job_id": "a1b2c3d4e5f67890",
  "domain": "cdn.example.com",
  "storage_target_id": "st_oss_prod",
  "files": [
    {
      "id": "f001abc123456789",
      "relative_path": "assets/logo.png",
      "size": 204800,
      "multipart": false
    }
  ],
  "presigned": [
    {
      "file_id": "f001abc123456789",
      "mode": "put",
      "upload_url": "https://bucket.oss-cn-hangzhou.aliyuncs.com/...",
      "method": "PUT"
    }
  ],
  "presign_errors": []
}
```

- `presigned`：单文件 **≤ 100MB** 时自动签发 PUT URL（首批最多 **50** 个）。
- `multipart: true` 表示大文件（> 100MB）；**当前外部 API 不支持对象存储分片**，此类文件会出现在 `presign_errors` 或后续 `presign` 报错中。

### FTP / SFTP / FTPS 响应示例（`mode = proxy`）

不返回预签名 URL，`multipart` 恒为 `false`。对每个 `files[].id` 调用 `proxy.url`。

```json
{
  "success": true,
  "mode": "proxy",
  "provider": "ftps",
  "job_id": "a1b2c3d4e5f67890",
  "domain": "cdn.example.com",
  "storage_target_id": "st_ftp_prod",
  "files": [
    {
      "id": "f001abc123456789",
      "relative_path": "assets/logo.png",
      "size": 204800,
      "multipart": false
    }
  ],
  "proxy": {
    "url": "/api/upload/proxy",
    "method": "POST",
    "content_type": "multipart/form-data",
    "signature_message": "{domain}{job_id}{timestamp}",
    "fields": ["domain", "job_id", "file_id", "timestamp", "signature", "file"]
  }
}
```

### 错误示例

```json
{
  "success": false,
  "error": "该环境未配置存储目标，请在存储目标管理中绑定"
}
```

---

## 6. 补签 PUT URL — `POST /api/upload/presign`

仅对象存储。对 `init` 时未签发或签发失败的 **小文件** 批量补签。

若 Job 的目标是 FTP / SFTP / FTPS，本接口返回 400，`mode` 为 `proxy`，请改调 `/api/upload/proxy`。

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `domain` | string | 是 | 同 init |
| `job_id` | string | 是 | init 返回的 Job ID |
| `timestamp` | int/string | 是 | Unix 秒 |
| `signature` | string | 是 | 见 §3.3 任务内消息 |
| `file_ids` | array | 是 | 文件 ID 列表，最多 **50** 个 |

### 响应示例

```json
{
  "success": true,
  "files": [
    {
      "file_id": "f001abc123456789",
      "mode": "put",
      "upload_url": "https://...",
      "method": "PUT"
    }
  ],
  "errors": []
}
```

---

## 7. 直传对象存储（`mode = presign`）

使用 `presigned` / `files` 中的 `upload_url` 发起 **HTTP PUT**：

```http
PUT {upload_url} HTTP/1.1
Content-Type: application/octet-stream
Content-Length: {size}

{文件二进制内容}
```

**要点：**

- 必须使用 **PUT**（不是 POST 表单上传）。
- 请求体大小应与 `init` 登记的 `size` 一致，否则 `complete` 校验失败。
- 从响应头读取 **ETag**（去掉首尾双引号），供 `complete` 使用：

```http
ETag: "d41d8cd98f00b204e9800998ecf8427e"
```

→ 上报 `etag`: `d41d8cd98f00b204e9800998ecf8427e`

- 预签名 URL 有效期约 **3600 秒**，请在过期前完成 PUT。
- 仅用于 OSS / COS / OOS。

---

## 8. FTP / SFTP / FTPS 代理上传 — `POST /api/upload/proxy`

当 init 的 `mode` 为 `proxy` 时，对每个 `files[].id` 发一次 multipart POST。签名与 presign / complete 相同：`HMAC(domain + job_id + timestamp)`。不要调用 `/api/upload/presign`。

| 字段 | 必填 | 说明 |
|------|------|------|
| `domain` | 是 | 表单字段，同 init |
| `job_id` | 是 | init 返回的 Job ID |
| `file_id` | 是 | `files[].id`。远程相对路径以登记值为准 |
| `timestamp` | 是 | Unix 秒 |
| `signature` | 是 | 任务消息签名，不使用浏览器 Cookie |
| `file` | 是 | 文件内容。一次请求一个文件，不分片 |

### 响应示例

```json
{
  "success": true,
  "mode": "proxy",
  "provider": "ftps",
  "job_id": "a1b2c3d4e5f67890",
  "file_id": "f001abc123456789",
  "relative_path": "assets/logo.png",
  "result": {
    "path": "/www/cdn/2026/09/assets/logo.png",
    "size": 204800
  }
}
```

- 成功后文件已写入远程目录，但仍需调用 `complete` 才会把 Job 中的该文件标为完成。
- 对象存储调用本接口会返回 400，并提示改用预签名 PUT。
- 字节经过应用服务器。FTP 系列没有对象存储 ETag；`complete` 可以不传 `etag`。若远程 `SIZE`/`stat` 失败，只要代理上传已经写入字节，完成请求仍视为成功。

---

## 9. 完成上传 — `POST /api/upload/complete`

presign 与 proxy 都调用本接口。对象存储建议带上 PUT 响应的 ETag；FTP 系列可以省略。

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `domain` | string | 是 | 同 init |
| `job_id` | string | 是 | Job ID |
| `file_id` | string | 是 | 文件 ID |
| `timestamp` | int/string | 是 | Unix 秒 |
| `signature` | string | 是 | 见 §3.3 任务内消息 |
| `etag` | string | 否 | PUT 响应 ETag；对象存储省略时由服务端 HEAD 对象获取。FTP 系列不需要 |

### 响应示例

```json
{
  "success": true,
  "etag": "d41d8cd98f00b204e9800998ecf8427e",
  "public_url": "https://cdn.example.com/2026/09/assets/logo.png",
  "refresh": {
    "success": true,
    "refreshed": 1,
    "failed": 0,
    "results": [
      {
        "domain": "cdn.example.com",
        "url": "https://cdn.example.com/2026/09/assets/logo.png",
        "success": true
      }
    ]
  }
}
```

- `public_url`：Job 内文件全部结束后，服务端刷新成功文件时返回首个 CDN URL。上传完成后不要再调用 `POST /api/refresh_url`。
- 对象最终路径：`{remote_prefix}{relative_path}`（对象存储 Bucket 内，或 FTP 根路径之下）。

---

## 10. 完整流程示例（Python）

```python
import hashlib
import hmac
import json
import time
import urllib.request

BASE = "https://cdn-manager.example.com"
DOMAIN = "cdn.example.com"
API_SECRET = "your-environment-or-project-api-key"


def sign_init(domain: str) -> tuple[int, str]:
    ts = int(time.time())
    message = f"{domain}{ts}"
    sig = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return ts, sig


def sign_job(domain: str, job_id: str) -> tuple[int, str]:
    ts = int(time.time())
    message = f"{domain}{job_id}{ts}"
    sig = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return ts, sig


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def upload_file(local_path: str, remote_path: str) -> dict:
    with open(local_path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()

    ts, sig = sign_init(DOMAIN)
    init = post("/api/upload/init", {
        "domain": DOMAIN,
        "timestamp": ts,
        "signature": sig,
        "remote_prefix": "2026/09/",
        "files": [
            {"relative_path": remote_path, "size": size, "mime": "application/octet-stream"}
        ],
    })
    if not init.get("success"):
        raise RuntimeError(init.get("error"))

    job_id = init["job_id"]
    file_id = init["files"][0]["id"]

    if init.get("mode") == "proxy":
        # FTP / SFTP / FTPS：对每个 file_id POST /api/upload/proxy（multipart），
        # 成功后再 complete，且不要传 etag。签名与 presign 相同，见下方 cURL。
        raise RuntimeError("FTP/SFTP/FTPS 请 POST /api/upload/proxy，见下方 cURL")

    presigned = init.get("presigned") or []
    if not presigned:
        ts2, sig2 = sign_job(DOMAIN, job_id)
        presign = post("/api/upload/presign", {
            "domain": DOMAIN,
            "job_id": job_id,
            "timestamp": ts2,
            "signature": sig2,
            "file_ids": [file_id],
        })
        presigned = presign.get("files") or []

    upload_url = presigned[0]["upload_url"]
    with open(local_path, "rb") as f:
        data = f.read()
    put_req = urllib.request.Request(upload_url, data=data, method="PUT")
    with urllib.request.urlopen(put_req, timeout=300) as put_resp:
        etag = put_resp.headers.get("ETag", "").strip('"')

    ts3, sig3 = sign_job(DOMAIN, job_id)
    return post("/api/upload/complete", {
        "domain": DOMAIN,
        "job_id": job_id,
        "file_id": file_id,
        "timestamp": ts3,
        "signature": sig3,
        "etag": etag,
    })
```

对象存储走 `presigned` PUT，再 `complete` 并带上 ETag。FTP 系列走 `/api/upload/proxy`，再 `complete`，`etag` 可省略。

---

## 11. cURL 示例

### init

```bash
TS=$(date +%s)
DOMAIN="cdn.example.com"
SECRET="your-api-key"
MSG="${DOMAIN}${TS}"
SIG=$(printf '%s' "$MSG" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -sS -X POST "https://cdn-manager.example.com/api/upload/init" \
  -H "Content-Type: application/json" \
  -d "{
    \"domain\": \"$DOMAIN\",
    \"timestamp\": $TS,
    \"signature\": \"$SIG\",
    \"remote_prefix\": \"2026/09/\",
    \"files\": [{\"relative_path\": \"test/hello.txt\", \"size\": 12}]
  }"
```

### PUT（仅 `mode=presign`，将 `{upload_url}` 替换为上一步返回值）

```bash
curl -sS -X PUT "{upload_url}" \
  -H "Content-Type: application/octet-stream" \
  --data-binary "hello world!"
# 记录响应头 ETag
```

### proxy（仅 FTP / SFTP / FTPS，`mode=proxy`）

```bash
JOB_ID="..."
FILE_ID="..."
TS=$(date +%s)
MSG="${DOMAIN}${JOB_ID}${TS}"
SIG=$(printf '%s' "$MSG" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -sS -X POST "https://cdn-manager.example.com/api/upload/proxy" \
  -F "domain=$DOMAIN" \
  -F "job_id=$JOB_ID" \
  -F "file_id=$FILE_ID" \
  -F "timestamp=$TS" \
  -F "signature=$SIG" \
  -F "file=@./hello.txt"
# 成功后再调用 complete，etag 可省略
```

### complete

```bash
JOB_ID="..."
FILE_ID="..."
ETAG="..."
TS=$(date +%s)
MSG="${DOMAIN}${JOB_ID}${TS}"
SIG=$(printf '%s' "$MSG" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')

curl -sS -X POST "https://cdn-manager.example.com/api/upload/complete" \
  -H "Content-Type: application/json" \
  -d "{
    \"domain\": \"$DOMAIN\",
    \"job_id\": \"$JOB_ID\",
    \"file_id\": \"$FILE_ID\",
    \"timestamp\": $TS,
    \"signature\": \"$SIG\",
    \"etag\": \"$ETAG\"
  }"
```

---

## 12. 限制与约定

| 项 | 值 |
|----|-----|
| 单批 init 文件数 | 1000 |
| 单次 presign 文件数 | 50 |
| init 自动 presign 数量 | 50（仅对象存储） |
| 对象存储单文件 PUT 上限 | **100 MB**（`UPLOAD_MULTIPART_THRESHOLD`）。更大文件外部 API 不支持分片 |
| FTP / SFTP / FTPS | 单请求单文件，经服务器代理，不分片；建议并发 ≤ 3 |
| 分片大小（管理端内部分片） | 8 MB |
| 预签名 URL 有效期 | 3600 秒 |
| 时间戳有效窗口 | ±300 秒 |

---

## 13. 已知限制

1. **对象存储大文件（> 100MB）**：外部 API **暂不支持**分片上传；请在管理后台「文件存储」页上传，或拆分为 ≤100MB 文件。
2. **FTP / SFTP / FTPS** 不走预签名，也不做分片。init 返回 `mode=proxy` 后，用 `/api/upload/proxy` 上传，再 `complete`。`complete` 不要求 ETag。
3. **追加 manifest**：外部 API 无 `init-batch`；单次 init 最多 1000 文件，更多文件需多次 init（多个 Job）。
4. **Job 查询**：外部 API 不提供 Job 进度查询；请自行跟踪 `file_id` 与 `complete` 结果。
5. **CDN 刷新**：依赖存储目标与 CDN 域名绑定**相同项目与环境**；未绑定时 `complete` 仍成功，但 `refresh` 失败或无 `public_url`。调用上传 `complete` 后不要再请求 `POST /api/refresh_url`。

---

## 14. 常见错误

| HTTP | error | 处理建议 |
|------|-------|----------|
| 400 | `timestamp 格式不正确` / `请求已过期` | 校准服务器时间，重算签名 |
| 403 | `验签失败` | 检查 API Key 与 message 拼接顺序 |
| 403 | `不可使用公共默认 Key` | 改用项目/环境独立 Key |
| 400 | `域名未绑定项目环境` | 在域名管理中绑定项目与环境 |
| 400 | `该环境未配置存储目标` | 在存储目标中绑定同环境 |
| 400 | `FTP/SFTP/FTPS 不支持预签名` | init 的 `mode` 为 `proxy`，改调 `/api/upload/proxy` |
| 400 | `对象存储请使用预签名 PUT` | 不要对 OSS/COS/OOS 调用 `/api/upload/proxy` |
| 400 | `大文件请使用 start/multipart` | 文件 >100MB，见 §13 |
| 400 | `校验失败` / HEAD 大小不一致 | 确认 PUT 完整且 size 正确 |
| 404 | `Job 不存在或无权限` | job_id 与 domain 不匹配 |

---

## 15. 相关接口

- URL 刷新：`POST /api/refresh_url`（见 [README](../README.md)）
- 管理端会话上传（含大文件分片，以及浏览器里的 FTP 代理上传）：`POST /api/upload/jobs` 等（需登录 Cookie，见 `docs/upload-phase-plan.md`）
