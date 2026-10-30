import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { resetAuthMock } from "@mocks/domains/auth";

/** 暴露当前 MemoryRouter 路径，断言不依赖落地页具体内容（落地页在 T4/T6/T8 才实现）。 */
function RouteProbe() {
  const location = useLocation();
  return <div data-testid="route">{location.pathname}</div>;
}
function renderAppAt(route: string) {
  return renderWithProviders(
    <>
      <RouteProbe />
      <AppRoutes />
    </>,
    { route },
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    localStorage.clear();
    resetAuthMock();
  });

  it("admin 登录成功后存储 token 并跳转 /tenants", async () => {
    const user = userEvent.setup();
    renderAppAt("/login");

    await user.type(screen.getByLabelText("用户名"), "admin");
    await user.type(screen.getByLabelText("密码"), "admin123");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() =>
      expect(localStorage.getItem("ov-dashboard-token")).toBe("jwt-admin"),
    );
    await waitFor(() => expect(screen.getByTestId("route")).toHaveTextContent("/tenants"));
  });

  it("team_admin 登录后跳转 /users", async () => {
    const user = userEvent.setup();
    renderAppAt("/login");
    await user.type(screen.getByLabelText("用户名"), "boss");
    await user.type(screen.getByLabelText("密码"), "boss-pass");
    await user.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(screen.getByTestId("route")).toHaveTextContent("/users"));
  });

  it("普通用户登录后跳转 /credentials", async () => {
    const user = userEvent.setup();
    renderAppAt("/login");
    await user.type(screen.getByLabelText("用户名"), "alice");
    await user.type(screen.getByLabelText("密码"), "alice-pass");
    await user.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() =>
      expect(screen.getByTestId("route")).toHaveTextContent("/credentials"),
    );
  });

  it("账密错误时展示统一文案、保留用户名且不写入 token", async () => {
    const user = userEvent.setup();
    renderAppAt("/login");
    await user.type(screen.getByLabelText("用户名"), "alice");
    await user.type(screen.getByLabelText("密码"), "wrong");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() =>
      expect(screen.getByText("用户名或密码错误")).toBeInTheDocument(),
    );
    expect((screen.getByLabelText("用户名") as HTMLInputElement).value).toBe("alice");
    expect(localStorage.getItem("ov-dashboard-token")).toBeNull();
    expect(within(document.body).queryByText(/\/credentials/)).toBeNull();
    // 登录端点 401 不代表会话过期，不应渲染过期警示条
    expect(screen.queryByText("登录状态已过期，请重新登录")).toBeNull();
  });
});
