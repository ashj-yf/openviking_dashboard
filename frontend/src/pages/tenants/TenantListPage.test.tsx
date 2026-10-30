import userEvent from "@testing-library/user-event";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";
import { resetHealthMock } from "@mocks/domains/health";
import {
  getTenantRequests,
  makeSyncReport,
  makeTenant,
  resetTenantsMock,
  setCreateError,
  setCreatedPayload,
  setSyncReport,
} from "@mocks/domains/tenants";

function renderAdmin() {
  localStorage.setItem("ov-dashboard-token", "jwt-admin");
  resetAuthMock(makeMe({ role: "admin" }));
  resetHealthMock();
  return renderWithProviders(<AppRoutes />, { route: "/tenants" });
}

describe("TenantListPage", () => {
  beforeEach(() => {
    localStorage.clear();
    resetTenantsMock();
  });

  // 防抖用例会临时开启 fake timers；无论用例成败都复位真实时钟，避免假时钟泄漏到后续用例。
  afterEach(() => {
    vi.useRealTimers();
  });

  it("渲染团队列：ID、显示名、初始管理员、用户数与创建时间", async () => {
    resetTenantsMock([
      makeTenant({ id: 1, account_id: "acme", display_name: "Acme 团队", admin_user_id: "boss", user_count: 3, created_at: "2026-10-20T03:24:15Z" }),
      makeTenant({ id: 2, account_id: "globex", display_name: null, admin_user_id: "admin2", user_count: 0, created_at: null }),
    ]);
    renderAdmin();

    expect(await screen.findByText("acme")).toBeInTheDocument();
    expect(screen.getByText("Acme 团队")).toBeInTheDocument();
    expect(screen.getByText("boss")).toBeInTheDocument();
    expect(screen.getByText("2026-10-20 03:24")).toBeInTheDocument();
    expect(screen.getByText("globex")).toBeInTheDocument();
  });

  it("无团队时显示空态", async () => {
    resetTenantsMock([]);
    renderAdmin();
    // antd Empty 插画的 SVG <title> 与可见描述同名，限定到可见描述节点避免多匹配。
    expect(
      await screen.findByText("暂无数据", { selector: ".ant-empty-description" }),
    ).toBeInTheDocument();
  });

  it("搜索框输入后 300ms 防抖发 q 查询，不为每个字符发请求", async () => {
    // 首屏列表必须在真实时钟下 settle（fake timers 会卡住 TestingLibrary 轮询与 MSW 响应）；
    // 待初始数据出现后再切 fake timers 专测 300ms 防抖。
    renderAdmin();
    await screen.findByText("acme");

    vi.useFakeTimers();
    const input = screen.getByPlaceholderText("搜索团队 ID / 显示名 / 管理员");
    // 用 fireEvent 同步模拟连续输入（被测对象是组件的 300ms 防抖，而非 userEvent 的击键延迟，
    // 后者在 fake timers 下会挂起）。防抖窗口内两次变更只应在 300ms 后发一次查询。
    fireEvent.change(input, { target: { value: "a" } });
    fireEvent.change(input, { target: { value: "ac" } });
    await vi.advanceTimersByTimeAsync(300);
    // 不用 runAllTimersAsync：AppLayout 健康灯有 30s 轮询链，runAll 会触发 infinite-loop 中止。
    // 零推进只让出真实事件循环回合，等待防抖查询实际发出（假时钟停在 300ms，不触发健康轮询）。
    let searches = getTenantRequests("GET").filter((r) => r.url.includes("q="));
    for (let i = 0; i < 10 && searches.length === 0; i++) {
      await vi.advanceTimersByTimeAsync(0);
      searches = getTenantRequests("GET").filter((r) => r.url.includes("q="));
    }

    expect(searches).toHaveLength(1);
    expect(searches[0].url).toContain("q=ac");
    vi.useRealTimers();
  });

  it("创建 Modal 字段齐全，seed 在折叠的高级选项中", async () => {
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText("acme");
    await user.click(screen.getByRole("button", { name: "新建团队" }));

    expect(await screen.findByLabelText("团队 ID（account_id）")).toBeInTheDocument();
    expect(screen.getByLabelText("初始管理员 OV ID")).toBeInTheDocument();
    expect(screen.getByLabelText("管理员登录名")).toBeInTheDocument();
    expect(screen.getByLabelText("管理员初始密码")).toBeInTheDocument();
    expect(screen.queryByLabelText("Seed（可选）")).toBeNull();

    await user.click(screen.getByText("高级选项"));
    expect(await screen.findByLabelText("Seed（可选）")).toBeInTheDocument();
  });

  it("account_id 含非法字符时前端拦截且不发请求", async () => {
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText("acme");
    await user.click(screen.getByRole("button", { name: "新建团队" }));

    await user.type(await screen.findByLabelText("团队 ID（account_id）"), "bad id!");
    await user.click(screen.getByRole("button", { name: "创建" }));

    expect(
      await screen.findByText("仅允许字母、数字、下划线、连字符，长度 1-64"),
    ).toBeInTheDocument();
    expect(getTenantRequests("POST")).toHaveLength(0);
    // antd Form 在 jsdom 下逐键校验定时器使交互用例较慢，放宽预算，断言不变。
  }, 20000);

  it("管理员初始密码不足 8 位时前端拦截", async () => {
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText("acme");
    await user.click(screen.getByRole("button", { name: "新建团队" }));
    await user.type(await screen.findByLabelText("管理员初始密码"), "short");
    await user.click(screen.getByRole("button", { name: "创建" }));
    expect(await screen.findByText("密码长度需为 8-128 位")).toBeInTheDocument();
    // antd Form 在 jsdom 下逐键校验定时器使交互用例较慢，放宽预算，断言不变。
  }, 20000);

  it("创建成功：关闭 Modal、刷新列表并提示线下交付初始密码", async () => {
    setCreatedPayload({
      id: 20,
      account_id: "newco",
      admin_user_id: "newboss",
      team_admin_id: 21,
      team_admin_username: "newboss",
      key_provisioned: true,
    });
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText("acme");
    await user.click(screen.getByRole("button", { name: "新建团队" }));
    await user.type(await screen.findByLabelText("团队 ID（account_id）"), "newco");
    await user.type(screen.getByLabelText("初始管理员 OV ID"), "newboss");
    await user.type(screen.getByLabelText("管理员登录名"), "newboss");
    await user.type(screen.getByLabelText("管理员初始密码"), "Newboss#2026");
    await user.click(screen.getByRole("button", { name: "创建" }));

    expect(await screen.findByText(/团队 newco 创建成功/)).toBeInTheDocument();
    expect(screen.getByText(/请通过安全渠道交付初始密码/)).toBeInTheDocument();
    const post = getTenantRequests("POST")[0];
    expect(post.body).toMatchObject({
      account_id: "newco",
      admin_user_id: "newboss",
      admin_username: "newboss",
      admin_password: "Newboss#2026",
    });
    await waitFor(() => expect(screen.queryByLabelText("团队 ID（account_id）")).toBeNull());
    // antd Form 在 jsdom 下逐键填四字段 + 提交往返较慢，放宽预算，断言不变。
  }, 30000);

  it("创建响应 key_provisioned=false 时提示团队管理员去凭证页重签", async () => {
    setCreatedPayload({
      id: 3,
      account_id: "newco",
      admin_user_id: "newboss",
      team_admin_id: 12,
      team_admin_username: "newboss",
      key_provisioned: false,
    });
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText("acme");
    await user.click(screen.getByRole("button", { name: "新建团队" }));
    await user.type(await screen.findByLabelText("团队 ID（account_id）"), "newco");
    await user.type(screen.getByLabelText("初始管理员 OV ID"), "newboss");
    await user.type(screen.getByLabelText("管理员登录名"), "newboss");
    await user.type(screen.getByLabelText("管理员初始密码"), "Newboss#2026");
    await user.click(screen.getByRole("button", { name: "创建" }));

    expect(
      await screen.findByText(/初始团队管理员的 user key 未随创建返回，可在「我的凭证」自助重签/),
    ).toBeInTheDocument();
    // antd Form 在 jsdom 下逐键填四字段 + 提交往返较慢，放宽预算，断言不变。
  }, 30000);

  it("409 冲突时显示后端文案且 Modal 不关闭", async () => {
    setCreateError(409, { detail: "account_id 已存在" });
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText("acme");
    await user.click(screen.getByRole("button", { name: "新建团队" }));
    await user.type(await screen.findByLabelText("团队 ID（account_id）"), "acme");
    await user.type(screen.getByLabelText("初始管理员 OV ID"), "boss");
    await user.type(screen.getByLabelText("管理员登录名"), "boss");
    await user.type(screen.getByLabelText("管理员初始密码"), "Boss#202600");
    await user.click(screen.getByRole("button", { name: "创建" }));

    expect(await screen.findByText("account_id 已存在")).toBeInTheDocument();
    expect(screen.getByLabelText("团队 ID（account_id）")).toBeInTheDocument();
    // antd Form 在 jsdom 下逐键填四字段 + 提交往返较慢，放宽预算，断言不变。
  }, 30000);

  it("422 字段错误挂到对应表单项", async () => {
    setCreateError(422, {
      detail: [{ loc: ["body", "admin_password"], msg: "密码长度需为 8-128 位", type: "value_error" }],
    });
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText("acme");
    await user.click(screen.getByRole("button", { name: "新建团队" }));
    await user.type(await screen.findByLabelText("团队 ID（account_id）"), "acme");
    await user.type(screen.getByLabelText("初始管理员 OV ID"), "boss");
    await user.type(screen.getByLabelText("管理员登录名"), "boss");
    await user.type(screen.getByLabelText("管理员初始密码"), "12345678");
    await user.click(screen.getByRole("button", { name: "创建" }));

    expect(await screen.findAllByText("密码长度需为 8-128 位")).not.toHaveLength(0);
    // antd Form 在 jsdom 下逐键填四字段 + 提交往返较慢，放宽预算，断言不变。
  }, 30000);

  it("删除二次确认：警示不可恢复、勾选后才允许确认，发送 {confirm:true}", async () => {
    resetTenantsMock([makeTenant({ id: 7, account_id: "doomed" })]);
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText("doomed");

    const row = screen.getByText("doomed").closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "删除" }));

    expect(
      await screen.findByText(/该团队在 OpenViking 的账户及其全部用户、数据将不可恢复/),
    ).toBeInTheDocument();
    const confirmButton = screen.getByRole("button", { name: "确认删除" });
    expect(confirmButton).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(confirmButton);

    await waitFor(() =>
      expect(getTenantRequests("DELETE").some((r) => r.url.endsWith("/api/v1/tenants/7"))).toBe(true),
    );
    expect(getTenantRequests("DELETE")[0].body).toEqual({ confirm: true });
  });

  it("同步后弹窗展示计数与差异用户", async () => {
    setSyncReport(
      makeSyncReport({
        ov_user_count: 5,
        local_user_count: 3,
        matched: 3,
        missing_local: [
          { ov_user_id: "carol", ov_role: "user", username: null },
          { ov_user_id: "dave", ov_role: "admin", username: null },
        ],
      }),
    );
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText("acme");
    await user.click(screen.getByRole("button", { name: "同步" }));

    expect(await screen.findByText("OpenViking 用户数")).toBeInTheDocument();
    expect(screen.getByText("carol")).toBeInTheDocument();
    expect(screen.getByText("dave")).toBeInTheDocument();
  });
});
