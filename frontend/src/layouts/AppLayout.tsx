import { useMemo, type ReactNode } from "react";
import { Dropdown, Layout, Menu, Space, Typography } from "antd";
import type { MenuProps } from "antd";
import {
  DashboardOutlined,
  FileTextOutlined,
  KeyOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { HealthDot } from "@/components/HealthDot";
import { useAuth } from "@/auth/auth-context";
import { can, type Permission } from "@/auth/permissions";

const { Header, Sider, Content } = Layout;

/** 用户下拉菜单；超管账号不提供修改密码入口（UI 禁改密，01 AUTH-3）。 */
export function buildUserMenu(isEnvAdmin: boolean): MenuProps["items"] {
  const items: MenuProps["items"] = [
    { type: "divider" },
    { key: "logout", icon: <LogoutOutlined />, label: "注销", danger: true },
  ];
  if (!isEnvAdmin) {
    items.unshift({ key: "change-password", icon: <KeyOutlined />, label: "修改密码" });
  }
  return items;
}

const NAV_ITEMS: { key: string; label: string; permission: Permission; icon: ReactNode }[] = [
  { key: "/overview", label: "总览看板", permission: "overview:view", icon: <DashboardOutlined /> },
  { key: "/tenants", label: "团队管理", permission: "tenants:manage", icon: <TeamOutlined /> },
  { key: "/users", label: "用户管理", permission: "users:manage", icon: <UserOutlined /> },
  { key: "/audit-logs", label: "审计日志", permission: "audit:view", icon: <FileTextOutlined /> },
  { key: "/ldap-config", label: "LDAP 认证", permission: "ldap:manage", icon: <SafetyCertificateOutlined /> },
  { key: "/credentials", label: "我的凭证", permission: "credentials:view", icon: <KeyOutlined /> },
];

export function AppLayout() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const menuItems = useMemo(
    () => NAV_ITEMS.filter((item) => can(me?.role, item.permission)),
    [me?.role],
  );

  const userMenu: MenuProps["items"] = buildUserMenu(me?.is_env_admin ?? false);

  const onUserMenuClick: MenuProps["onClick"] = async ({ key }) => {
    if (key === "change-password") navigate("/change-password");
    if (key === "logout") {
      await logout();
      navigate("/login", { replace: true });
    }
  };

  return (
    <Layout style={{ minHeight: "100vh" }} hasSider>
      <Sider theme="dark" width={208}>
        <div
          style={{
            color: "#fff",
            fontWeight: 600,
            height: 48,
            margin: 16,
            display: "flex",
            alignItems: "center",
          }}
        >
          OpenViking
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems.map(({ key, label, icon }) => ({ key, label, icon }))}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            paddingInline: 24,
            background: "#fff",
          }}
        >
          <HealthDot />
          <Dropdown menu={{ items: userMenu, onClick: onUserMenuClick }} trigger={["click"]}>
            <Space style={{ cursor: "pointer" }} data-testid="user-menu">
              <UserOutlined />
              <Typography.Text>{me?.username}</Typography.Text>
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ padding: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
