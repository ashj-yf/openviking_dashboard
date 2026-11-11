import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { getAuthRequests, makeMe, resetAuthMock } from "@mocks/domains/auth";

function RouteProbe() {
  const location = useLocation();
  return <div data-testid="route">{location.pathname}</div>;
}

describe("强制改密门禁与改密页", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("must_change_password 的用户访问任意页被重定向到改密页", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-alice");
    resetAuthMock(makeMe({ id: 3, username: "alice", role: "user", must_change_password: true }));
    renderWithProviders(<AppRoutes />, { route: "/" });

    expect(await screen.findByRole("heading", { name: "修改密码" })).toBeInTheDocument();
  });

  it("无需改密的用户不被拦截", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-admin");
    resetAuthMock(makeMe({ role: "admin", must_change_password: false }));
    renderWithProviders(
      <>
        <RouteProbe />
        <AppRoutes />
      </>,
      { route: "/" },
    );

    await waitFor(() => expect(screen.getByTestId("route")).toHaveTextContent("/tenants"));
    expect(screen.queryByRole("heading", { name: "修改密码" })).toBeNull();
  });

  it("改密成功后门禁解除并跳转角色落地页", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-alice");
    resetAuthMock(makeMe({ id: 3, username: "alice", role: "user", must_change_password: true }));
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <RouteProbe />
        <AppRoutes />
      </>,
      { route: "/change-password" },
    );

    await user.type(screen.getByLabelText("旧密码"), "alice-old");
    await user.type(screen.getByLabelText("新密码"), "alice-new-2026");
    await user.type(screen.getByLabelText("确认新密码"), "alice-new-2026");
    await user.click(screen.getByRole("button", { name: "提交" }));

    await waitFor(() =>
      expect(screen.getByTestId("route")).toHaveTextContent("/credentials"),
    );
    // jsdom 下三段 type + 提交往返在高负载机器上超过默认 10s 预算；仅放宽时间，断言不变。
  }, 20000);

  it("改密页提供注销并切换账号出口：调用登出端点、清除会话并落地登录页", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-alice");
    resetAuthMock(makeMe({ id: 3, username: "alice", role: "user", must_change_password: true }));
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <RouteProbe />
        <AppRoutes />
      </>,
      { route: "/change-password" },
    );

    await screen.findByRole("heading", { name: "修改密码" });
    await user.click(screen.getByRole("button", { name: "注销并切换账号" }));

    await waitFor(() =>
      expect(getAuthRequests("POST").some((r) => r.url.includes("/auth/logout"))).toBe(true),
    );
    await waitFor(() => expect(screen.getByTestId("route")).toHaveTextContent("/login"));
    expect(localStorage.getItem("ov-dashboard-token")).toBeNull();
    expect(
      await screen.findByRole("heading", { name: "OpenViking 管理后台" }),
    ).toBeInTheDocument();
    // 强改密用户登出后不被门禁弹回改密页。
    expect(screen.queryByRole("heading", { name: "修改密码" })).toBeNull();
  }, 20000);

  it("旧密码错误时停留在改密页并显示后端文案", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-alice");
    resetAuthMock(makeMe({ id: 3, username: "alice", role: "user", must_change_password: true }));
    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { route: "/change-password" });

    await user.type(screen.getByLabelText("旧密码"), "bad-old");
    await user.type(screen.getByLabelText("新密码"), "alice-new-2026");
    await user.type(screen.getByLabelText("确认新密码"), "alice-new-2026");
    await user.click(screen.getByRole("button", { name: "提交" }));

    expect(await screen.findByText("旧密码不正确")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "修改密码" })).toBeInTheDocument();
    // 同文件：高负载下三段 type + 提交往返超 10s 预算，仅放宽时间，断言不变。
  }, 20000);
});

describe("超管账号 UI 保护", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("超管账号进入改密页仅显示 .env 提示，不提供表单", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-admin");
    resetAuthMock(
      makeMe({ id: 1, username: "rootadmin", role: "admin", is_env_admin: true }),
    );
    renderWithProviders(<AppRoutes />, { route: "/change-password" });

    expect(
      await screen.findByText(/超管账号密码仅可通过 \.env 配置修改/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("旧密码")).toBeNull();
    expect(screen.queryByRole("button", { name: "提交" })).toBeNull();
  });
});

describe("LDAP 用户改密页提示", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("test_change_password_page_shows_ldap_hint_for_ldap_user", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-alice");
    resetAuthMock(
      makeMe({
        id: 3,
        username: "alice",
        role: "user",
        auth_source: "ldap",
        ldap_bound: true,
        ldap_enabled: true,
      }),
    );
    renderWithProviders(<AppRoutes />, { route: "/change-password" });

    // 渲染提示卡而非表单（参照超管禁改模式）
    expect(
      await screen.findByText("密码由 LDAP 统一管理，请通过企业密码自助平台修改"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("旧密码")).toBeNull();
    expect(screen.queryByLabelText("新密码")).toBeNull();
    expect(screen.queryByRole("button", { name: "提交" })).toBeNull();
  });

  it("test_change_password_form_still_renders_for_local_user", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-alice");
    resetAuthMock(
      makeMe({ id: 3, username: "alice", role: "user", auth_source: "local" }),
    );
    renderWithProviders(<AppRoutes />, { route: "/change-password" });

    expect(await screen.findByLabelText("旧密码")).toBeInTheDocument();
    expect(screen.getByLabelText("新密码")).toBeInTheDocument();
    expect(screen.getByLabelText("确认新密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交" })).toBeInTheDocument();
  });
});
