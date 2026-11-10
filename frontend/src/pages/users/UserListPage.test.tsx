import userEvent from "@testing-library/user-event";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";
import { resetHealthMock } from "@mocks/domains/health";
import { resetTenantsMock } from "@mocks/domains/tenants";
import { getUserRequests, makeUser, resetUsersMock, setProvisionError } from "@mocks/domains/users";

function renderAs(role: "admin" | "team_admin", route = "/users") {
  localStorage.setItem("ov-dashboard-token", role === "admin" ? "jwt-admin" : "jwt-boss");
  resetAuthMock(
    role === "admin"
      ? makeMe({ role: "admin" })
      : makeMe({ id: 5, username: "boss", role: "team_admin", tenant_id: 1, account_id: "acme", ov_user_id: "boss", ov_role: "admin", has_ov_key: true }),
  );
  resetHealthMock();
  resetTenantsMock();
  return renderWithProviders(<AppRoutes />, { route });
}

describe("UserListPage", () => {
  beforeEach(() => {
    localStorage.clear();
    resetUsersMock();
  });

  it("渲染用户名、OV 角色、密钥托管状态、账号状态与最近登录", async () => {
    resetUsersMock([
      makeUser({ username: "alice", ov_role: "user", is_active: true, last_login_at: "2026-10-28T10:00:00Z" }),
    ]);
    renderAs("admin");

    expect(await screen.findAllByText("alice")).not.toHaveLength(0);
    expect(screen.getByText("普通用户")).toBeInTheDocument();
    expect(screen.getByText("已托管")).toBeInTheDocument();
    expect(screen.getByText("启用")).toBeInTheDocument();
    expect(screen.getByText("2026-10-28 10:00")).toBeInTheDocument();
  });

  it("admin 可见团队列；team_admin 视角不显示团队列", async () => {
    resetUsersMock([makeUser({ account_id: "acme" })]);
    const { unmount } = renderAs("admin");
    expect(await screen.findAllByText("alice")).not.toHaveLength(0);
    expect(screen.getByRole("columnheader", { name: "团队" })).toBeInTheDocument();
    unmount();

    resetUsersMock([makeUser({ account_id: "acme" })]);
    renderAs("team_admin");
    expect(await screen.findAllByText("alice")).not.toHaveLength(0);
    expect(screen.queryByRole("columnheader", { name: "团队" })).toBeNull();
  });

  it("按团队与关键字筛选，请求携带 tenant_id 与 keyword", async () => {
    // 全程真实时钟：fake timers 会卡住 TestingLibrary 轮询与 userEvent（同 T4 防抖用例教训），
    // 且 runAllTimersAsync 会沿 AppLayout 健康灯 30s 轮询链触发 infinite-loop 中止。
    // 本用例断言请求参数而非防抖节律（后者由 T4 团队列表用例覆盖）。
    const user = userEvent.setup();
    renderAs("admin");
    await screen.findAllByText("alice");

    // jsdom 下 antd Select 不响应 user-event 点击开合，按 canonical 方式以 mouseDown 打开；
    // 选项文本在 content 子节点上，role 查询会命中 rc-select 的无障碍测量节点，故按类名取可见项。
    fireEvent.mouseDown(screen.getByRole("combobox"));
    await user.click(await screen.findByText("acme", { selector: ".ant-select-item-option-content" }));
    // 选定团队 → URL 携带 tenant_id → 触发携带该参数的重新查询
    await waitFor(() => expect(getUserRequests("GET").at(-1)?.url).toContain("tenant_id=1"));

    await user.type(screen.getByPlaceholderText("搜索登录名 / OV 用户 ID"), "alice");
    // 300ms 防抖后发携带 keyword 的查询
    await waitFor(() => expect(getUserRequests("GET").at(-1)?.url).toContain("keyword=alice"));

    const gets = getUserRequests("GET");
    expect(gets.at(-1)?.url).toContain("tenant_id=1");
    expect(gets.at(-1)?.url).toContain("keyword=alice");
  });

  it("从团队详情跳入时按 URL tenant_id 预置筛选", async () => {
    renderAs("admin", "/users?tenant_id=1");
    await screen.findAllByText("alice");
    const gets = getUserRequests("GET");
    expect(gets[0].url).toContain("tenant_id=1");
  });

  it("待签发用户显示待签发标记且无已托管", async () => {
    resetUsersMock([makeUser({ has_key: false, key_state: "pending", is_active: false })]);
    renderAs("admin");
    expect(await screen.findByText("待签发")).toBeInTheDocument();
    expect(screen.queryByText("已托管")).toBeNull();
  });

  it("team_admin 开通模态锁定团队与角色：无选择器、显示团队名", async () => {
    const user = userEvent.setup();
    renderAs("team_admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));

    expect(await screen.findByText("归属团队")).toBeInTheDocument();
    expect(screen.getByText("acme")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "普通用户" })).toBeNull();
    expect(screen.queryByRole("radio", { name: "团队管理员" })).toBeNull();
  });

  it("admin 开通模态含团队选择与角色单选，seed 在高级折叠中", async () => {
    const user = userEvent.setup();
    renderAs("admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));

    expect(await screen.findByRole("radio", { name: "普通用户" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "团队管理员" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Seed（可选）")).toBeNull();
    await user.click(screen.getByText("高级选项"));
    expect(await screen.findByLabelText("Seed（可选）")).toBeInTheDocument();
  });

  it("OV 用户 ID 默认跟随登录名", async () => {
    const user = userEvent.setup();
    renderAs("admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));

    await user.type(await screen.findByLabelText("登录用户名"), "carol");
    expect((screen.getByLabelText("OV 用户 ID") as HTMLInputElement).value).toBe("carol");
  });

  it("手动修改过 OV 用户 ID 后不再被登录名覆盖", async () => {
    const user = userEvent.setup();
    renderAs("admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));

    await user.type(await screen.findByLabelText("登录用户名"), "carol");
    const ovInput = screen.getByLabelText("OV 用户 ID");
    await user.clear(ovInput);
    await user.type(ovInput, "carol-dev");
    await user.type(screen.getByLabelText("登录用户名"), "x");
    expect((ovInput as HTMLInputElement).value).toBe("carol-dev");
  });

  it("开通成功：发送完整 body、提示线下交付流程、列表出现新用户", async () => {
    const user = userEvent.setup();
    renderAs("admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));

    await user.type(await screen.findByLabelText("登录用户名"), "dave");
    await user.type(screen.getByLabelText("初始密码"), "Dave#202600");
    // 弹窗与页面各有一个 combobox，按 dialog 范围取弹窗内的。弹窗内的 antd Select 在 jsdom
    // 下 mouseDown 开合后随即被 rc-motion/焦点链收起，且异步轮询选项会与关闭竞态挂起，
    // 故 mouseDown 后同步取可见项并 fireEvent 点击，选中前不插入任何 await。
    const dialog = screen.getByRole("dialog");
    fireEvent.mouseDown(within(dialog).getByRole("combobox"));
    fireEvent.click(screen.getByText("acme", { selector: ".ant-select-item-option-content" }));
    await user.click(screen.getByRole("button", { name: "开通" }));

    expect(await screen.findByText(/用户 dave 开通成功/)).toBeInTheDocument();
    expect(screen.getByText(/首次登录将被要求修改密码/)).toBeInTheDocument();
    const post = getUserRequests("POST")[0];
    expect(post.body).toMatchObject({
      username: "dave",
      password: "Dave#202600",
      tenant_id: 1,
      ov_user_id: "dave",
      role: "user",
    });
    await waitFor(() => expect(screen.queryByLabelText("登录用户名")).toBeNull());
    expect(await screen.findAllByText("dave")).not.toHaveLength(0);
    // antd Form 在 jsdom 下逐键校验定时器会被 user-event 的 act 包装逐键等待，交互用例较慢，
    // 放宽预算，断言不变（同 T4）。
  }, 30000);

  it("team_admin 提交时不发送 tenant_id 与 role（后端按身份强制）", async () => {
    const user = userEvent.setup();
    renderAs("team_admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));
    await user.type(await screen.findByLabelText("登录用户名"), "frank");
    await user.type(screen.getByLabelText("初始密码"), "Frank#202600");
    await user.click(screen.getByRole("button", { name: "开通" }));

    await waitFor(() => expect(getUserRequests("POST")).toHaveLength(1));
    const body = getUserRequests("POST")[0].body as Record<string, unknown>;
    expect(body.tenant_id).toBeUndefined();
    expect(body.role).toBeUndefined();
    expect(body).toMatchObject({ username: "frank" });
    // antd Form 在 jsdom 下逐键校验定时器会被 user-event 的 act 包装逐键等待，交互用例较慢，
    // 放宽预算，断言不变（同 T4）。
  }, 30000);

  it("签发失败 502：提示半成品待补发、关闭模态并在列表显示待签发行", async () => {
    setProvisionError(502, {
      detail: { message: "OpenViking 用户已创建但密钥签发失败，请稍后重试签发", user_id: 88 },
    });
    const user = userEvent.setup();
    renderAs("admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));
    await user.type(await screen.findByLabelText("登录用户名"), "grace");
    await user.type(screen.getByLabelText("初始密码"), "Grace#202600");
    // 弹窗与页面各有一个 combobox，按 dialog 范围取弹窗内的。弹窗内的 antd Select 在 jsdom
    // 下 mouseDown 开合后随即被 rc-motion/焦点链收起，且异步轮询选项会与关闭竞态挂起，
    // 故 mouseDown 后同步取可见项并 fireEvent 点击，选中前不插入任何 await。
    const dialog = screen.getByRole("dialog");
    fireEvent.mouseDown(within(dialog).getByRole("combobox"));
    fireEvent.click(screen.getByText("acme", { selector: ".ant-select-item-option-content" }));
    await user.click(screen.getByRole("button", { name: "开通" }));

    expect(
      await screen.findByText("OpenViking 用户已创建但密钥签发失败，请稍后重试签发"),
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByLabelText("登录用户名")).toBeNull());
    expect(await screen.findByText("待签发")).toBeInTheDocument();
    // antd Form 在 jsdom 下逐键校验定时器会被 user-event 的 act 包装逐键等待，交互用例较慢，
    // 放宽预算，断言不变（同 T4）。
  }, 30000);

  it("409 用户名冲突显示后端文案且模态不关闭", async () => {
    setProvisionError(409, { detail: "用户名已存在" });
    const user = userEvent.setup();
    renderAs("admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));
    await user.type(await screen.findByLabelText("登录用户名"), "alice");
    await user.type(screen.getByLabelText("初始密码"), "Alice#202600");
    // admin 表单的归属团队为必填，不选定会被前端校验拦下而到不了 409；
    // 弹窗内 Select 的同步选中配方同测试 10。
    const dialog = screen.getByRole("dialog");
    fireEvent.mouseDown(within(dialog).getByRole("combobox"));
    fireEvent.click(screen.getByText("acme", { selector: ".ant-select-item-option-content" }));
    await user.click(screen.getByRole("button", { name: "开通" }));
    expect(await screen.findByText("用户名已存在")).toBeInTheDocument();
    expect(screen.getByLabelText("登录用户名")).toBeInTheDocument();
    // antd Form 在 jsdom 下逐键校验定时器会被 user-event 的 act 包装逐键等待，交互用例较慢，
    // 放宽预算，断言不变（同 T4）。
  }, 30000);

  it("403 越权以消息提示且不假装成功", async () => {
    setProvisionError(403, { detail: "只能管理本团队成员" });
    const user = userEvent.setup();
    renderAs("team_admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));
    await user.type(await screen.findByLabelText("登录用户名"), "outsider");
    await user.type(screen.getByLabelText("初始密码"), "Outsider#2026");
    await user.click(screen.getByRole("button", { name: "开通" }));
    expect(await screen.findByText("只能管理本团队成员")).toBeInTheDocument();
    // antd Form 在 jsdom 下逐键校验定时器会被 user-event 的 act 包装逐键等待，交互用例较慢，
    // 放宽预算，断言不变（同 T4）。
  }, 30000);
});
