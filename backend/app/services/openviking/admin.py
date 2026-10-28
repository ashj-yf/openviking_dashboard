"""Admin API 封装：账户、用户、角色、密钥。路径依据 v0.4.13/14 OpenAPI。"""
from typing import Any

from app.services.openviking.client import OVClient


class OVAdminAPI:
    def __init__(self, client: OVClient):
        self.c = client

    # ---------- accounts ----------
    async def list_accounts(self) -> Any:
        return await self.c.request("GET", "/api/v1/admin/accounts")

    async def create_account(
        self,
        account_id: str,
        admin_user_id: str,
        *,
        seed: str | None = None,
        user_config: dict | None = None,
        settings: dict | None = None,
    ) -> Any:
        body: dict[str, Any] = {"account_id": account_id, "admin_user_id": admin_user_id}
        if seed is not None:
            body["seed"] = seed
        if user_config is not None:
            body["user_config"] = user_config
        if settings is not None:
            body["settings"] = settings
        return await self.c.request("POST", "/api/v1/admin/accounts", json=body)

    async def get_account(self, account_id: str) -> Any:
        return await self.c.request("GET", f"/api/v1/admin/accounts/{account_id}")

    async def delete_account(self, account_id: str) -> Any:
        return await self.c.request("DELETE", f"/api/v1/admin/accounts/{account_id}")

    # ---------- users ----------
    async def list_users(self, account_id: str) -> Any:
        return await self.c.request("GET", f"/api/v1/admin/accounts/{account_id}/users")

    async def register_user(
        self,
        account_id: str,
        user_id: str,
        *,
        role: str = "user",
        seed: str | None = None,
        user_config: dict | None = None,
    ) -> Any:
        body: dict[str, Any] = {"user_id": user_id, "role": role}
        if seed is not None:
            body["seed"] = seed
        if user_config is not None:
            body["user_config"] = user_config
        return await self.c.request(
            "POST", f"/api/v1/admin/accounts/{account_id}/users", json=body
        )

    async def delete_user(self, account_id: str, user_id: str) -> Any:
        return await self.c.request(
            "DELETE", f"/api/v1/admin/accounts/{account_id}/users/{user_id}"
        )

    async def set_role(self, account_id: str, user_id: str, role: str) -> Any:
        return await self.c.request(
            "PUT",
            f"/api/v1/admin/accounts/{account_id}/users/{user_id}/role",
            json={"role": role},
        )

    async def regenerate_key(
        self, account_id: str, user_id: str, *, seed: str | None = None
    ) -> Any:
        body = {"seed": seed} if seed is not None else None
        return await self.c.request(
            "POST",
            f"/api/v1/admin/accounts/{account_id}/users/{user_id}/key",
            json=body,
        )
