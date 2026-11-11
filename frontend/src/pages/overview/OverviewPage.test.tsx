import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";
import { resetHealthMock } from "@mocks/domains/health";
import {
  getOverviewRequests,
  makeComponent,
  makeObserver,
  makeSummary,
  resetOverviewMock,
  setOverviewError,
} from "@mocks/domains/overview";

// AppLayout 头部会渲染当前登录用户名（行内无同名文本干扰）。
function renderAt(role: "admin" | "team_admin") {
  localStorage.setItem("ov-dashboard-token", `jwt-${role}`);
  resetAuthMock(
    role === "admin"
      ? makeMe({ role: "admin" })
      : makeMe({ id: 5, username: "boss", role: "team_admin", tenant_id: 1 }),
  );
  resetHealthMock();
  return renderWithProviders(<AppRoutes />, { route: "/overview" });
}

const renderAdminAt = () => renderAt("admin");
const renderTeamAdminAt = () => renderAt("team_admin");

function requestCountOf(pathSuffix: string): number {
  return getOverviewRequests("GET").filter((r) =>
    new URL(r.url).pathname.endsWith(pathSuffix),
  ).length;
}

describe("OverviewPage", () => {
  beforeEach(() => {
    localStorage.clear();
    resetOverviewMock();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("admin 四张 KPI 卡数值正确，健康卡「已连接」且字段齐备，observer 七卡全绿", async () => {
    resetOverviewMock({
      summary: makeSummary({
        tenant_count: 7,
        users_total: 30,
        users_active: 24,
        users_disabled: 6,
        ov_health: { status: "ok", version: "v9.9.9", latency_ms: 88 },
      }),
    });
    renderAdminAt();

    expect(await screen.findByText("团队数")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("用户总数")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
    expect(screen.getByText("启用")).toBeInTheDocument();
    expect(screen.getByText("24")).toBeInTheDocument();
    expect(screen.getByText("禁用")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();

    expect(screen.getByText("已连接")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("v9.9.9")).toBeInTheDocument();
    expect(screen.getByText("88 ms")).toBeInTheDocument();

    // 七组件卡：中文名 + 原始 key，全部「正常」
    for (const label of ["队列", "模型", "检索", "系统", "VikingDB", "文件系统", "锁"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("vikingdb")).toBeInTheDocument();
    expect(screen.getAllByText("正常")).toHaveLength(7);
    expect(screen.getByText("数据每 30 秒自动刷新")).toBeInTheDocument();
    // 图标按钮的可及名含 icon 的 aria-label（"reload 刷新"），以子串匹配。
    expect(screen.getByRole("button", { name: /刷新/ })).toBeInTheDocument();
  });

  it("observer 卡点击打开 JSON 抽屉展示该组件原始 JSON", async () => {
    renderAdminAt();

    fireEvent.click(await screen.findByText("队列"));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByText("Observer · queue")).toBeInTheDocument();
    expect(within(dialog).getByText(/"component": "queue"/)).toBeInTheDocument();
  });

  it("OV 摘要卡「原始 JSON」按钮打开抽屉展示 ov_summary", async () => {
    renderAdminAt();

    fireEvent.click(await screen.findByRole("button", { name: "原始 JSON" }));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByText("OV 摘要原始 JSON")).toBeInTheDocument();
    expect(within(dialog).getByText(/"tenants": 3/)).toBeInTheDocument();
  });

  it("observer 单组件异常：红「异常」Tag + Tooltip 错误信息，其余六卡正常", async () => {
    resetOverviewMock({
      observer: makeObserver({
        lock: makeComponent("lock", { data: null, error: "锁服务超时" }),
      }),
    });
    renderAdminAt();

    expect(await screen.findByText("队列")).toBeInTheDocument();
    expect(screen.getByText("异常")).toBeInTheDocument();
    expect(screen.getAllByText("正常")).toHaveLength(6);

    fireEvent.mouseEnter(screen.getByText("异常"));
    expect(await screen.findByText("锁服务超时")).toBeInTheDocument();
  });

  it("OV 分节降级（ov_error 非空）：KPI 照常渲染，「OV 未连接」+ 错误文案，健康字段显 —，不白屏", async () => {
    resetOverviewMock({
      summary: makeSummary({
        ov_summary: null,
        ov_health: null,
        ov_error: "OpenViking 连接失败（503）",
      }),
    });
    renderAdminAt();

    expect(await screen.findByText("OV 未连接")).toBeInTheDocument();
    expect(screen.getByText("OpenViking 连接失败（503）")).toBeInTheDocument();
    // 本地 KPI 不受 OV 故障影响
    expect(screen.getByText("团队数")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    // ov_health null → 状态/版本/延迟全部占位
    expect(screen.getAllByText("—")).toHaveLength(3);
    // OV 摘要降级为不可用占位
    expect(screen.getByText("OV 摘要暂不可用")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "原始 JSON" })).toBeNull();
  });

  it("summary 端点 502：显式错误 Alert + 重试，页面壳不白屏，observer 查询独立不受影响", async () => {
    // 注入须晚于 beforeEach 的 reset（reset 会清空错误，同 CredentialsPage 先例）。
    setOverviewError(502, { detail: "OV 网关错误" });
    renderAdminAt();

    expect(await screen.findByText("OV 网关错误")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    // 侧边菜单项与页标题同名，只断言标题 role 避免多匹配（页面壳未白屏）。
    expect(screen.getByRole("heading", { name: "总览看板" })).toBeInTheDocument();
    // observer 是独立接口，照常渲染
    expect(await screen.findByText("队列")).toBeInTheDocument();
    expect(screen.getAllByText("正常")).toHaveLength(7);
  });

  it("team_admin 三卡（无团队数卡）、无 OV 摘要卡与 observer 区，且不发起 observer 请求", async () => {
    resetOverviewMock({
      summary: makeSummary({ tenant_count: null, ov_summary: undefined }),
    });
    renderTeamAdminAt();

    expect(await screen.findByText("本团队用户总数")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    expect(screen.queryByText("团队数")).toBeNull();
    expect(screen.queryByText("OV 摘要")).toBeNull();
    expect(screen.queryByText("OV Observer 组件")).toBeNull();

    // enabled: false 生效——聚合请求从未发出（权限收窄是后端职责，前端不发起是双保险）
    const urls = getOverviewRequests("GET").map((r) => r.url);
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((u) => !u.includes("/overview/observer"))).toBe(true);
  });

  it("自动刷新：30s 轮询使 summary 与 observer 各发出第二次请求", async () => {
    // 钉法说明：以 vi.useFakeTimers 真实推进 30s 验证 refetchInterval: 30000 生效
    // （比断言配置对象存在更强——直接证明两次网络请求发生）。
    vi.useFakeTimers();
    renderAdminAt();

    // 初始请求：路由门（/auth/me → 页面挂载）经两轮 tick 刷出。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(requestCountOf("/overview/summary")).toBe(1);
    expect(requestCountOf("/overview/observer")).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000);
    });
    expect(requestCountOf("/overview/summary")).toBe(2);
    expect(requestCountOf("/overview/observer")).toBe(2);
  });
});
