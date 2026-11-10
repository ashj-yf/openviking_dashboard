import { useEffect, useMemo, useState } from "react";
import { Alert, App, Collapse, Form, Input, Modal, Radio, Select } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { qk } from "@/api/query-keys";
import { tenantApi } from "@/api/tenants";
import { userApi, type UserCreateBody } from "@/api/users";
import { useAuth } from "@/auth/auth-context";

interface Props {
  open: boolean;
  onClose: () => void;
}

const ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

export function ProvisionUserModal({ open, onClose }: Props) {
  const [form] = Form.useForm<UserCreateBody & { role: "admin" | "team_admin" | "user" }>();
  const { me } = useAuth();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [topError, setTopError] = useState<string | null>(null);
  const [ovTouched, setOvTouched] = useState(false);

  const isTeamAdmin = me?.role === "team_admin";
  const username = Form.useWatch("username", form) as string | undefined;

  const tenantsQuery = useQuery({
    queryKey: qk.tenants(""),
    queryFn: () => tenantApi.list(undefined),
    enabled: open && me?.role === "admin",
  });
  const tenantOptions = useMemo(
    () => (tenantsQuery.data ?? []).map((t) => ({ value: t.id, label: t.account_id, title: t.account_id })),
    [tenantsQuery.data],
  );

  useEffect(() => {
    if (open) {
      form.resetFields();
      form.setFieldsValue({ role: "user" });
      setOvTouched(false);
      setTopError(null);
    }
  }, [open, form]);

  useEffect(() => {
    if (!ovTouched && username) form.setFieldValue("ov_user_id", username);
  }, [username, ovTouched, form]);

  const mutation = useMutation({
    mutationFn: (values: UserCreateBody) => userApi.create(values),
    onSuccess: (created) => {
      message.success(
        `用户 ${created.username} 开通成功。请通过安全渠道交付登录地址、账号与初始密码；首次登录将被要求修改密码，user key 在「我的凭证」页面获取。`,
        6,
      );
      queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
    onError: (error) => {
      if (!(error instanceof ApiError)) {
        setTopError("开通失败，请稍后重试");
        return;
      }
      if (error.status === 502) {
        message.warning(error.message, 8);
        queryClient.invalidateQueries({ queryKey: ["users"] });
        onClose();
        return;
      }
      if (error.status === 403) {
        message.error(error.message);
        return;
      }
      if (error.fields) {
        form.setFields(
          Object.entries(error.fields).map(([name, errors]) => ({
            name: name as keyof UserCreateBody,
            errors: [errors],
          })),
        );
        return;
      }
      setTopError(error.message);
    },
  });

  function submit(raw: UserCreateBody) {
    // tenant_id/role 仅 admin 随请求发送；team_admin 由后端按会话身份强制，
    // wire 层缺省两者合法（契约 role 为必填但标注 @default user），故字面量断言收窄。
    const body = {
      username: raw.username,
      password: raw.password,
      ov_user_id: raw.ov_user_id || undefined,
      seed: raw.seed || undefined,
    } as UserCreateBody;
    if (me?.role === "admin") {
      body.tenant_id = raw.tenant_id ?? undefined;
      body.role = raw.role === "team_admin" ? "team_admin" : "user";
    }
    mutation.mutate(body);
  }

  return (
    <Modal
      title="开通用户"
      open={open}
      okText="开通"
      cancelText="取消"
      confirmLoading={mutation.isPending}
      onOk={() => form.submit()}
      onCancel={onClose}
      destroyOnHidden
    >
      {topError && (
        <Alert type="error" showIcon style={{ marginBottom: 16 }} message={topError} />
      )}
      <Form form={form} layout="vertical" requiredMark={false} onFinish={submit}>
        <Form.Item label="登录用户名" name="username" rules={[{ required: true, message: "请输入登录用户名" }, { max: 64 }]}>
          <Input maxLength={64} autoComplete="off" />
        </Form.Item>
        <Form.Item
          label="初始密码"
          name="password"
          rules={[
            { required: true, message: "请输入初始密码" },
            { min: 8, max: 128, message: "密码长度需为 8-128 位" },
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        {isTeamAdmin ? (
          <Form.Item label="归属团队">
            <span>{me?.account_id}</span>
          </Form.Item>
        ) : (
          <Form.Item label="归属团队" name="tenant_id" rules={[{ required: true, message: "请选择归属团队" }]}>
            <Select options={tenantOptions} placeholder="选择团队" loading={tenantsQuery.isLoading} />
          </Form.Item>
        )}
        <Form.Item
          label="OV 用户 ID"
          name="ov_user_id"
          rules={[{ pattern: ID_PATTERN, message: "仅允许字母、数字、下划线、连字符，长度 1-64" }]}
          extra="留空则与登录名一致；创建后不可修改"
        >
          <Input maxLength={64} autoComplete="off" onChange={() => setOvTouched(true)} />
        </Form.Item>
        {!isTeamAdmin && (
          <Form.Item label="Dashboard 角色" name="role">
            <Radio.Group>
              <Radio value="user">普通用户</Radio>
              <Radio value="team_admin">团队管理员</Radio>
            </Radio.Group>
          </Form.Item>
        )}
        <Collapse
          destroyOnHidden
          items={[
            {
              key: "advanced",
              label: "高级选项",
              children: (
                <Form.Item label="Seed（可选）" name="seed" extra="同 seed 可确定性重建密钥">
                  <Input maxLength={256} autoComplete="off" />
                </Form.Item>
              ),
            },
          ]}
        />
      </Form>
    </Modal>
  );
}
