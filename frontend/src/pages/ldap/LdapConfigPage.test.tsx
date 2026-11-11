import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";
import { resetHealthMock } from "@mocks/domains/health";
import { resetUsersMock } from "@mocks/domains/users";
import {
  getLdapRequests,
  makeLdapConfig,
  makeTestResult,
  resetLdapMock,
  setLdapTestResult,
} from "@mocks/domains/ldap";

function resetSession(role: "admin" | "team_admin") {
  localStorage.setItem("ov-dashboard-token", role === "admin" ? "jwt-admin" : "jwt-boss");
  resetAuthMock(
    role === "admin"
      ? makeMe({ role: "admin" })
      : makeMe({
          id: 5,
          username: "boss",
          role: "team_admin",
          tenant_id: 1,
          account_id: "acme",
          ov_user_id: "boss",
          ov_role: "admin",
          has_ov_key: true,
        }),
  );
  resetHealthMock();
  resetUsersMock();
}

/** 已保存过的配置样例：has_bind_password=true，密码框应空但有占位提示。 */
const SAVED_CONFIG = makeLdapConfig({
  enabled: true,
  server_host: "ldap.test",
  server_port: 636,
  encryption: "ldaps",
  bind_dn: "cn=svc,dc=test",
  user_base_dn: "ou=people,dc=test",
  has_bind_password: true,
});

describe("LdapConfigPage", () => {
  beforeEach(() => {
    localStorage.clear();
    resetLdapMock();
  });

  it("test_renders_saved_config", async () => {
    resetSession("admin");
    resetLdapMock(SAVED_CONFIG);
    renderWithProviders(<AppRoutes />, { route: "/ldap-config" });

    // GET 回填：文本/数字/下拉/可选字段逐项落位
    // （findBy 可能落在表单已挂载但 setFieldsValue 尚未渲染的中间帧，先等回填落地）
    await screen.findByLabelText("服务器地址");
    await waitFor(() => expect(screen.getByLabelText("服务器地址")).toHaveValue("ldap.test"));
    expect((screen.getByLabelText("端口") as HTMLInputElement).value).toBe("636");
    expect(screen.getByText("LDAPS", { selector: ".ant-select-selection-item" })).toBeInTheDocument();
    expect(screen.getByLabelText("Bind DN（可选）")).toHaveValue("cn=svc,dc=test");
    expect(screen.getByLabelText("用户 Base DN")).toHaveValue("ou=people,dc=test");
    expect(screen.getByRole("switch")).toBeChecked();
    // 密码只写不读：输入框恒为空，仅以占位提示告知已存密文
    expect(screen.getByPlaceholderText("已保存，留空保持不变")).toHaveValue("");
  });

  it("test_save_omits_empty_bind_password", async () => {
    resetSession("admin");
    resetLdapMock(
      makeLdapConfig({ enabled: true, server_host: "ldap.test", user_base_dn: "ou=people,dc=test", has_bind_password: true }),
    );
    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { route: "/ldap-config" });

    await screen.findByLabelText("服务器地址");
    await waitFor(() => expect(screen.getByLabelText("服务器地址")).toHaveValue("ldap.test"));
    // Bind DN 起始为空，补一个值使表单发生变化（user.clear 在 antd 受控输入上不可靠，改用追加输入）
    await user.type(screen.getByLabelText("Bind DN（可选）"), "cn=new,dc=test");
    await user.click(screen.getByRole("button", { name: "保存" }));

    expect(await screen.findByText("LDAP 配置已保存并即时生效")).toBeInTheDocument();
    const puts = getLdapRequests("PUT");
    expect(puts).toHaveLength(1);
    const body = puts[0].body as Record<string, unknown>;
    // 未输密码不发键：后端按 bind_password=None 语义保留旧密文
    expect("bind_password" in body).toBe(false);
    expect(body).toMatchObject({
      enabled: true,
      server_host: "ldap.test",
      bind_dn: "cn=new,dc=test",
      user_base_dn: "ou=people,dc=test",
    });
    // antd Form 在 jsdom 下逐键校验定时器使交互用例较慢，放宽预算，断言不变。
  }, 20000);

  it("test_save_sends_password_when_typed", async () => {
    resetSession("admin");
    resetLdapMock(makeLdapConfig({ server_host: "ldap.test", user_base_dn: "ou=people,dc=test" }));
    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { route: "/ldap-config" });

    await screen.findByLabelText("服务器地址");
    await waitFor(() => expect(screen.getByLabelText("服务器地址")).toHaveValue("ldap.test"));
    // 无密码历史时输入框没有占位提示
    expect(screen.queryByPlaceholderText("已保存，留空保持不变")).toBeNull();
    await user.type(screen.getByLabelText("Bind 密码"), "new-secret");
    await user.click(screen.getByRole("button", { name: "保存" }));

    expect(await screen.findByText("LDAP 配置已保存并即时生效")).toBeInTheDocument();
    const body = getLdapRequests("PUT")[0].body as Record<string, unknown>;
    expect(body.bind_password).toBe("new-secret");
    // antd Form 在 jsdom 下逐键校验定时器使交互用例较慢，放宽预算，断言不变。
  }, 20000);

  it("test_connection_button_posts_and_shows_stage_message", async () => {
    resetSession("admin");
    resetLdapMock(
      makeLdapConfig({ enabled: true, server_host: "ldap.test", user_base_dn: "ou=people,dc=test", has_bind_password: true }),
    );
    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { route: "/ldap-config" });

    await screen.findByLabelText("服务器地址");
    await waitFor(() => expect(screen.getByLabelText("服务器地址")).toHaveValue("ldap.test"));
    // 密码留空：本地前置拦截，仅警示不发请求（省一次注定失败的后端调用）
    await user.click(screen.getByRole("button", { name: "测试连接" }));
    expect(await screen.findByText("请填写 Bind 密码后再测试")).toBeInTheDocument();
    expect(getLdapRequests("POST")).toHaveLength(0);

    // 成功态：用当前表单值发 POST，展示后端返回的分类文案
    await user.type(screen.getByLabelText("Bind 密码"), "secret");
    setLdapTestResult(makeTestResult({ ok: true, stage: "ok", message: "连接、绑定与用户搜索均正常" }));
    await user.click(screen.getByRole("button", { name: "测试连接" }));
    expect(await screen.findByText("连接、绑定与用户搜索均正常")).toBeInTheDocument();
    const posts = getLdapRequests("POST");
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toMatchObject({ server_host: "ldap.test", bind_password: "secret" });

    // 失败态：同一按钮展示失败阶段的分类文案
    setLdapTestResult(
      makeTestResult({ ok: false, stage: "search", message: "LDAP 服务绑定失败，请检查 Bind DN 与 Bind 密码" }),
    );
    await user.click(screen.getByRole("button", { name: "测试连接" }));
    expect(await screen.findByText("LDAP 服务绑定失败，请检查 Bind DN 与 Bind 密码")).toBeInTheDocument();
    expect(getLdapRequests("POST")).toHaveLength(2);
    // antd Form 在 jsdom 下逐键校验定时器使交互用例较慢，放宽预算，断言不变。
  }, 20000);

  it("test_menu_entry_admin_only", async () => {
    // 非 admin：侧边导航不含「LDAP 认证」，其余项照常
    // （菜单项的可访问名含图标 aria-label，按子文本断言比 role+name 更稳）
    resetSession("team_admin");
    const first = renderWithProviders(<AppRoutes />, { route: "/users" });
    expect(await first.findAllByText("alice")).not.toHaveLength(0);
    const menu = screen.getByRole("menu");
    expect(within(menu).getByText("用户管理")).toBeInTheDocument();
    expect(within(menu).queryByText("LDAP 认证")).toBeNull();
    first.unmount();

    // 非 admin 直达 /ldap-config：RequireRole 送 403
    resetSession("team_admin");
    const second = renderWithProviders(<AppRoutes />, { route: "/ldap-config" });
    expect(await second.findByText("无权访问")).toBeInTheDocument();
    second.unmount();

    // admin：导航含「LDAP 认证」，可进入配置页
    resetSession("admin");
    const third = renderWithProviders(<AppRoutes />, { route: "/ldap-config" });
    const adminMenu = await third.findByRole("menu");
    expect(await within(adminMenu).findByText("LDAP 认证")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "LDAP 认证" })).toBeInTheDocument();
    expect(screen.getByLabelText("服务器地址")).toBeInTheDocument();
  });
});
