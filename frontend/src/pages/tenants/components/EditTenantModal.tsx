import { useEffect } from "react";
import { App, Form, Input, Modal } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { tenantApi, type TenantDetail, type TenantUpdateBody } from "@/api/tenants";

interface Props {
  open: boolean;
  tenant: TenantDetail;
  onClose: () => void;
}

export function EditTenantModal({ open, tenant, onClose }: Props) {
  const [form] = Form.useForm<TenantUpdateBody>();
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (open) form.setFieldsValue({ display_name: tenant.display_name, remark: tenant.remark });
  }, [open, tenant, form]);

  const mutation = useMutation({
    mutationFn: (values: TenantUpdateBody) => {
      const body: TenantUpdateBody = {};
      if (values.display_name && values.display_name.trim().length > 0) {
        body.display_name = values.display_name;
      }
      if (values.remark && values.remark.trim().length > 0) body.remark = values.remark;
      return tenantApi.update(tenant.id, body);
    },
    onSuccess: () => {
      message.success("团队信息已更新");
      queryClient.invalidateQueries({ queryKey: ["tenant", tenant.id] });
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
      onClose();
    },
    onError: (error) => {
      message.error(error instanceof ApiError ? error.message : "更新失败，请稍后重试");
    },
  });

  return (
    <Modal
      title={`编辑团队 · ${tenant.account_id}`}
      open={open}
      okText="保存"
      cancelText="取消"
      confirmLoading={mutation.isPending}
      onOk={() => form.submit()}
      onCancel={onClose}
      destroyOnClose
    >
      <Form form={form} layout="vertical" onFinish={(values) => mutation.mutate(values)}>
        <Form.Item label="显示名" name="display_name" rules={[{ max: 128 }]}>
          <Input maxLength={128} />
        </Form.Item>
        <Form.Item label="备注" name="remark" rules={[{ max: 500 }]}>
          <Input.TextArea rows={3} maxLength={500} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
