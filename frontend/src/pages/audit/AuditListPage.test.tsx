import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";
import { resetHealthMock } from "@mocks/domains/health";
import {
  getAuditRequests,
  makeAuditLog,
  resetAuditMock,
  setAuditError,
  setOvAuditError,
  setOvAuditPayload,
} from "@mocks/domains/audit";
import type { AuditLog } from "@/api/audit";

// AppLayout 头部会渲染当前登录用户名（默认 admin），行内操作人避免同名造成多匹配。
function renderAt(role: "admin" | "team_admin") {
  localStorage.setItem("ov-dashboard-token", `jwt-${role}`);
  resetAuthMock(
    role === "admin"
      ? makeMe({ role: "admin" })
      : makeMe({ id: 5, username: "boss", role: "team_admin", tenant_id: 1 }),
  );
  resetHealthMock();
  return renderWithProviders(<AppRoutes />, { route: "/audit-logs" });
}

const renderAdmin = () => renderAt("admin");
const renderTeamAdmin = () => renderAt("team_admin");

function pagedRows(count: number): AuditLog[] {
  return Array.from({ length: count }, (_, index) =>
    makeAuditLog({
      id: index + 1,
      actor_name: `user${index + 1}`,
      action: "auth.logout",
      target_type: null,
      target_id: null,
      detail: null,
      ip: null,
      created_at: "2026-11-01T00:00:00Z",
    }),
  );
}

describe("AuditListPage", () => {
  beforeEach(() => {
    localStorage.clear();
    resetAuditMock();
  });

  it("admin 渲染审计行：操作人、动作、UTC 时间与目标拼接，空目标显示 —", async () => {
    resetAuditMock([
      makeAuditLog({
        id: 1,
        actor_name: "root",
        action: "tenant.create",
        target_type: "tenant",
        target_id: "acme",
        ip: "10.0.0.8",
        created_at: "2026-11-01T08:30:00Z",
        detail: { account_id: "acme" },
      }),
      makeAuditLog({
        id: 2,
        actor_name: "boss",
        action: "user.disable",
        target_type: null,
        target_id: null,
        ip: "192.168.1.2",
        created_at: "2026-11-02T09:00:00Z",
        detail: null,
      }),
    ]);
    renderAdmin();

    expect(await screen.findByText("tenant.create")).toBeInTheDocument();
    expect(screen.getByText("root")).toBeInTheDocument();
    expect(screen.getByText("2026-11-01 08:30")).toBeInTheDocument();
    expect(screen.getByText("tenant:acme")).toBeInTheDocument();
    expect(screen.getByText("boss")).toBeInTheDocument();
    expect(screen.getByText("user.disable")).toBeInTheDocument();
    expect(screen.getByText("2026-11-02 09:00")).toBeInTheDocument();
    // 第二行 target 为空 → 目标列显示占位符（其 IP 存在，避免多个 — 竞争）。
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("详情抽屉展示基础字段与 detail JSON；detail 为 null 时显示无详情占位", async () => {
    resetAuditMock([
      makeAuditLog({ id: 1, actor_name: "root", action: "tenant.create", detail: { account_id: "acme", count: 3 } }),
      makeAuditLog({ id: 2, actor_name: "boss", action: "user.disable", target_type: null, detail: null }),
    ]);
    renderAdmin();

    const detailButtons = await screen.findAllByRole("button", { name: "详情" });
    fireEvent.click(detailButtons[0]);

    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByText(/"account_id": "acme"/)).toBeInTheDocument();
    expect(within(dialog).getByText("操作人")).toBeInTheDocument();
    expect(within(dialog).getByText("tenant.create")).toBeInTheDocument();

    // 不关抽屉直接查看第二行：抽屉内容切换为该记录，detail 为 null → 无详情占位。
    fireEvent.click(detailButtons[1]);
    expect(await within(dialog).findByText("无详情")).toBeInTheDocument();
    expect(within(dialog).getByText("user.disable")).toBeInTheDocument();
  });

  it("选择动作域并输入操作人后查询：请求携带 action/actor 且回到第 1 页", async () => {
    renderAdmin();
    await screen.findByText("tenant.create");

    // jsdom 下 antd Select 不响应 user-event 点击开合，按 canonical 方式以 mouseDown 打开；
    // 选项文本在 content 子节点上，按类名取可见项（分页 sizeChanger combobox 在 DOM 后方，取 [0]）。
    // jsdom 下 antd Select 不响应 user-event 点击开合，且开合与点击之间插入 await 会被
    // rc-motion 收起（UserActions/UserListPage canonical）：mouseDown 后同步取可见项 fireEvent 点击。
    fireEvent.mouseDown(screen.getAllByRole("combobox")[0]);
    fireEvent.click(screen.getByText("tenant.", { selector: ".ant-select-item-option-content" }));
    fireEvent.change(screen.getByPlaceholderText("操作人"), { target: { value: "boss" } });
    fireEvent.click(screen.getByRole("button", { name: "查询" }));

    await waitFor(() => {
      const last = getAuditRequests("GET").at(-1);
      expect(last).toBeDefined();
      const search = new URL(last!.url).searchParams;
      expect(search.get("action")).toBe("tenant.");
      expect(search.get("actor")).toBe("boss");
      expect(search.get("page")).toBe("1");
      expect(search.get("page_size")).toBe("20");
    });
    // 默认夹具 tenant.* 中隔行为 boss，过滤后 auth 域行不再出现。
    expect(screen.queryByText("auth.login.success")).toBeNull();
  });

  it("受控分页：切到第 2 页请求携带 page=2 并渲染第二页数据", async () => {
    resetAuditMock(pagedRows(25));
    renderAdmin();

    expect(await screen.findByText("user1")).toBeInTheDocument();
    const first = getAuditRequests("GET")[0];
    expect(new URL(first.url).searchParams.get("page")).toBe("1");
    expect(new URL(first.url).searchParams.get("page_size")).toBe("20");

    fireEvent.click(screen.getByTitle("2"));

    expect(await screen.findByText("user21")).toBeInTheDocument();
    expect(screen.queryByText("user1")).toBeNull();
    const last = getAuditRequests("GET").at(-1)!;
    expect(new URL(last.url).searchParams.get("page")).toBe("2");
  });

  it("team_admin 可见本地列表但没有 OV 审计 Tab", async () => {
    renderTeamAdmin();

    expect(await screen.findByText("tenant.create")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "本平台审计" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "OV 审计" })).toBeNull();
  });

  it("admin 可见 OV 审计 Tab：展示原始 JSON 并可查看完整 JSON", async () => {
    renderAdmin();
    await screen.findByText("tenant.create");

    setOvAuditPayload({ total: 1, items: [{ ts: "2026-11-01T00:00:00Z", actor: "ovadmin", action: "vm.create" }] });
    fireEvent.click(screen.getByRole("tab", { name: "OV 审计" }));

    expect(await screen.findByText(/"actor": "ovadmin"/)).toBeInTheDocument();
    expect(screen.getByText("OV 侧审计原始数据，字段随真机抓包固化")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "查看完整 JSON" }));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByText("OV 审计原始 JSON")).toBeInTheDocument();
    expect(within(dialog).getByText(/"action": "vm.create"/)).toBeInTheDocument();
  });

  it("OV 透传失败时展示错误原文并提供重试", async () => {
    renderAdmin();
    await screen.findByText("tenant.create");

    setOvAuditError(500, { detail: "OV 审计暂不可用" });
    fireEvent.click(screen.getByRole("tab", { name: "OV 审计" }));

    expect(await screen.findByText("OV 审计暂不可用")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });

  it("本地列表查询失败时页面内 Alert 展示错误原文，而非空表假成功", async () => {
    // 注入须晚于 mock reset：beforeEach 的 resetAuditMock 会清空错误（同 CredentialsPage 先例）。
    setAuditError(500, { detail: "boom" });
    renderAdmin();

    expect(await screen.findByText("boom")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(screen.queryByText("tenant.create")).toBeNull();
  });
});
