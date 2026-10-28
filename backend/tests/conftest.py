"""pytest 全局夹具。环境变量必须在任何 app.* 模块导入前设置。"""
import os
import pathlib
import secrets
import tempfile

_TMP_DIR = pathlib.Path(tempfile.mkdtemp(prefix="ovdash-test-"))
os.environ.update(
    {
        "DEBUG": "false",
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP_DIR / 'global.db'}",
        "JWT_SECRET": secrets.token_urlsafe(48),
        "SECRET_KEY": secrets.token_urlsafe(48),
        "FIRST_ADMIN_USERNAME": "admin",
        "FIRST_ADMIN_PASSWORD": "Admin#12345",
        "OPENVIKING_ROOT_KEY": "test-root-key",
        "CORS_ORIGINS": "http://localhost:5173",
    }
)
