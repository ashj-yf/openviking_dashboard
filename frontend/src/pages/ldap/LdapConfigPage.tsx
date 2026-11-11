import { useEffect, useState } from "react";
import { Alert, App, Button, Card, Col, Form, Input, InputNumber, Row, Select, Space, Switch, Typography } from "antd";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { ldapApi, type LdapConfigUpdate } from "@/api/ldap";
import { qk } from "@/api/query-keys";

type Encryption = LdapConfigUpdate["encryption"];

interface LdapConfigFormValues {
  enabled: boolean;
  server_host: string;
  server_port: number;
  encryption: Encryption;
  bind_dn?: string;
  bind_password?: string;
  user_base_dn: string;
  user_filter: string;
  attr_uid: string;
  attr_mail: string;
  attr_display_name: string;
}

const ENCRYPTION_OPTIONS = [
  { value: "none", label: "无" },
  { value: "starttls", label: "StartTLS" },
  { value: "ldaps", label: "LDAPS" },
] satisfies { value: Encryption; label: string }[];

export function LdapConfigPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<LdapConfigFormValues>();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const { data, isError, error, refetch } = useQuery({
    queryKey: qk.ldapConfig,
    queryFn: () => ldapApi.getConfig(),
  });

  const hasBindPassword = data?.has_bind_password ?? false;

  // GET 落地后回填表单；bind_password 只写不读，恒为空
  useEffect(() => {
    if (!data) return;
    form.setFieldsValue({
      enabled: data.enabled,
      server_host: data.server_host,
      server_port: data.server_port,
      encryption: (data.encryption as Encryption) ?? "none",
      bind_dn: data.bind_dn ?? "",
      bind_password: "",
      user_base_dn: data.user_base_dn,
      user_filter: data.user_filter,
      attr_uid: data.attr_uid,
      attr_mail: data.attr_mail,
      attr_display_name: data.attr_display_name,
    });
  }, [data, form]);

  function buildPayload(values: LdapConfigFormValues): LdapConfigUpdate {
    const bindPassword = values.bind_password ?? "";
    const bindDn = (values.bind_dn ?? "").trim();
    return {
      enabled: values.enabled,
      server_host: values.server_host,
      server_port: values.server_port,
      encryption: values.encryption,
      bind_dn: bindDn ? bindDn : undefined,
      // 空串/纯空白视为「未输入」：不发键，后端按 None 语义保留已存密文
      bind_password: bindPassword.trim() ? bindPassword : undefined,
      user_base_dn: values.user_base_dn,
      user_filter: values.user_filter,
      attr_uid: values.attr_uid,
      attr_mail: values.attr_mail,
      attr_display_name: values.attr_display_name,
    };
  }

  async function onSave(values: LdapConfigFormValues) {
    setSaving(true);
    try {
      await ldapApi.save(buildPayload(values));
      message.success("LDAP 配置已保存并即时生效");
      // me 缓存携带 ldap_enabled（登录分流依据），一并失效让导航与登录语义即时更新
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.ldapConfig }),
        queryClient.invalidateQueries({ queryKey: qk.me }),
      ]);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "保存失败，请稍后重试");
    } finally {
      setSaving(false);
    }
  }

  async function onTest() {
    let values: LdapConfigFormValues;
    try {
      values = await form.validateFields();
    } catch {
      // 校验失败：错误已就地挂在对应表单项，不发请求
      return;
    }
    const payload = buildPayload(values);
    if (!payload.bind_password) {
      message.warning("请填写 Bind 密码后再测试");
      return;
    }
    setTesting(true);
    try {
      const result = await ldapApi.test(payload);
      if (result.ok) message.success(result.message);
      else message.error(result.message);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "测试失败，请稍后重试");
    } finally {
      setTesting(false);
    }
  }

  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        LDAP 认证
      </Typography.Title>
      <Card>
        {/* 读取失败必须显式呈错，不能以空表单假装成功 */}
        {isError && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message={error.message}
            action={
              <Button size="small" danger onClick={() => refetch()}>
                重试
              </Button>
            }
          />
        )}
        <Form<LdapConfigFormValues>
          form={form}
          layout="vertical"
          requiredMark={false}
          onFinish={onSave}
        >
          <Form.Item label="启用 LDAP 认证" name="enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label="服务器地址"
                name="server_host"
                rules={[{ required: true, message: "请输入服务器地址" }]}
              >
                <Input placeholder="如 ldap.example.com" autoComplete="off" />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item
                label="端口"
                name="server_port"
                rules={[{ required: true, message: "请输入端口" }]}
              >
                <InputNumber min={1} max={65535} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="加密方式" name="encryption">
                <Select options={ENCRYPTION_OPTIONS} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="Bind DN（可选）" name="bind_dn">
                <Input placeholder="留空则匿名检索，如 cn=svc,dc=example" autoComplete="off" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="Bind 密码" name="bind_password">
                <Input.Password
                  autoComplete="new-password"
                  placeholder={hasBindPassword ? "已保存，留空保持不变" : undefined}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label="用户 Base DN"
                name="user_base_dn"
                rules={[{ required: true, message: "请输入用户 Base DN" }]}
              >
                <Input placeholder="如 ou=people,dc=example" autoComplete="off" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="用户过滤条件"
                name="user_filter"
                rules={[{ required: true, message: "请输入用户过滤条件" }]}
              >
                <Input placeholder="(uid={username})" autoComplete="off" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                label="UID 属性"
                name="attr_uid"
                rules={[{ required: true, message: "请输入 UID 属性" }]}
              >
                <Input autoComplete="off" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                label="邮箱属性"
                name="attr_mail"
                rules={[{ required: true, message: "请输入邮箱属性" }]}
              >
                <Input autoComplete="off" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                label="显示名属性"
                name="attr_display_name"
                rules={[{ required: true, message: "请输入显示名属性" }]}
              >
                <Input autoComplete="off" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item style={{ marginBottom: 0 }}>
            <Space>
              <Button type="primary" htmlType="submit" loading={saving}>
                保存
              </Button>
              <Button loading={testing} onClick={onTest}>
                测试连接
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </>
  );
}
