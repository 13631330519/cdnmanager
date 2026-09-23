# 项目依赖层级规范

本文档定义了当前项目的依赖边界，所有新增代码都应遵守以下规则：

1. 允许上层引用下层。
2. 禁止下层引用上层。
3. 同级模块之间不允许互相引用。
4. 如果功能必须跨层调用，应优先迁移到更底层，或增加更低层的桥接接口，而不是让上层直接依赖下层的实现细节。

## 允许的层级顺序

cdnmanager.common、cdnmanager.config
  -> cdnmanager.db
  -> cdnmanager.providers
  -> cdnmanager.services
  -> cdnmanager.routes、 cdnmanager.views
  -> cdnmanager.__init__

说明：
- `common` 只放常量、工具函数、基础判断逻辑。
- `config` 负责配置项和启动参数。
- `db` 负责数据访问与业务查询接口。
- `providers` 负责第三方 CDN/DNS/存储 SDK 适配。
- `services` 负责业务编排和协同流程。
- `routes` 负责 HTTP 接口和权限检查。
- `views` 负责页面渲染和模板数据组装。
- `__init__.py` 负责应用装配，不承担业务逻辑。

## 必须遵守的禁止项

### 1. 前面的不能引用后面的

例如：
- `db` 不能直接 `import services`
- `providers` 不能直接 `import routes`
- `services` 不能直接 `import views`

### 2. 同层不能互相引用

例如：
- `routes` 之间不要互相 import
- `views` 和 `routes` 之间不应该互相依赖
- `db` 下不同文件之间如果需要共享能力，应放到更低层的公共模块或更高层的统一入口中，而不是交叉调用

## 迁移和接口放置原则

当某个能力“必须被更高层使用”时，优先执行以下顺序：

1. 判断它是否属于底层公共能力；
2. 如果属于公共能力，迁到 `common` 或 `db`；
3. 如果属于业务编排能力，迁到 `services`；
4. 如果属于 HTTP 接口能力，放到 `routes`；
5. 只有模板/页面逻辑才放在 `views`。

如果跨层必须访问，应优先通过“更底层统一 API”暴露，而不是让调用方直接依赖更上层模块的函数。

## 典型例子

### 例 1：可见域名逻辑

以前的错误模式：
- `views.py` 直接 `from cdnmanager.routes.cdn.domains import get_visible_domains`
- `routes` 中又实现了域名权限判断和查询函数

现在的方式：
- 通用查询和权限判断统一下沉到 `db/domains.py`
- `views` 与 `routes` 直接从 `db` 调用

### 例 2：凭据获取

以前的错误模式：
- `routes/common.py` 内部实现 `get_credential()`
- `services` 再依赖 `routes.common`

现在的方式：
- `db/credentials.py` 提供 `get_credential()`
- `service` / `route` 统一从 `db` 读取

### 例 3：存储目标解析

以前的错误模式：
- `routes/projects.py` 内部实现 `resolve_storage_target_for_domain()`
- `external_api` 直接从 `routes` 调用

现在的方式：
- `db/projects.py` 中保留统一的解析接口
- `routes` 和 `external_api` 统一使用 `db` 层的公共 API

## 自动检查

项目中已保留依赖层级检查脚本：

- [tests/test_project_layering.py](../tests/test_project_layering.py)

它会静态扫描所有 `cdnmanager` 模块，检测是否存在“高层模块引用低层模块以外的更高层依赖”的情况。

## 维护要求

新增模块时：
- 先确认归属层级；
- 不要因为“方便调用”直接跨层 import；
- 若涉及复用，应先抽象到更底层；
- 若确实需要跨层桥接，优先迁移到 `db` 或更底层公共接口，而不是在 `routes`/`views` 里做重复实现。

遵守这套规则后，代码结构会更稳定，测试与业务扩展也更容易维护。
