import userEvent from "@testing-library/user-event";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { UserActions } from "@/pages/users/components/UserActions";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";
import { resetHealthMock } from "@mocks/domains/health";
import { makeTenant, resetTenantsMock } from "@mocks/domains/tenants";
import {
  getUserRequests,
  makeSyncReport,
  makeUser,
  resetUsersMock,
  setUserActionError,
  setUserSyncReport,
} from "@mocks/domains/users";
import type { UserListItem } from "@/api/users";

/** 未开通行工厂：无团队归属与 OV 身份（tenant_id==null），LDAP JIT 自动建档或本地两段式创建同构。 */
function makeUnprovisionedUser(overrides: Partial<UserListItem> = {}): UserListItem {
  return makeUser({
    id: 21,
    username: "ldapguy",
    role: "user",
    auth_source: "ldap",
    tenant_id: null,
    account_id: null,
    ov_user_id: null,
    ov_role: null,
    has_key: false,
    key_state: "pending",
    key_synced_at: null,
    ...overrides,
  });
}

async function renderActions(
  actor: ReturnType<typeof makeMe>,
  user: UserListItem,
  tenants: ReturnType<typeof makeTenant>[] | null = [],
  users: UserListItem[] = [],
) {
  localStorage.setItem("ov-dashboard-token", `jwt-${actor.username}`);
  resetAuthMock(actor);
  resetHealthMock();
  resetTenantsMock(tenants);
  resetUsersMock(users);
  const view = renderWithProviders(<UserActions user={user} />);
  // 等 /me 引导完成，避免在 me=null 的禁用初态上点击
  await screen.findByTestId("user-actions");
  await waitFor(() =>
    expect(screen.getByTestId("user-actions")).toHaveAttribute("data-ready", "true"),
  );
  return view;
}

const admin = () => makeMe({ id: 1, username: "admin", role: "admin" });
const teamAdmin = () =>
  makeMe({ id: 5, username: "boss", role: "team_admin", tenant_id: 1, account_id: "acme", ov_user_id: "boss", ov_role: "admin", has_ov_key: true });

describe("UserActions", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("admin 切换角色发送 PATCH role 并刷新行", async () => {
    const user = userEvent.setup();
    await renderActions(admin(), makeUser({ id: 3, username: "alice", role: "user", ov_role: "user" }));

    // jsdom 下 antd Select 不响应 user-event 点击开合，按 T6 canonical 方式以 mouseDown 打开；
    // role 查询会命中 rc-select 的无障碍测量节点，故按类名取可见项。
    fireEvent.mouseDown(screen.getByRole("combobox"));
    await user.click(await screen.findByText("团队管理员", { selector: ".ant-select-item-option-content" }));

    await waitFor(() => {
      const patch = getUserRequests("PATCH")[0];
      expect(patch.url).toContain("/users/3/role");
      expect(patch.body).toEqual({ role: "team_admin" });
    });
  });

  it("末位团队管理员降级被 409 拒绝时给出后端文案", async () => {
    const user = userEvent.setup();
    await renderActions(admin(), makeUser({ id: 9, username: "soloboss", role: "team_admin", ov_role: "admin" }));
    // 注入必须在 renderActions 之后：resetUsersMock 会清空 actionError（brief 原稿置于其前会被重置）。
    setUserActionError("PATCH", "/role", 409, { detail: "团队最后一个团队管理员不可降级" });

    fireEvent.mouseDown(screen.getByRole("combobox"));
    await user.click(await screen.findByText("普通用户", { selector: ".ant-select-item-option-content" }));
    expect(await screen.findByText("团队最后一个团队管理员不可降级")).toBeInTheDocument();
  });

  it("重置密码可勾选联动重签并展开 seed，请求体完整", async () => {
    const user = userEvent.setup();
    await renderActions(admin(), makeUser({ id: 3 }));

    await user.click(screen.getByRole("button", { name: "重置密码" }));
    await user.type(await screen.findByLabelText("新密码"), "Alice#202611");
    await user.click(screen.getByRole("checkbox", { name: /同时作废并重新生成/ }));
    await user.click(screen.getByText("高级选项"));
    await user.type(await screen.findByLabelText("Seed（可选）"), "seed-1");
    await user.click(screen.getByRole("button", { name: "确认重置" }));

    await waitFor(() => expect(getUserRequests("POST").some((r) => r.url.includes("reset-password"))).toBe(true));
    const reset = getUserRequests("POST").find((r) => r.url.includes("reset-password"))!;
    expect(reset.body).toEqual({
      new_password: "Alice#202611",
      regenerate_key: true,
      seed: "seed-1",
    });
    // antd Form 在 jsdom 下逐键校验定时器会被 user-event 的 act 包装逐键等待，交互用例较慢，
    // 放宽预算，断言不变（同 T4/T6）。
  }, 30000);

  it("重置失败转成功后关闭弹窗，重开不残留上次的错误横幅", async () => {
    const user = userEvent.setup();
    await renderActions(admin(), makeUser({ id: 3 }));
    // 注入必须在 renderActions 之后：resetUsersMock 会清空 actionError（同上）。
    setUserActionError("POST", "reset-password", 500, { detail: "重置服务暂不可用" });

    await user.click(screen.getByRole("button", { name: "重置密码" }));
    await user.type(await screen.findByLabelText("新密码"), "Alice#202611");
    await user.click(screen.getByRole("button", { name: "确认重置" }));
    expect(await screen.findByText("重置服务暂不可用")).toBeInTheDocument();

    // 修复注入后表单原值重提成功，弹窗关闭；重开不得再渲染陈旧错误。
    resetUsersMock([]);
    await user.click(screen.getByRole("button", { name: "确认重置" }));
    expect(await screen.findByText(/已重置 alice 的登录密码/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByLabelText("新密码")).toBeNull());

    await user.click(screen.getByRole("button", { name: "重置密码" }));
    expect(await screen.findByRole("button", { name: "确认重置" })).toBeInTheDocument();
    expect(screen.queryByText("重置服务暂不可用")).toBeNull();
  }, 30000);

  it("停用需二次确认，发送 disable；启用直接发送 enable", async () => {
    const user = userEvent.setup();
    const view = await renderActions(admin(), makeUser({ id: 3, is_active: true }));

    await user.click(screen.getByRole("switch"));
    await user.click(await screen.findByRole("button", { name: "停用" }));
    await waitFor(() => expect(getUserRequests("POST").some((r) => r.url.endsWith("/disable"))).toBe(true));
    view.unmount();

    resetUsersMock([makeUser({ id: 3, is_active: false })]);
    await renderActions(admin(), makeUser({ id: 3, is_active: false }));
    await user.click(screen.getByRole("switch"));
    await waitFor(() => expect(getUserRequests("POST").some((r) => r.url.endsWith("/enable"))).toBe(true));
  }, 30000);

  it("自己的行不出现角色选择、启停开关与销户按钮", async () => {
    const me = admin();
    await renderActions(me, makeUser({ id: me.id, username: "admin", role: "admin", account_id: null }));
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByRole("button", { name: "销户" })).toBeNull();
  });

  it("team_admin 对团队管理员目标的所有控件禁用", async () => {
    await renderActions(teamAdmin(), makeUser({ id: 9, username: "soloboss", role: "team_admin", ov_role: "admin" }));
    for (const button of screen.getAllByRole("button")) {
      if (button.textContent) expect(button).toBeDisabled();
    }
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("重签密钥强提示旧 key 立即失效，成功后刷新", async () => {
    const user = userEvent.setup();
    await renderActions(admin(), makeUser({ id: 3, has_key: true, key_state: "current" }));

    await user.click(screen.getByRole("button", { name: "重签密钥" }));
    expect(
      await screen.findByText(/旧 key 立即失效，所有设备上的 ovcli 都需要重新配置/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认重签" }));

    await waitFor(() => expect(getUserRequests("POST").some((r) => r.url.includes("regenerate-key"))).toBe(true));
  });

  it("待签发行主按钮为补发密钥，走同一签发端点", async () => {
    const user = userEvent.setup();
    await renderActions(admin(), makeUser({ id: 41, username: "grace", has_key: false, key_state: "pending", is_active: false }));
    await user.click(await screen.findByRole("button", { name: "补发密钥" }));
    await user.click(await screen.findByRole("button", { name: "确认重签" }));
    await waitFor(() => {
      const posts = getUserRequests("POST").filter((r) => r.url.includes("/users/41/regenerate-key"));
      expect(posts).toHaveLength(1);
    });
  });

  it("初始管理员销户被 409 拒绝时提示且行保留", async () => {
    const user = userEvent.setup();
    await renderActions(admin(), makeUser({ id: 8, username: "boss", ov_user_id: "boss" }));
    // 注入必须在 renderActions 之后：resetUsersMock 会清空 actionError（brief 原稿置于其前会被重置）。
    setUserActionError("DELETE", "/users/", 409, { detail: "账户初始管理员不可删除" });

    await user.click(screen.getByRole("button", { name: "销户" }));
    await user.click(await screen.findByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "确认销户" }));

    expect(await screen.findByText("账户初始管理员不可删除")).toBeInTheDocument();
    expect(getUserRequests("DELETE")).toHaveLength(1);
  }, 30000);

  it("校准后弹窗展示一致性与 OV 侧存在状态", async () => {
    const user = userEvent.setup();
    await renderActions(admin(), makeUser({ id: 3 }));
    // 注入必须在 renderActions 之后：resetUsersMock 会重置 syncReport 为一致默认值（同上）。
    setUserSyncReport(
      makeSyncReport({ ov_exists: false, consistent: false, local_ov_role: "user", ov_role: null }),
    );
    await user.click(screen.getByRole("button", { name: "校准" }));

    expect(await screen.findByText("OpenViking 侧存在")).toBeInTheDocument();
    expect(screen.getByText("不一致")).toBeInTheDocument();
  });

  it("test_reset_password_hidden_for_ldap_source_row", async () => {
    await renderActions(admin(), makeUser({ id: 3, username: "alice", auth_source: "ldap" }));

    // LDAP 用户口令由目录统一管理：无重置密码入口（后端 400 兜底）
    expect(screen.queryByRole("button", { name: "重置密码" })).toBeNull();
    // 停用/角色/销户照旧不受影响
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    expect(screen.getByRole("switch")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "销户" })).toBeInTheDocument();
  });

  it("test_reset_password_visible_for_local_row", async () => {
    await renderActions(admin(), makeUser({ id: 3, username: "alice", auth_source: "local" }));

    expect(screen.getByRole("button", { name: "重置密码" })).toBeInTheDocument();
  });

  it("test_provision_action_shown_for_unprovisioned_jit_admin_only", async () => {
    const jit = makeUnprovisionedUser();

    // admin：未开通 JIT 行出现开通入口；重置密码/重签密钥/校准不适用
    const adminView = await renderActions(admin(), jit);
    expect(screen.getByRole("button", { name: "开通账号" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重置密码" })).toBeNull();
    expect(screen.queryByRole("button", { name: "重签密钥" })).toBeNull();
    adminView.unmount();

    // team_admin：开通仅平台 admin 可见（JIT 行无团队归属，team_admin 视角无此入口）
    await renderActions(teamAdmin(), jit);
    expect(screen.queryByRole("button", { name: "开通账号" })).toBeNull();
  });

  it("test_team_admin_no_provision_button_for_local_unprovisioned_row", async () => {
    // 本地两段式创建的未开通行同样泛化出开通入口后，team_admin 视角仍不得出现（锁 Review Focus #5）
    const orphan = makeUnprovisionedUser({ id: 31, username: "orphan", auth_source: "local" });
    await renderActions(teamAdmin(), orphan);
    expect(screen.queryByRole("button", { name: "开通账号" })).toBeNull();
  });

  it("test_no_provision_button_for_env_admin_row", async () => {
    // env 超管行 tenant_id 亦为 null，但不在开通语义内（判定须排除 is_env_admin）
    await renderActions(
      admin(),
      makeUser({ id: 2, username: "rootadmin", is_env_admin: true, tenant_id: null, account_id: null }),
    );
    expect(screen.queryByRole("button", { name: "开通账号" })).toBeNull();
  });

  it("test_provision_modal_submits_and_closes", async () => {
    const user = userEvent.setup();
    // JIT 行须同时进 mock store：provision 落库语义按 id patch 行，缺行会 404（对齐后端）
    const jit = makeUnprovisionedUser();
    await renderActions(admin(), jit, [makeTenant()], [jit]);
    await user.click(screen.getByRole("button", { name: "开通账号" }));

    expect(await screen.findByText("开通 LDAP 用户")).toBeInTheDocument();
    expect(screen.getByText("ldapguy")).toBeInTheDocument();

    const dialog = screen.getByRole("dialog");
    // 团队列表在弹窗打开时才拉取：先等 Select 的 loading 图标消失（数据入缓存），
    // 再同步 mouseDown+点击选中——开合与点击之间插入 await 会被 rc-motion 收起（同 UserListPage 配方）。
    await waitFor(() =>
      expect(dialog.querySelector(".ant-select-arrow .anticon-loading")).toBeNull(),
    );
    fireEvent.mouseDown(within(dialog).getByRole("combobox"));
    fireEvent.click(screen.getByText("acme", { selector: ".ant-select-item-option-content" }));
    await user.click(within(dialog).getByText("团队管理员"));
    await user.type(within(dialog).getByLabelText("OV 用户 ID"), "ldapguy-ov");
    await user.click(within(dialog).getByRole("button", { name: "开通" }));

    expect(await screen.findByText(/ldapguy 开通成功/)).toBeInTheDocument();
    const post = getUserRequests("POST")[0];
    expect(post.url).toContain("/users/21/provision");
    expect(post.body).toEqual({
      tenant_id: 1,
      role: "team_admin",
      ov_user_id: "ldapguy-ov",
    });
    // 成功后弹窗关闭
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  }, 30000);
});
