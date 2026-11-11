import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";
import { resetHealthMock } from "@mocks/domains/health";
import {
  getTenantRequests,
  makeTenant,
  makeTenantDetail,
  resetTenantsMock,
  setTenantDetail,
} from "@mocks/domains/tenants";

function renderAdminAt(route: string) {
  localStorage.setItem("ov-dashboard-token", "jwt-admin");
  resetAuthMock(makeMe({ role: "admin" }));
  resetHealthMock();
  return renderWithProviders(<AppRoutes />, { route });
}

describe("TenantDetailPage", () => {
  beforeEach(() => {
    localStorage.clear();
    resetTenantsMock();
  });

  it("渲染本地字段与三个 OV 信息区", async () => {
    setTenantDetail(
      1,
      makeTenantDetail({
        ...makeTenant({ id: 1, account_id: "acme", display_name: "Acme 团队", remark: "重点客户", user_count: 3 }),
      }),
    );
    renderAdminAt("/tenants/1");

    expect(await screen.findByText("Acme 团队")).toBeInTheDocument();
    expect(screen.getByText("重点客户")).toBeInTheDocument();
    expect(screen.getByText("账户信息")).toBeInTheDocument();
    expect(screen.getByText("账户配置")).toBeInTheDocument();
    expect(screen.getByText("账户设置")).toBeInTheDocument();
    expect(screen.queryByText(/OpenViking 信息获取失败/)).toBeNull();
  });

  it("查看原始 JSON 抽屉展示后端对象原文", async () => {
    const user = userEvent.setup();
    renderAdminAt("/tenants/1");
    await screen.findByText("账户配置");

    const buttons = screen.getAllByRole("button", { name: "查看原始 JSON" });
    await user.click(buttons[1]);

    const drawer = await screen.findByRole("dialog");
    expect(drawer).toHaveTextContent('"enabled": true');
    expect(drawer).toHaveTextContent('"version": 9');
  });

  it("OV 部分失败时 200 降级：横幅 + null 区占位，其余区域照常", async () => {
    setTenantDetail(
      1,
      makeTenantDetail({
        ov_error: "upstream down",
        configuration: null,
        settings: null,
      }),
    );
    renderAdminAt("/tenants/1");

    expect(await screen.findByText(/OpenViking 信息获取失败：upstream down/)).toBeInTheDocument();
    expect(screen.getAllByText("OpenViking 信息暂不可用")).toHaveLength(2);
    expect(screen.getByText("账户信息")).toBeInTheDocument();
  });

  it("团队不存在时显示 404 结果", async () => {
    setTenantDetail(999, null);
    renderAdminAt("/tenants/999");
    expect(await screen.findByText("团队不存在")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回团队列表" })).toBeInTheDocument();
  });

  it("编辑显示名与备注提交 PATCH，成功后页面刷新", async () => {
    const user = userEvent.setup();
    renderAdminAt("/tenants/1");
    await screen.findByText("Acme 团队");

    await user.click(screen.getByRole("button", { name: "编辑" }));
    const nameInput = await screen.findByLabelText("显示名");
    await user.clear(nameInput);
    await user.type(nameInput, "Acme 中国");
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(screen.getByText("Acme 中国")).toBeInTheDocument());
    const patch = getTenantRequests("PATCH")[0];
    expect(patch.body).toEqual({ display_name: "Acme 中国" });
  });

  it("备注留空时不发送该字段（后端 null 语义为不变）", async () => {
    const user = userEvent.setup();
    renderAdminAt("/tenants/1");
    await screen.findByText("Acme 团队");

    await user.click(screen.getByRole("button", { name: "编辑" }));
    const remarkInput = await screen.findByLabelText("备注");
    await user.clear(remarkInput);
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(getTenantRequests("PATCH")).toHaveLength(1));
    const body = getTenantRequests("PATCH")[0].body as Record<string, unknown>;
    expect(body).not.toHaveProperty("remark");
  });

  it("提供跳转到本团队用户列表的入口", async () => {
    renderAdminAt("/tenants/1");
    await screen.findByText("Acme 团队");
    const link = screen.getByRole("link", { name: "查看团队用户" });
    expect(link).toHaveAttribute("href", "/users?tenant_id=1");
  });
});
