# 文件直传上传 — Phase 1 / Phase 2 实施计划

分支：`feat/upload-phase1`（Phase 1）→ `feat/upload-phase2`（Phase 2，自 Phase 1 合并后切出）

---

## Phase 1 — MVP（目标 4～6 周，当前分支实现核心骨架）

### 目标

- 管理端配置 **存储凭据**、**存储目标**（阿里云 OSS / 腾讯云 COS）
- 浏览器 **客户端直传**（不经 Flask 转发文件 body）
- 支持 **小文件单次 PUT**（≤100MB）与 **大文件分片**（>100MB，8MB/片）
- **Job + 单文件** 进度、完成校验（HEAD）、失败重试
- 上传完成后可选 **CDN URL 刷新**（绑定域名）

### 交付清单

| # | 模块 | 文件/路由 | 状态 |
|---|------|-----------|------|
| 1 | 数据模型 | `cdnmanager/db/models.py` — `storage_credentials`, `storage_targets`, `upload_jobs`, `upload_files`, `upload_parts` | ✅ Phase 1 |
| 2 | 常量 | `common.py` — `STORAGE_PROVIDERS`, 分片阈值 | ✅ Phase 1 |
| 3 | 存储凭据 CRUD | `cdnmanager/routes/storage/credentials.py`, `tab_storage_credentials.html` | ✅ Phase 1 |
| 4 | 存储目标 CRUD | `cdnmanager/routes/storage/targets.py`, `tab_storage_targets.html` | ✅ Phase 1 |
| 5 | OSS 适配 | `cdnmanager/providers/storage_oss.py` — presign PUT/multipart, HEAD, complete | ✅ Phase 1 |
| 6 | COS 适配 | `cdnmanager/providers/storage_cos.py` — 同上 | ✅ Phase 1 |
| 7 | 上传 API | `cdnmanager/routes/storage/uploads.py` — Job/文件生命周期 | ✅ Phase 1 |
| 8 | 上传 UI | `tab_upload.html`, `static/js/upload.js` | ✅ Phase 1 |
| 9 | 导航集成 | `base.html`, `index.html`, `app.py` | ✅ Phase 1 |
| 10 | 依赖 | `oss2`, `cos-python-sdk-v5` | ✅ Phase 1 |

### API（Phase 1）

```
POST   /save_storage_credential          管理员：保存 OSS/COS 凭据
POST   /delete_storage_credential
POST   /save_storage_target              管理员：bucket/region/前缀/CDN 域名
POST   /delete_storage_target

POST   /api/upload/jobs                  创建 Job + manifest
GET    /api/upload/jobs/{id}             Job 汇总进度
GET    /api/upload/jobs/{id}/files       文件列表（分页）

POST   /api/upload/files/{id}/start      初始化直传（PUT 或 multipart）
POST   /api/upload/files/{id}/presign-parts   领取更多分片 URL
POST   /api/upload/files/{id}/part-done       上报分片 ETag
POST   /api/upload/files/{id}/complete        完成 + 服务端 verify
POST   /api/upload/files/{id}/retry           失败重试
PATCH  /api/upload/files/{id}/progress        进度心跳
```

### 前端（Phase 1）

- 选择存储目标、远程前缀
- `webkitdirectory` / 多文件选择
- 调度器：小文件并发 20，大文件并发 3，分片并发 6
- 总进度条 + 失败列表 + 重试
- Job 完成后展示刷新结果

### 验收标准

- [ ] 100MB 以下文件直传 OSS/COS 成功，服务器 access log 无大 body
- [ ] 1GB 级文件分片上传、中断后可对 failed parts 重试
- [ ] Job 页显示 done_files/total_files、done_bytes/total_bytes
- [ ] complete 后 HEAD 校验失败会标记 failed
- [ ] 配置 CDN 域名后单 URL 刷新成功

### 不在 Phase 1

- FTP / tus / WebSocket
- 批量 presign（一次 50 URL）
- IndexedDB 断点恢复
- 天翼云 OOS
- WebSocket 推送

---

## Phase 2 — 规模化（目标 3～4 周，分支 `feat/upload-phase2`）

### 目标

- **数万文件** 批次稳定上传
- **断点续传**（刷新页面可恢复 Job）
- **批量 presign**、服务端 **超时扫描**
- **天翼云 OOS**（S3 兼容）
- **WebSocket** 进度推送（可选降级为轮询）

### 交付清单

| # | 模块 | 说明 |
|---|------|------|
| 1 | 批量 presign | `POST /api/upload/files/presign-batch`（≤50） |
| 2 | Manifest 分批 init | 每批 500～1000 文件，避免单次 JSON 过大 |
| 3 | IndexedDB | `upload.js` 持久化 queue + part 状态 |
| 4 | 虚拟列表 | 文件数 >500 时只渲染活跃/失败行 |
| 5 | WebSocket | `WS /api/upload/jobs/{id}/stream` 或 SSE |
| 6 | 超时 Worker | 后台线程：`uploading` 无心跳 >15min → failed |
| 7 | Verify 强化 | multipart ListParts 全量核对 |
| 8 | OOS 适配 | `providers/storage_oos.py`（boto3 S3） |
| 9 | Job 管理页 | 历史 Job、导出失败 manifest CSV |
| 10 | CDN 批量刷新 | 完成后按变更文件列表批量 refresh_url |

### API 增量（Phase 2）

```
POST   /api/upload/jobs/init-batch       分批追加 manifest
POST   /api/upload/files/presign-batch
GET    /api/upload/jobs                  历史列表
GET    /api/upload/jobs/{id}/manifest-failures.csv
WS     /api/upload/jobs/{id}/stream
```

### 性能指标（Phase 2 验收）

- 10,000 文件 × 500KB：Job 创建 <30s（分批 init）
- 客户端内存稳定，Tab 刷新后可 resume
- presign API P99 <200ms（批量接口）

### Phase 2 之后（Phase 3 预览，不在本计划实现）

- FTP 模式 A（临时账密 + CLI）
- FTP 模式 C（tus 中继 + Worker）
- FTP 模式 B（WS 代理，小文件可选）

---

## 分支策略

```
main
 └── feat/upload-phase1    ← 当前：Phase 1 实现
      └── feat/upload-phase2   Phase 1 合并后切出
```

合并要求：Phase 1 PR 需通过手动验收清单；Phase 2 依赖 Phase 1 表结构与 API 契约。
