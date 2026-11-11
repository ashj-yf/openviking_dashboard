import { act, screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { authExpired } from "@/api/client";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";

describe("路由鉴权", () => {
  beforeEach(() => {
    localStorage.clear();
    resetAuthMock();
  });

  it("未登录访问受保护页面跳转登录页", async () => {
    renderWithProviders(<AppRoutes />, { route: "/users" });
    expect(await screen.findByLabelText("用户名")).toBeInTheDocument();
  });

  it("会话中收到 401 过期事件后跳转登录页并提示", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-alice");
    resetAuthMock(makeMe({ id: 3, username: "alice", role: "user" }));
    renderWithProviders(<AppRoutes />, { route: "/" });
    expect(await screen.findByTestId("user-menu")).toBeInTheDocument();

    act(() => {
      authExpired.dispatchEvent(new Event("expired"));
    });

    expect(await screen.findByText("登录状态已过期，请重新登录")).toBeInTheDocument();
    expect(screen.getByLabelText("用户名")).toBeInTheDocument();
  });
});

describe("审计与总览路由权限", () => {
  beforeEach(() => {
    localStorage.clear();
    resetAuthMock();
  });

  it("user 访问 /overview 重定向 /403", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-alice");
    resetAuthMock(makeMe({ id: 3, username: "alice", role: "user", tenant_id: 1 }));
    renderWithProviders(<AppRoutes />, { route: "/overview" });
    expect(await screen.findByText("无权访问")).toBeInTheDocument();
  });

  it("user 访问 /audit-logs 重定向 /403", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-alice");
    resetAuthMock(makeMe({ id: 3, username: "alice", role: "user", tenant_id: 1 }));
    renderWithProviders(<AppRoutes />, { route: "/audit-logs" });
    expect(await screen.findByText("无权访问")).toBeInTheDocument();
  });

  it("team_admin 可进入 /overview 与 /audit-logs 占位页", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-boss");
    resetAuthMock(
      makeMe({ id: 5, username: "boss", role: "team_admin", tenant_id: 1, ov_role: "admin" }),
    );
    const { unmount } = renderWithProviders(<AppRoutes />, { route: "/overview" });
    expect(await screen.findByRole("heading", { name: "总览看板" })).toBeInTheDocument();
    unmount();
    renderWithProviders(<AppRoutes />, { route: "/audit-logs" });
    expect(await screen.findByRole("heading", { name: "审计日志" })).toBeInTheDocument();
  });
});
