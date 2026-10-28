import pytest
from fastapi import HTTPException

from app.core.deps import assert_password_current
from app.models import DashboardUser


def _user(**kw):
    defaults = dict(id=1, username="u", password_hash="x", role="user",
                    is_active=True, must_change_password=False)
    defaults.update(kw)
    return DashboardUser(**defaults)


def test_gate_allows_auth_paths_when_must_change():
    assert_password_current(_user(must_change_password=True), "/api/v1/auth/change-password")
    assert_password_current(_user(must_change_password=True), "/api/v1/auth/me")


def test_gate_blocks_other_paths_when_must_change():
    with pytest.raises(HTTPException) as exc:
        assert_password_current(_user(must_change_password=True), "/api/v1/users")
    assert exc.value.status_code == 403


def test_gate_inactive_when_password_current():
    assert_password_current(_user(), "/api/v1/anything")
