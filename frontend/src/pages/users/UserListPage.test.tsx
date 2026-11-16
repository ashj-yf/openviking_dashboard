import userEvent from "@testing-library/user-event";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { server } from "@mocks/server";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";
import { resetHealthMock } from "@mocks/domains/health";
import { resetTenantsMock } from "@mocks/domains/tenants";
import {
  getUserRequests,
  makeUser,
  resetUsersMock,
  setListError,
  setProvisionError,
} from "@mocks/domains/users";

function renderAs(
  role: "admin" | "team_admin",
  route = "/users",
  meOverrides: Partial<ReturnType<typeof makeMe>> = {},
) {
  localStorage.setItem("ov-dashboard-token", role === "admin" ? "jwt-admin" : "jwt-boss");
  resetAuthMock(
    role === "admin"
      ? makeMe({ role: "admin", ...meOverrides })
      : makeMe({
          id: 5,
          username: "boss",
          role: "team_admin",
          tenant_id: 1,
          account_id: "acme",
          ov_user_id: "boss",
          ov_role: "admin",
          has_ov_key: true,
          ...meOverrides,
        }),
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
    // T7 操作列为行内加了角色 Select（选中值同样显示"普通用户"），按 td 收窄到 OV 角色列。
    expect(screen.getByText("普通用户", { selector: "td" })).toBeInTheDocument();
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
    // T7 操作列为每行加了角色 Select，页面出现多个 combobox；DOM 顺序上 Card extra 的团队筛选在前。
    fireEvent.mouseDown(screen.getAllByRole("combobox")[0]);
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

  it("列表查询失败时展示后端错误原文并可重试，重试成功后恢复列表", async () => {
    const user = userEvent.setup();
    // 注入须晚于 mock reset：beforeEach 的 resetUsersMock 会清空 listError（同 CredentialsPage 先例）。
    setListError(500, { detail: "数据库暂时不可用" });
    renderAs("admin");

    expect(await screen.findByText("数据库暂时不可用")).toBeInTheDocument();
    expect(screen.queryByText("alice")).toBeNull();

    resetUsersMock([makeUser({ username: "alice" })]);
    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findAllByText("alice")).not.toHaveLength(0);
    expect(screen.queryByText("数据库暂时不可用")).toBeNull();
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

    // 未选团队：角色锁普通用户，OV 专属字段（含 seed）隐藏；先选定团队解锁。
    // 弹窗内 Select 的同步选中配方同「开通成功」用例：mouseDown 后不插入 await 直接点击。
    await screen.findByLabelText("登录用户名");
    const dialog = screen.getByRole("dialog");
    await waitFor(() =>
      expect(dialog.querySelector(".ant-select-arrow .anticon-loading")).toBeNull(),
    );
    fireEvent.mouseDown(within(dialog).getByRole("combobox"));
    fireEvent.click(screen.getByText("acme", { selector: ".ant-select-item-option-content" }));

    expect(await screen.findByRole("radio", { name: "普通用户" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "团队管理员" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Seed（可选）")).toBeNull();
    await user.click(screen.getByText("高级选项"));
    expect(await screen.findByLabelText("Seed（可选）")).toBeInTheDocument();
    // 选团队+折叠展开的交互链在 jsdom 下较慢，放宽预算（同「开通成功」用例）。
  }, 30000);

  it("OV 用户 ID 默认跟随登录名", async () => {
    const user = userEvent.setup();
    renderAs("admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));

    // OV 字段在未选团队时隐藏：先选定团队（同步选中配方同「开通成功」用例）
    await screen.findByLabelText("登录用户名");
    const dialog = screen.getByRole("dialog");
    await waitFor(() =>
      expect(dialog.querySelector(".ant-select-arrow .anticon-loading")).toBeNull(),
    );
    fireEvent.mouseDown(within(dialog).getByRole("combobox"));
    fireEvent.click(screen.getByText("acme", { selector: ".ant-select-item-option-content" }));

    await user.type(screen.getByLabelText("登录用户名"), "carol");
    expect((screen.getByLabelText("OV 用户 ID") as HTMLInputElement).value).toBe("carol");
    // 选团队的交互前缀在 jsdom 下较慢，放宽预算（同「开通成功」用例）。
  }, 30000);

  it("手动修改过 OV 用户 ID 后不再被登录名覆盖", async () => {
    const user = userEvent.setup();
    renderAs("admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));

    // OV 字段在未选团队时隐藏：先选定团队（同步选中配方同「开通成功」用例）
    await screen.findByLabelText("登录用户名");
    const dialog = screen.getByRole("dialog");
    await waitFor(() =>
      expect(dialog.querySelector(".ant-select-arrow .anticon-loading")).toBeNull(),
    );
    fireEvent.mouseDown(within(dialog).getByRole("combobox"));
    fireEvent.click(screen.getByText("acme", { selector: ".ant-select-item-option-content" }));

    await user.type(screen.getByLabelText("登录用户名"), "carol");
    const ovInput = screen.getByLabelText("OV 用户 ID");
    await user.clear(ovInput);
    await user.type(ovInput, "carol-dev");
    await user.type(screen.getByLabelText("登录用户名"), "x");
    expect((ovInput as HTMLInputElement).value).toBe("carol-dev");
    // 选团队的交互前缀在 jsdom 下较慢，放宽预算（同「开通成功」用例）。
  }, 30000);

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

  it("不选团队提交时角色强制普通用户且不发送 tenant_id", async () => {
    const user = userEvent.setup();
    renderAs("admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));

    await user.type(await screen.findByLabelText("登录用户名"), "orphan");
    await user.type(screen.getByLabelText("初始密码"), "Orphan#2026");
    // 无团队：角色组整体禁用且强制选中普通用户，OV 专属字段隐藏
    expect(screen.getByRole("radio", { name: "普通用户" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "团队管理员" })).toBeDisabled();
    expect(screen.queryByLabelText("OV 用户 ID")).toBeNull();
    await user.click(screen.getByRole("button", { name: "开通" }));

    await waitFor(() => expect(getUserRequests("POST")).toHaveLength(1));
    const body = getUserRequests("POST")[0].body as Record<string, unknown>;
    expect(body.role).toBe("user");
    expect("tenant_id" in body).toBe(false);
    // antd Form 在 jsdom 下逐键校验定时器会被 user-event 的 act 包装逐键等待，交互用例较慢，
    // 放宽预算，断言不变（同 T4）。
  }, 30000);

  it("无团队创建成功文案含未开通提示", async () => {
    // 两段式创建：POST /users 不带 tenant_id → 201 未开通账号（tenant_id=null，覆盖默认 mock）
    server.use(
      http.post("*/api/v1/users", async ({ request }) => {
        const body = (await request.json()) as { username: string };
        return HttpResponse.json(
          makeUser({
            id: 78,
            username: body.username,
            tenant_id: null,
            account_id: null,
            ov_user_id: null,
            ov_role: null,
            has_key: false,
            key_state: "pending",
          }),
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderAs("admin");
    await screen.findAllByText("alice");
    await user.click(screen.getByRole("button", { name: "开通用户" }));

    await user.type(await screen.findByLabelText("登录用户名"), "orphan");
    await user.type(screen.getByLabelText("初始密码"), "Orphan#2026");
    await user.click(screen.getByRole("button", { name: "开通" }));

    expect(await screen.findByText(/orphan 已创建（未开通）/)).toBeInTheDocument();
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

  it("test_create_button_hidden_when_ldap_enabled", async () => {
    // LDAP 模式下创建入口整体隐藏：本地创建与 LDAP 单源互斥（admin 与 team_admin 都看不到）
    const { unmount } = renderAs("admin", "/users", { ldap_enabled: true });
    await screen.findAllByText("alice");
    expect(screen.queryByRole("button", { name: "开通用户" })).toBeNull();
    unmount();

    renderAs("team_admin", "/users", { ldap_enabled: true });
    await screen.findAllByText("alice");
    expect(screen.queryByRole("button", { name: "开通用户" })).toBeNull();
  });

  it("test_create_button_visible_local_mode", async () => {
    const { unmount } = renderAs("admin");
    await screen.findAllByText("alice");
    expect(screen.getByRole("button", { name: "开通用户" })).toBeInTheDocument();
    unmount();

    renderAs("team_admin");
    await screen.findAllByText("alice");
    expect(screen.getByRole("button", { name: "开通用户" })).toBeInTheDocument();
  });

  it("未开通 JIT 行以 Tag 标识且不显示启用/停用", async () => {
    resetUsersMock([
      makeUser({
        username: "jitguy",
        auth_source: "ldap",
        tenant_id: null,
        account_id: null,
        ov_user_id: null,
        ov_role: null,
        has_key: false,
        key_state: "pending",
        is_active: true,
      }),
    ]);
    const { unmount } = renderAs("admin");

    expect(await screen.findByText("jitguy")).toBeInTheDocument();
    expect(screen.getByText("未开通")).toBeInTheDocument();
    expect(screen.queryByText("启用")).toBeNull();
    expect(screen.queryByText("停用")).toBeNull();
    unmount();

    // 已开通行不受影响（回归：本地行仍显示启用）
    resetUsersMock([makeUser({ username: "alice", is_active: true })]);
    renderAs("admin");
    expect(await screen.findAllByText("alice")).not.toHaveLength(0);
    expect(screen.getByText("启用")).toBeInTheDocument();
    expect(screen.queryByText("未开通")).toBeNull();
  });

  it("本地未开通行显示未开通标签与开通按钮", async () => {
    // 两段式创建的未开通行：auth_source=local 且无团队归属，与 LDAP JIT 同构
    resetUsersMock([
      makeUser({
        username: "orphan",
        auth_source: "local",
        tenant_id: null,
        account_id: null,
        ov_user_id: null,
        ov_role: null,
        has_key: false,
        key_state: "pending",
        is_active: true,
      }),
    ]);
    renderAs("admin");

    expect(await screen.findByText("orphan")).toBeInTheDocument();
    expect(screen.getByText("未开通")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开通账号" })).toBeInTheDocument();
  });

  it("env 超管行虽无团队但不标未开通且无开通按钮", async () => {
    resetUsersMock([
      makeUser({
        username: "rootadmin",
        is_env_admin: true,
        tenant_id: null,
        account_id: null,
        is_active: true,
      }),
    ]);
    renderAs("admin");

    expect(await screen.findByText("rootadmin")).toBeInTheDocument();
    expect(screen.getByText("启用")).toBeInTheDocument();
    expect(screen.queryByText("未开通")).toBeNull();
    expect(screen.queryByRole("button", { name: "开通账号" })).toBeNull();
  });
});
