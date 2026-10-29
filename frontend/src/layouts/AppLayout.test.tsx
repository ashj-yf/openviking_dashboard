import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";
import { resetHealthMock } from "@mocks/domains/health";

// AppLayout 挂载 HealthDot，每个用例前统一复位健康探针的模块级 mock 状态。
beforeEach(() => resetHealthMock());

describe("AppLayout 用户菜单", () => {
  beforeEach(() => {
    localStorage.clear();
    resetAuthMock();
  });

  it("注销调用登出端点、清除 token 并回到登录页", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-admin");
    resetAuthMock(makeMe({ role: "admin" }));
    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { route: "/" });

    expect(await screen.findByTestId("user-menu")).toBeInTheDocument();
    await user.click(screen.getByTestId("user-menu"));
    await user.click(await screen.findByText("注销"));

    await waitFor(() => expect(screen.getByLabelText("用户名")).toBeInTheDocument());
    expect(localStorage.getItem("ov-dashboard-token")).toBeNull();
  });
});

describe("Sider RBAC 菜单", () => {
  beforeEach(() => {
    localStorage.clear();
    resetAuthMock();
    resetHealthMock();
  });

  it("admin 可见团队管理与用户管理，不可见我的凭证", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-admin");
    resetAuthMock(makeMe({ role: "admin" }));
    renderWithProviders(<AppRoutes />, { route: "/" });

    expect(await screen.findByText("团队管理")).toBeInTheDocument();
    expect(screen.getByText("用户管理")).toBeInTheDocument();
    expect(screen.queryByText("我的凭证")).toBeNull();
  });

  it("team_admin 可见用户管理与我的凭证，不可见团队管理", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-boss");
    resetAuthMock(makeMe({ id: 5, username: "boss", role: "team_admin", ov_role: "admin", account_id: "acme" }));
    renderWithProviders(<AppRoutes />, { route: "/" });

    expect(await screen.findByText("用户管理")).toBeInTheDocument();
    expect(screen.getByText("我的凭证")).toBeInTheDocument();
    expect(screen.queryByText("团队管理")).toBeNull();
  });

  it("普通用户仅可见我的凭证", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-alice");
    resetAuthMock(makeMe({ id: 3, username: "alice", role: "user", account_id: "acme" }));
    renderWithProviders(<AppRoutes />, { route: "/" });

    expect(await screen.findByText("我的凭证")).toBeInTheDocument();
    expect(screen.queryByText("团队管理")).toBeNull();
    expect(screen.queryByText("用户管理")).toBeNull();
  });

  it("顶栏展示当前登录用户名与健康灯", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-admin");
    resetAuthMock(makeMe({ username: "admin", role: "admin" }));
    renderWithProviders(<AppRoutes />, { route: "/" });

    expect(await screen.findByTestId("user-menu")).toHaveTextContent("admin");
    expect(
      await screen.findByRole("img", { name: /系统正常/ }),
    ).toBeInTheDocument();
  });
});
