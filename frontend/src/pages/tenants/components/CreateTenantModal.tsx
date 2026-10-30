import { useState } from "react";
import { Alert, App, Collapse, Form, Input, Modal } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { tenantApi, type TenantCreateBody } from "@/api/tenants";

const ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

interface Props {
  open: boolean;
  onClose: () => void;
}

export function CreateTenantModal({ open, onClose }: Props) {
  const [form] = Form.useForm<TenantCreateBody>();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [topError, setTopError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (body: TenantCreateBody) => tenantApi.create(body),
    onSuccess: (created) => {
      message.success(`团队 ${created.account_id} 创建成功，请通过安全渠道交付初始密码`);
      if (!created.key_provisioned) {
        message.warning("初始团队管理员的 user key 未随创建返回，可在「我的凭证」自助重签");
      }
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
      form.resetFields();
      setTopError(null);
      onClose();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.fields) {
        form.setFields(
          Object.entries(error.fields).map(([name, errors]) => ({
            name: name as keyof TenantCreateBody,
            errors: [errors],
          })),
        );
        return;
      }
      setTopError(error instanceof ApiError ? error.message : "创建失败，请稍后重试");
    },
  });

  return (
    <Modal
      title="新建团队"
      open={open}
      onCancel={() => {
        form.resetFields();
        setTopError(null);
        onClose();
      }}
      onOk={() => form.submit()}
      confirmLoading={mutation.isPending}
      okText="创建"
      destroyOnClose
    >
      {topError && (
        <Alert type="error" showIcon style={{ marginBottom: 16 }} message={topError} />
      )}
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        onFinish={(values) => mutation.mutate(values)}
      >
        <Form.Item
          label="团队 ID（account_id）"
          name="account_id"
          rules={[
            { required: true, message: "请输入团队 ID" },
            { pattern: ID_PATTERN, message: "仅允许字母、数字、下划线、连字符，长度 1-64" },
          ]}
        >
          <Input placeholder="如 acme，创建后不可修改" />
        </Form.Item>
        <Form.Item
          label="初始管理员 OV ID"
          name="admin_user_id"
          rules={[
            { required: true, message: "请输入初始管理员 OV ID" },
            { pattern: ID_PATTERN, message: "仅允许字母、数字、下划线、连字符，长度 1-64" },
          ]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          label="管理员登录名"
          name="admin_username"
          rules={[{ required: true, message: "请输入管理员登录名" }]}
        >
          <Input maxLength={64} />
        </Form.Item>
        <Form.Item
          label="管理员初始密码"
          name="admin_password"
          rules={[
            { required: true, message: "请输入管理员初始密码" },
            { min: 8, max: 128, message: "密码长度需为 8-128 位" },
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item label="显示名（可选）" name="display_name">
          <Input maxLength={128} />
        </Form.Item>
        <Form.Item label="备注（可选）" name="remark">
          <Input.TextArea maxLength={500} rows={2} />
        </Form.Item>
        <Collapse
          destroyInactivePanel
          items={[
            {
              key: "advanced",
              label: "高级选项",
              children: (
                <Form.Item
                  label="Seed（可选）"
                  name="seed"
                  extra="同 seed 可确定性重建密钥；仅在确有需要时填写"
                >
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
