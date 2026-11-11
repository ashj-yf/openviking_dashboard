import { useState } from "react";
import { Alert, App, Button, Card, Form, Input, Modal, Typography } from "antd";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/auth/auth-context";
import { ApiError } from "@/api/client";
import * as authApi from "@/api/auth";
import { getToken, setToken } from "@/auth/token-store";
import { qk } from "@/api/query-keys";
import { AuthLayout } from "@/layouts/AuthLayout";

interface LoginFormValues {
  username: string;
  password: string;
}

interface BindFormValues {
  ldap_username: string;
  ldap_password: string;
}

export function LoginPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [binding, setBinding] = useState(false);
  // bind_token 只存组件态（刷新即失），绝不写 token-store；非空即弹绑定窗。
  const [bindToken, setBindToken] = useState<string | null>(null);
  const [bindUsername, setBindUsername] = useState("");
  const [bindError, setBindError] = useState<string | null>(null);
  const expired = (location.state as { expired?: boolean } | null)?.expired === true;

  // 仅在本地确有有效会话时弹回首页；401 过期场景 token 已清，me 缓存可能尚未刷新，
  // 只看 me 会把过期跳转弹回 "/" 并丢掉 expired 提示状态。
  if (me && getToken() !== null) {
    window.queueMicrotask(() => navigate("/", { replace: true }));
  }

  async function onFinish(values: LoginFormValues) {
    setLoading(true);
    try {
      const resp = await authApi.login({ username: values.username, password: values.password });
      // must_bind：本次登录不签发会话（access_token 为空串），不能走 useAuth().login 的
      // 存 token + 导航路径；只留弹窗绑定，绑定成功后要求以 LDAP 账号重新登录。
      if (resp.must_bind) {
        if (resp.bind_token) {
          setBindUsername(values.username);
          setBindToken(resp.bind_token);
        }
        return;
      }
      setToken(resp.access_token);
      // me 查询 enabled 读 token-store 且仅在重渲染时重估：本路径没有 AuthProvider 内部
      // mutation 的重渲染信号，invalidate 拉不起 disabled 查询，直接显式取数落缓存，
      // 避免跳转后 RequireAuth 在 me 未就绪时把会话弹回登录页。
      await queryClient.fetchQuery({ queryKey: qk.me, queryFn: authApi.fetchMe });
      navigate("/", { replace: true });
    } catch (error) {
      message.error(error instanceof ApiError ? error.message : "登录失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  async function onBindFinish(values: BindFormValues) {
    if (!bindToken) return;
    setBinding(true);
    setBindError(null);
    try {
      await authApi.ldapBind(values.ldap_username, values.ldap_password, bindToken);
      message.success("绑定成功，请使用 LDAP 账号重新登录");
      closeBindModal();
    } catch (error) {
      setBindError(error instanceof ApiError ? error.message : "绑定失败，请稍后重试");
    } finally {
      setBinding(false);
    }
  }

  function closeBindModal() {
    // 仅关弹窗留在登录页：无会话可清，丢弃组件态 bind_token（重新登录才可再绑定）。
    setBindToken(null);
    setBindError(null);
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
        {/* 弹窗期间封住主表单，避免绕过绑定直接用本地账号进入 */}
        <Form<LoginFormValues>
          onFinish={onFinish}
          layout="vertical"
          requiredMark={false}
          disabled={bindToken !== null}
        >
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
            <Button
              type="primary"
              htmlType="submit"
              block
              loading={loading}
              disabled={bindToken !== null}
            >
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
      <Modal
        title="绑定 LDAP 账号"
        open={bindToken !== null}
        onCancel={closeBindModal}
        // 绑定是进入系统的必经步骤：不允许误触遮罩跳过，仅保留右上角关闭按钮显式退出（留登录页）。
        maskClosable={false}
        footer={null}
        destroyOnHidden
      >
        {bindError && (
          <Alert type="error" showIcon style={{ marginBottom: 16 }} message={bindError} />
        )}
        {/* destroyOnHidden 使每次打开都按最新登录用户名重挂表单，实现账号默认预填 */}
        <Form<BindFormValues>
          onFinish={onBindFinish}
          layout="vertical"
          requiredMark={false}
          initialValues={{ ldap_username: bindUsername }}
        >
          <Form.Item
            label="LDAP 账号"
            name="ldap_username"
            rules={[{ required: true, message: "请输入 LDAP 账号" }]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item
            label="LDAP 密码"
            name="ldap_password"
            rules={[{ required: true, message: "请输入 LDAP 密码" }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" block loading={binding}>
              绑定
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    </AuthLayout>
  );
}
