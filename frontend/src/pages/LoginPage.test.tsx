import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { useLocation } from "react-router-dom";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { authExpired } from "@/api/client";
import { server } from "@mocks/server";
import {
  getAuthRequests,
  getBindAuthHeaders,
  ldapBindHandler,
  mustBindLoginHandler,
  resetAuthMock,
} from "@mocks/domains/auth";

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

describe("LoginPage LDAP 绑定弹窗", () => {
  beforeEach(() => {
    localStorage.clear();
    resetAuthMock();
  });

  async function submitLogin(user: ReturnType<typeof userEvent.setup>, username: string) {
    await user.type(screen.getByLabelText("用户名"), username);
    await user.type(screen.getByLabelText("密码"), `${username}-pass`);
    await user.click(screen.getByRole("button", { name: "登录" }));
  }

  it("test_login_must_bind_shows_bind_modal", async () => {
    const user = userEvent.setup();
    server.use(mustBindLoginHandler("bind-jwt-test"));
    renderAppAt("/login");
    await submitLogin(user, "alice");

    // 弹窗出现：标题逐字，LDAP 账号默认填当前登录用户名
    expect(await screen.findByText("绑定 LDAP 账号")).toBeInTheDocument();
    expect(screen.getByLabelText("LDAP 账号")).toHaveValue("alice");
    // must_bind 不签发会话：不写 token-store、不导航，主表单不可再提交
    expect(localStorage.getItem("ov-dashboard-token")).toBeNull();
    expect(screen.getByTestId("route")).toHaveTextContent("/login");
    expect(screen.getByRole("button", { name: "登录" })).toBeDisabled();
    // 尚未发出绑定请求
    expect(getBindAuthHeaders()).toHaveLength(0);
    // antd Form 逐键校验定时器使交互用例较慢，放宽预算，断言不变。
  }, 20000);

  it("test_bind_success_shows_relogin_message_and_stays_on_login", async () => {
    const user = userEvent.setup();
    server.use(mustBindLoginHandler("bind-jwt-test"), ldapBindHandler(false));
    renderAppAt("/login");
    await submitLogin(user, "alice");
    await screen.findByText("绑定 LDAP 账号");

    await user.type(screen.getByLabelText("LDAP 密码"), "ldap-pass-2026");
    await user.click(screen.getByRole("button", { name: "绑定" }));

    // 成功提示逐字
    expect(await screen.findByText("绑定成功，请使用 LDAP 账号重新登录")).toBeInTheDocument();
    // bind_token 显式作为 Bearer 头携带（绑定阶段 token-store 为空，来源只能是登录响应）
    expect(getBindAuthHeaders()).toEqual(["Bearer bind-jwt-test"]);
    const bindPost = getAuthRequests("POST").find((r) => r.url.includes("/auth/ldap/bind"));
    expect(bindPost?.body).toMatchObject({ ldap_username: "alice" });
    // 弹窗关闭、留登录页、token-store 仍为空（须以 LDAP 账号重新登录）
    await waitFor(() => expect(screen.queryByText("绑定 LDAP 账号")).toBeNull());
    expect(screen.getByTestId("route")).toHaveTextContent("/login");
    expect(localStorage.getItem("ov-dashboard-token")).toBeNull();
    // 清登录表单：成功提示要求以 LDAP 账号重登，不得残留旧本地凭证诱导误重提
    expect(screen.getByLabelText("用户名")).toHaveValue("");
    expect(screen.getByLabelText("密码")).toHaveValue("");
    // antd Form 逐键校验定时器使交互用例较慢，放宽预算，断言不变。
  }, 20000);

  it("test_bind_failure_shows_inline_error_no_logout", async () => {
    const user = userEvent.setup();
    const expired = vi.fn();
    authExpired.addEventListener("expired", expired);
    server.use(mustBindLoginHandler("bind-jwt-test"), ldapBindHandler(true));
    renderAppAt("/login");
    await submitLogin(user, "alice");
    await screen.findByText("绑定 LDAP 账号");

    await user.type(screen.getByLabelText("LDAP 密码"), "wrong-ldap");
    await user.click(screen.getByRole("button", { name: "绑定" }));

    // 弹窗内内联错误（401 对象 detail 的 message），弹窗保持打开可重试
    expect(await screen.findByText("LDAP 账号或密码错误")).toBeInTheDocument();
    expect(screen.getByLabelText("LDAP 密码")).toBeInTheDocument();
    // 未广播 authExpired：监听未触发、无过期提示条、仍留登录页
    expect(expired).not.toHaveBeenCalled();
    expect(screen.queryByText("登录状态已过期，请重新登录")).toBeNull();
    expect(screen.getByTestId("route")).toHaveTextContent("/login");
    authExpired.removeEventListener("expired", expired);
    // antd Form 逐键校验定时器使交互用例较慢，放宽预算，断言不变。
  }, 20000);

  it("test_normal_login_unaffected", async () => {
    const user = userEvent.setup();
    renderAppAt("/login");
    await submitLogin(user, "alice");

    // 正常登录回归：照常写 token、按角色跳转，不弹绑定弹窗
    await waitFor(() => expect(localStorage.getItem("ov-dashboard-token")).toBe("jwt-alice"));
    await waitFor(() => expect(screen.getByTestId("route")).toHaveTextContent("/credentials"));
    expect(screen.queryByText("绑定 LDAP 账号")).not.toBeInTheDocument();
  }, 20000);
});
