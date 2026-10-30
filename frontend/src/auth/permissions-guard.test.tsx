import { screen } from "@testing-library/react";
import { Routes, Route } from "react-router-dom";
import type { ReactNode } from "react";
import { renderWithProviders } from "@/test/utils";
import { RequireRole } from "@/router/AppRoutes";
import type { Role } from "@/auth/permissions";
import type { Me } from "@/api/auth";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";

function renderGuard(me: Me, allow: Role | Role[]) {
  localStorage.setItem("ov-dashboard-token", `jwt-${me.username}`);
  resetAuthMock(me);
  function Harness({ children }: { children: ReactNode }) {
    return (
      <Routes>
        <Route path="/" element={<RequireRole allow={allow}>{children}</RequireRole>} />
        <Route path="/403" element={<div>无权访问此页面</div>} />
      </Routes>
    );
  }
  return renderWithProviders(
    <Harness>
      <div>目标内容</div>
    </Harness>,
    { route: "/" },
  );
}

describe("RequireRole", () => {
  beforeEach(() => localStorage.clear());

  it("普通用户访问仅 admin 区域被送到 /403", async () => {
    renderGuard(makeMe({ id: 3, username: "alice", role: "user", tenant_id: 1 }), "admin");
    expect(await screen.findByText("无权访问此页面")).toBeInTheDocument();
    expect(screen.queryByText("目标内容")).toBeNull();
  });

  it("team_admin 访问仅 admin 区域被拒绝", async () => {
    renderGuard(makeMe({ id: 5, username: "boss", role: "team_admin", ov_role: "admin" }), "admin");
    expect(await screen.findByText("无权访问此页面")).toBeInTheDocument();
  });

  it("team_admin 可进入 admin|team_admin 共享区域", async () => {
    renderGuard(makeMe({ id: 5, username: "boss", role: "team_admin", ov_role: "admin" }), [
      "admin",
      "team_admin",
    ]);
    expect(await screen.findByText("目标内容")).toBeInTheDocument();
  });

  it("平台 admin 无 OV 身份，凭证区域对其关闭", async () => {
    renderGuard(makeMe({ role: "admin" }), ["team_admin", "user"]);
    expect(await screen.findByText("无权访问此页面")).toBeInTheDocument();
  });
});
