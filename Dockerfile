# syntax=docker/dockerfile:1.7

# ---------- stage 1: frontend ----------
FROM node:22-alpine AS frontend
WORKDIR /build

# 先拷贝包清单以利用层缓存
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---------- stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    # 容器内 SQLite 固定落 /app/data（compose 绑定挂载；可被 .env 覆盖）
    DATABASE_URL=sqlite+aiosqlite:////app/data/dashboard.db

# 官方推荐的 uv 安装方式：从 pinned 发布镜像拷贝二进制
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

WORKDIR /app

# 先装依赖（利用层缓存）。backend 为非打包项目（package=false），
# 从锁文件导出运行期需求（不含 dev 组），安装到系统 Python。
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt \
    && uv pip install --system --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# 后端代码
COPY backend/app ./app

# 前端静态产物到固定目录（与 app.main.STATIC_DIR 对齐）
COPY --from=frontend /build/dist ./static

# 非 root 运行；数据目录归属运行用户以便挂载卷写入
RUN mkdir -p /app/data \
    && groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser \
        --home-dir /home/appuser --create-home appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
