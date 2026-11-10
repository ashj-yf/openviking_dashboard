import { Alert, App, Button, Card, Form, Input, Space, Typography } from "antd";
import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import { homePathFor } from "@/auth/permissions";
import { AuthLayout } from "@/layouts/AuthLayout";

interface ChangePasswordFormValues {
  old_password: string;
  new_password: string;
  confirm: string;
}

export function ChangePasswordPage() {
  const { me, changePassword, logout } = useAuth();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  async function onFinish(values: ChangePasswordFormValues) {
    setLoading(true);
    try {
      await changePassword(values.old_password, values.new_password);
      message.success("密码已修改");
      navigate(homePathFor(me?.role), { replace: true });
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : "修改失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  // 强改密门禁没有其他出口，提供换账号通道：走全局注销（清 token 与 me 缓存）后回登录页。
  async function onLogout() {
    setLoggingOut(true);
    try {
      await logout();
    } finally {
      setLoggingOut(false);
      navigate("/login", { replace: true });
    }
  }

  return (
    <AuthLayout>
      <Card style={{ width: 400 }}>
        <Typography.Title level={3} style={{ marginTop: 0 }}>
          修改密码
        </Typography.Title>
        {me?.must_change_password && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="首次登录或密码已被重置，请先修改密码后再使用系统"
          />
        )}
        <Form<ChangePasswordFormValues> layout="vertical" requiredMark={false} onFinish={onFinish}>
          <Form.Item
            label="旧密码"
            name="old_password"
            rules={[{ required: true, message: "请输入旧密码" }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            label="新密码"
            name="new_password"
            rules={[
              { required: true, message: "请输入新密码" },
              { min: 8, max: 128, message: "密码长度需为 8-128 位" },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            label="确认新密码"
            name="confirm"
            dependencies={["new_password"]}
            rules={[
              { required: true, message: "请再次输入新密码" },
              ({ getFieldValue }) => ({
                validator: (_: unknown, value: string) =>
                  !value || getFieldValue("new_password") === value
                    ? Promise.resolve()
                    : Promise.reject(new Error("两次输入的新密码不一致")),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              <Button type="primary" htmlType="submit" block loading={loading}>
                提交
              </Button>
              <Button block loading={loggingOut} onClick={onLogout}>
                注销并切换账号
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </AuthLayout>
  );
}
