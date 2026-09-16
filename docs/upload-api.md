# 外部文件上传 API 接入文档

本文描述通过 **签名鉴权** 调用 CDN Manager 上传接口，由**客户端直传对象存储**（OSS / COS / OOS），服务端仅负责签发凭证、校验与可选 CDN 刷新。

> 适用版本：`feat/upload-phase1` 及之后包含外部上传 API 的分支。

---

## 1. 架构说明

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
│ CDN Manager │ ── 可选 CDN 刷新 ────────────────► │  CDN 边缘节点 │
└─────────────┘                                    └──────────────┘
```

- 文件 **不经过** CDN Manager 服务器转发，适合大文件与批量上传。
- 鉴权与「刷新 URL」接口相同，基于 **域名 + HMAC-SHA256**。
- 存储目标由域名绑定的 **项目 / 环境** 自动解析，无需在请求中传 Bucket 密钥。

---

## 2. 接入前准备（管理后台）

按顺序完成以下配置：

| 步骤 | 位置 | 说明 |
|------|------|------|
| 1 | 项目管理 | 创建项目与环境（如 `prod`） |
| 2 | 项目管理 | 为项目或环境生成 **API Key**（推荐用环境级 Key） |
| 3 | 存储凭据 | 配置 OSS / COS / OOS 凭据 |
| 4 | 存储目标 | 创建存储目标，**绑定同一项目与环境**，填写 Bucket / Region |
| 5 | 域名管理 | 添加 CDN 域名，**绑定同一项目与环境**（用于解析存储目标；`refresh_after=1` 时用于刷新） |

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
| 任务内操作 `presign` / `complete` | `{domain}{job_id}{timestamp}` |

其中 `domain` 为系统中登记的**规范域名**（如 `cdn.example.com`），与请求 JSON 里的 `domain` 字段一致（大小写不敏感，服务端会规范化）。

---

## 4. 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/upload/init` | 创建 Job、登记文件清单、批量签发小文件 PUT URL |
| `POST` | `/api/upload/presign` | 为尚未签发 URL 的文件补签 PUT URL |
| `POST` | `/api/upload/complete` | 上报上传完成、服务端校验、可选 CDN 刷新 |

**公共约定：**

- `Content-Type: application/json`
- 响应均为 JSON；HTTP 4xx/5xx 时 `success` 为 `false`（若 body 可解析）
- Base URL 示例：`https://cdn-manager.example.com`

---

## 5. 创建上传任务 — `POST /api/upload/init`

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `domain` | string | 是 | 已绑定的 CDN 域名 |
| `timestamp` | int/string | 是 | Unix 秒 |
| `signature` | string | 是 | 见 §3.3 init 消息 |
| `files` | array | 是 | 文件清单，见下表 |
| `remote_prefix` | string | 否 | 对象存储路径前缀，如 `2026/09/`（不要前导 `/`） |
| `storage_target_id` | string | 否 | 指定存储目标 ID；省略则取环境下第一个 |
| `refresh_after` | bool/int | 否 | `1`/`true` 时，`complete` 成功后刷新 CDN 缓存 |

**`files[]` 元素：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `relative_path` | string | 是 | 相对路径，如 `assets/app.js`（可用 `/` 或 `\`，服务端归一化） |
| `size` | int | 是 | 文件字节大小，≥ 0 |
| `mime` | string | 否 | MIME，默认 `application/octet-stream` |

**限制：** 首批最多 **1000** 个文件。

### 响应示例

```json
{
  "success": true,
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
- `multipart: true` 表示大文件（> 100MB）；**当前外部 API 不支持大文件分片**，此类文件会出现在 `presign_errors` 或后续 `presign` 报错中。

### 错误示例

```json
{
  "success": false,
  "error": "该环境未配置存储目标，请在存储目标管理中绑定"
}
```

---

## 6. 补签 PUT URL — `POST /api/upload/presign`

对 `init` 时未签发或签发失败的 **小文件** 批量补签。

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

## 7. 直传对象存储

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

---

## 8. 完成上传 — `POST /api/upload/complete`

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `domain` | string | 是 | 同 init |
| `job_id` | string | 是 | Job ID |
| `file_id` | string | 是 | 文件 ID |
| `timestamp` | int/string | 是 | Unix 秒 |
| `signature` | string | 是 | 见 §3.3 任务内消息 |
| `etag` | string | 否 | PUT 响应 ETag；省略时由服务端 HEAD 对象获取 |

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

- `public_url`：仅当 `init` 时 `refresh_after=1` 且刷新成功时返回首个 CDN URL。
- 对象最终路径：`{remote_prefix}{relative_path}`（存储目标 Bucket 内）。

---

## 9. 完整流程示例（Python）

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


def upload_file(local_path: str, remote_path: str, refresh: bool = True) -> dict:
    with open(local_path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()

    ts, sig = sign_init(DOMAIN)
    init_body = {
        "domain": DOMAIN,
        "timestamp": ts,
        "signature": sig,
        "remote_prefix": "2026/09/",
        "refresh_after": refresh,
        "files": [
            {"relative_path": remote_path, "size": size, "mime": "application/octet-stream"}
        ],
    }
    init = post("/api/upload/init", init_body)
    if not init.get("success"):
        raise RuntimeError(init.get("error"))

    job_id = init["job_id"]
    file_id = init["files"][0]["id"]

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


if __name__ == "__main__":
    result = upload_file("./logo.png", "assets/logo.png")
    print(json.dumps(result, ensure_ascii=False, indent=2))
```

---

## 10. cURL 示例

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
    \"refresh_after\": true,
    \"files\": [{\"relative_path\": \"test/hello.txt\", \"size\": 12}]
  }"
```

### PUT（将 `{upload_url}` 替换为上一步返回值）

```bash
curl -sS -X PUT "{upload_url}" \
  -H "Content-Type: application/octet-stream" \
  --data-binary "hello world!"
# 记录响应头 ETag
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

## 11. 限制与约定

| 项 | 值 |
|----|-----|
| 单批 init 文件数 | 1000 |
| 单次 presign 文件数 | 50 |
| init 自动 presign 数量 | 50 |
| 单文件 PUT 上限 | **100 MB**（`UPLOAD_MULTIPART_THRESHOLD`） |
| 分片大小（内部分片上传） | 8 MB |
| 预签名 URL 有效期 | 3600 秒 |
| 时间戳有效窗口 | ±300 秒 |

---

## 12. 已知限制

1. **大文件（> 100MB）**：外部 API **暂不支持**分片上传流程；请在管理后台「文件存储」页上传，或拆分为 ≤100MB 文件。
2. **追加 manifest**：外部 API 无 `init-batch`；单次 init 最多 1000 文件，更多文件需多次 init（多个 Job）。
3. **Job 查询**：外部 API 不提供 Job 进度查询；请自行跟踪 `file_id` 与 `complete` 结果。
4. **CDN 刷新**：依赖存储目标与 CDN 域名绑定**相同项目与环境**；未绑定时 `complete` 仍成功，但 `refresh` 失败或无 `public_url`。

---

## 13. 常见错误

| HTTP | error | 处理建议 |
|------|-------|----------|
| 400 | `timestamp 格式不正确` / `请求已过期` | 校准服务器时间，重算签名 |
| 403 | `验签失败` | 检查 API Key 与 message 拼接顺序 |
| 403 | `不可使用公共默认 Key` | 改用项目/环境独立 Key |
| 400 | `域名未绑定项目环境` | 在域名管理中绑定项目与环境 |
| 400 | `该环境未配置存储目标` | 在存储目标中绑定同环境 |
| 400 | `大文件请使用 start/multipart` | 文件 >100MB，见 §12 |
| 400 | `校验失败` / HEAD 大小不一致 | 确认 PUT 完整且 size 正确 |
| 404 | `Job 不存在或无权限` | job_id 与 domain 不匹配 |

---

## 14. 相关接口

- URL 刷新：`POST /api/refresh_url`（见 [README](../README.md)）
- 管理端会话上传（含大文件分片）：`POST /api/upload/jobs` 等（需登录 Cookie，见 `docs/upload-phase-plan.md`）
