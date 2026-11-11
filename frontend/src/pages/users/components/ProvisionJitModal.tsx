import { useEffect, useState } from "react";
import { Alert, App, Form, Input, Modal, Radio, Select } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { qk } from "@/api/query-keys";
import { tenantApi } from "@/api/tenants";
import { userApi, type UserListItem, type UserProvisionBody } from "@/api/users";

interface Props {
  open: boolean;
  user: UserListItem;
  onClose: () => void;
}

interface ProvisionJitFormValues {
  tenant_id: number;
  role: "team_admin" | "user";
  ov_user_id?: string;
}

const ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

/** LDAP JIT 用户开通弹窗：为自动建档用户（auth_source=ldap 且未归属团队）补全团队与 OV 身份。 */
export function ProvisionJitModal({ open, user, onClose }: Props) {
  const [form] = Form.useForm<ProvisionJitFormValues>();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [topError, setTopError] = useState<string | null>(null);

  const tenantsQuery = useQuery({
    queryKey: qk.tenants(""),
    queryFn: () => tenantApi.list(undefined),
    enabled: open,
  });
  const tenantOptions = (tenantsQuery.data ?? []).map((t) => ({
    value: t.id,
    label: t.account_id,
  }));

  useEffect(() => {
    if (open) {
      form.resetFields();
      form.setFieldsValue({ role: "user" });
      setTopError(null);
    }
  }, [open, form]);

  const mutation = useMutation({
    mutationFn: (values: ProvisionJitFormValues) =>
      userApi.provision(user.id, {
        tenant_id: values.tenant_id,
        role: values.role === "team_admin" ? "team_admin" : "user",
        ov_user_id: values.ov_user_id || undefined,
      } satisfies UserProvisionBody),
    onSuccess: (updated) => {
      message.success(
        `用户 ${updated.username} 开通成功，OV key 已签发，可在「我的凭证」页面获取`,
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
        // OV 侧已注册但签发失败：半成品保留 OV 归属，可经「重签密钥」复活补救（B4 R1）。
        message.warning(error.message, 8);
        queryClient.invalidateQueries({ queryKey: ["users"] });
        onClose();
        return;
      }
      if (error.fields) {
        form.setFields(
          Object.entries(error.fields).map(([name, errors]) => ({
            name: name as keyof ProvisionJitFormValues,
            errors: [errors],
          })),
        );
        return;
      }
      setTopError(error.message);
    },
  });

  return (
    <Modal
      title="开通 LDAP 用户"
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
      <Form form={form} layout="vertical" requiredMark={false} onFinish={(values) => mutation.mutate(values)}>
        <Form.Item label="登录用户名">
          <span>{user.username}</span>
        </Form.Item>
        <Form.Item
          label="归属团队"
          name="tenant_id"
          rules={[{ required: true, message: "请选择归属团队" }]}
        >
          <Select options={tenantOptions} placeholder="选择团队" loading={tenantsQuery.isLoading} />
        </Form.Item>
        <Form.Item label="OV 角色" name="role">
          <Radio.Group>
            <Radio value="user">普通用户</Radio>
            <Radio value="team_admin">团队管理员</Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item
          label="OV 用户 ID"
          name="ov_user_id"
          rules={[{ pattern: ID_PATTERN, message: "仅允许字母、数字、下划线、连字符，长度 1-64" }]}
          extra="留空则与登录名一致；创建后不可修改"
        >
          <Input maxLength={64} autoComplete="off" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
