import { useState } from "react";
import { Alert, App, Button, Card, Form, Input, Typography } from "antd";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { getToken } from "@/auth/token-store";
import { AuthLayout } from "@/layouts/AuthLayout";

interface LoginFormValues {
  username: string;
  password: string;
}

export function LoginPage() {
  const { me, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const expired = (location.state as { expired?: boolean } | null)?.expired === true;

  // 仅在本地确有有效会话时弹回首页；401 过期场景 token 已清，me 缓存可能尚未刷新，
  // 只看 me 会把过期跳转弹回 "/" 并丢掉 expired 提示状态。
  if (me && getToken() !== null) {
    window.queueMicrotask(() => navigate("/", { replace: true }));
  }

  async function onFinish(values: LoginFormValues) {
    setLoading(true);
    try {
      await login(values.username, values.password);
      navigate("/", { replace: true });
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : "登录失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout>
      <Card style={{ width: 360 }}>
        <Typography.Title level={3} style={{ textAlign: "center", marginTop: 0 }}>
          OpenViking 管理后台
        </Typography.Title>
        {expired && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="登录状态已过期，请重新登录"
          />
        )}
        <Form<LoginFormValues> onFinish={onFinish} layout="vertical" requiredMark={false}>
          <Form.Item
            label="用户名"
            name="username"
            rules={[{ required: true, message: "请输入用户名" }]}
          >
            <Input prefix={<UserOutlined />} autoComplete="username" />
          </Form.Item>
          <Form.Item
            label="密码"
            name="password"
            rules={[{ required: true, message: "请输入密码" }]}
          >
            <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </AuthLayout>
  );
}
