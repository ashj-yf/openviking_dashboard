import { useEffect, type ReactNode } from "react";
import { Spin } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { authExpired } from "@/api/client";
import type { Me } from "@/api/auth";
import { qk } from "@/api/query-keys";
import { useAuth } from "@/auth/auth-context";
import { homePathFor, type Role } from "@/auth/permissions";
import { AppLayout } from "@/layouts/AppLayout";
import { ChangePasswordPage } from "@/pages/ChangePasswordPage";
import { ForbiddenPage } from "@/pages/errors/ForbiddenPage";
import { NotFoundPage } from "@/pages/errors/NotFoundPage";
import { LoginPage } from "@/pages/LoginPage";
import { TenantDetailPage } from "@/pages/tenants/TenantDetailPage";
import { TenantListPage } from "@/pages/tenants/TenantListPage";
import { UserListPage } from "@/pages/users/UserListPage";
import { getToken } from "@/auth/token-store";

/** 监听 401 事件，统一跳登录（Api client 已在此前清除 token）。 */
function AuthBoundary() {
  const navigate = useNavigate();
  useEffect(() => {
    const onExpired = () =>
      navigate("/login", { replace: true, state: { expired: true } });
    authExpired.addEventListener("expired", onExpired);
    return () => authExpired.removeEventListener("expired", onExpired);
  }, [navigate]);
  return null;
}

function FullScreenSpin() {
  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Spin size="large" />
    </div>
  );
}

function RequireAuth() {
  const { me, isLoading } = useAuth();
  const location = useLocation();
  if (getToken() === null) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  // 引导查询已结束却没有 me（如 /me 失败且未触发 401 事件），回登录页；
  // 引导未决不在此拦截——/change-password 必须立即可达，应用区由 BootstrapGate 等待。
  if (!me && !isLoading) return <Navigate to="/login" replace />;
  return <Outlet />;
}

export function RequireRole({ allow, children }: { allow: Role | Role[]; children: ReactNode }) {
  const { me } = useAuth();
  // 生产路径上 RequireRole 总在 RequireAuth 之内（me 必然已就绪）；
  // me 未就绪时不判定，避免会话引导期间误重定向到 /403。
  if (!me) return null;
  const roles = Array.isArray(allow) ? allow : [allow];
  if (roles.includes(me.role as Role)) return <>{children}</>;
  return <Navigate to="/403" replace />;
}

/** 应用区（含 HomeRedirect）等待 /me 落地，避免按默认角色误跳再纠正。 */
function BootstrapGate() {
  const { me, isLoading } = useAuth();
  if (getToken() !== null && !me && isLoading) return <FullScreenSpin />;
  return <Outlet />;
}

function ForceChangeGate() {
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const location = useLocation();
  // 改密成功后在同一事件循环内 navigate：AuthProvider 位于 Router 外层，context
  // 刷新可能晚于本次路由渲染，故门禁位直接读实时缓存，避免被滞后的 me 弹回改密页。
  const mustChange =
    queryClient.getQueryData<Me>(qk.me)?.must_change_password ?? me?.must_change_password;
  if (mustChange && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  return <Outlet />;
}

function HomeRedirect() {
  const { me } = useAuth();
  return <Navigate to={homePathFor(me?.role)} replace />;
}

function PlaceholderPage({ title }: { title: string }) {
  return <div data-testid="landing-placeholder">{title}页（待实现）</div>;
}

export function AppRoutes() {
  return (
    <>
      <AuthBoundary />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/change-password" element={<ChangePasswordPage />} />
          <Route element={<BootstrapGate />}>
            <Route element={<ForceChangeGate />}>
              <Route element={<AppLayout />}>
                <Route index element={<HomeRedirect />} />
                <Route
                  path="/tenants"
                  element={
                    <RequireRole allow="admin">
                      <TenantListPage />
                    </RequireRole>
                  }
                />
                <Route
                  path="/tenants/:id"
                  element={
                    <RequireRole allow="admin">
                      <TenantDetailPage />
                    </RequireRole>
                  }
                />
                {/* 落地占位：T8 替换为带 RequireRole 的真实页面 */}
                <Route
                  path="/users"
                  element={
                    <RequireRole allow={["admin", "team_admin"]}>
                      <UserListPage />
                    </RequireRole>
                  }
                />
                <Route path="/credentials" element={<PlaceholderPage title="我的凭证" />} />
                <Route path="/403" element={<ForbiddenPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Route>
          </Route>
        </Route>
      </Routes>
    </>
  );
}
