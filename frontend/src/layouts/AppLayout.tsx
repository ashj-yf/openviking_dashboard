import { Dropdown, Layout, Space, Typography } from "antd";
import type { MenuProps } from "antd";
import { LogoutOutlined, KeyOutlined, UserOutlined } from "@ant-design/icons";
import { Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";

const { Header, Content } = Layout;

export function AppLayout() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();

  const menuItems: MenuProps["items"] = [
    { key: "change-password", icon: <KeyOutlined />, label: "修改密码" },
    { type: "divider" },
    { key: "logout", icon: <LogoutOutlined />, label: "注销", danger: true },
  ];

  const onMenuClick: MenuProps["onClick"] = async ({ key }) => {
    if (key === "change-password") {
      navigate("/change-password");
    } else if (key === "logout") {
      await logout();
      navigate("/login", { replace: true });
    }
  };

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          paddingInline: 24,
        }}
      >
        <Typography.Text strong style={{ color: "#fff", fontSize: 16 }}>
          OpenViking 管理后台
        </Typography.Text>
        <Dropdown menu={{ items: menuItems, onClick: onMenuClick }} trigger={["click"]}>
          <Space style={{ color: "#fff", cursor: "pointer" }} data-testid="user-menu">
            <UserOutlined />
            {me?.username}
          </Space>
        </Dropdown>
      </Header>
      <Content style={{ padding: 24 }}>
        <Outlet />
      </Content>
    </Layout>
  );
}
