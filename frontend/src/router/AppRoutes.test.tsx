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
