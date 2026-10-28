# OpenViking Dashboard

OpenViking 多租户管理后台与用户看板。对接 OpenViking Admin API（v0.4.x，auth_mode=api_key），
实现租户（account）管理、租户内用户与 api_key 管理、用户数据看板（memories / skills /
resources / sessions）以及全局总览（console summary + observer）。

## 架构

```
┌──────────────┐     /api/v1      ┌────────────────┐   Admin API (root key)   ┌──────────────┐
│  React SPA   │  ──────────────▶ │  FastAPI 后端   │ ───────────────────────▶ │  OpenViking  │
│ Vite + antd  │ ◀──────────────  │  + httpx       │   Data API (admin key)   │  Server      │
└──────────────┘                  │  SQLite (ORM)  │ ◀─────────────────────── │ v0.4.13+     │
                                  └────────────────┘                          └──────────────┘
```

- **前端**：React 18 + TypeScript + Vite + Ant Design 5 + React Router + TanStack Query
- **后端**：FastAPI + SQLAlchemy 2.x (async) + aiosqlite + httpx + JWT(HS256)
- **身份模型**（与 OpenViking 一致）：
  - `ROOT`：root api_key 仅保存在后端 `.env`，用于 `/api/v1/admin/*`（账户/用户/密钥管理）
  - `ACCOUNT ADMIN`：创建租户时 OpenViking 返回的账户管理员 key，由后端**加密落库**，
    用于代理该账户的数据面 API（root key 访问数据面会 403）
  - `USER`：普通用户 key，签发后仅在界面展示一次，不入库
- **双链路**：管理操作走 Admin API（root key）；用户数据看板走数据面 API（账户 admin key
  + `X-OpenViking-Account` / `X-OpenViking-User` 头）

## 目录结构

```
backend/
  app/
    core/          # 配置、数据库、JWT、加密、依赖注入
    models/        # SQLAlchemy 模型：后台用户、租户、OV 用户映射、密钥记录、审计
    schemas/       # Pydantic 请求/响应模型
    services/
      openviking/  # OpenViking HTTP 客户端（admin.py / data.py / system.py）
      *.py         # 业务服务层（auth / tenant / key / overview / audit）
    api/v1/        # 路由：auth / tenants / users / keys / browse / overview / audit
frontend/
  src/
    api/           # axios 实例与各模块接口
    layouts/       # 主框架（侧边栏 + 顶栏）
    pages/         # overview / tenants / users / audit / login
    router/        # 路由表与权限守卫
    types/         # 与后端 schemas 对应的 TS 类型
```

## 启动

后端：

```bash
cd backend
uv sync
cp .env.example .env   # 填入 OPENVIKING_BASE_URL / OPENVIKING_ROOT_KEY / JWT_SECRET
uv run uvicorn app.main:app --reload --port 8000
# 首次启动自动建表并创建默认管理员 admin / admin123（请立即修改密码）
# API 文档: http://127.0.0.1:8000/docs
```

前端：

```bash
cd frontend
npm install
npm run dev            # http://127.0.0.1:5173 ，/api 自动代理到 8000
```

## 对接的 OpenViking 端点（v0.4.x OpenAPI 实测）

| 用途 | 方法 & 路径 |
| --- | --- |
| 账户列表 / 创建 | `GET/POST /api/v1/admin/accounts` |
| 账户详情 / 删除 | `GET/DELETE /api/v1/admin/accounts/{account_id}` |
| 账户配置 / 设置 | `GET/PATCH .../configuration`、`GET/PATCH .../settings` |
| 用户列表 / 注册 | `GET/POST .../users` |
| 用户删除 | `DELETE .../users/{user_id}` |
| 密钥（重）签发 | `POST .../users/{user_id}/key`（body: `{"seed": "..."} `，seed 可确定性重建） |
| 角色设置 | `PUT .../users/{user_id}/role` |
| 全局看板 | `GET /api/v1/console/dashboard/summary`、`/console/audit`、`/console/tokens` |
| 组件状态 | `GET /api/v1/observer/{queue,models,retrieval,system,vikingdb,filesystem,lock}` |
| 用户数据 | `/api/v1/skills`、`/api/v1/resources`、`/api/v1/sessions`、`/api/v1/fs/*`、`/api/v1/search/*` |

> 注意：root key 不能访问数据面 API（403）；数据面请求按账户自动隔离。
