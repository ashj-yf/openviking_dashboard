import { useState } from "react";
import { Alert, App, Button, Checkbox, Modal, Space } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { tenantApi, type TenantListItem } from "@/api/tenants";

interface Props {
  tenant: TenantListItem;
}

export function DeleteTenantModal({ tenant }: Props) {
  const [open, setOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => tenantApi.remove(tenant.id),
    onSuccess: () => {
      message.success(`团队 ${tenant.account_id} 已删除`);
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
      setOpen(false);
      setAcknowledged(false);
    },
    onError: (error) => {
      message.error(error instanceof ApiError ? error.message : "删除失败，请稍后重试");
    },
  });

  return (
    <>
      <Button type="link" danger size="small" onClick={() => setOpen(true)}>
        删除
      </Button>
      <Modal
        title={`删除团队 ${tenant.account_id}`}
        open={open}
        okText="确认删除"
        okButtonProps={{ danger: true, disabled: !acknowledged }}
        cancelText="取消"
        confirmLoading={mutation.isPending}
        onOk={() => mutation.mutate()}
        onCancel={() => {
          setOpen(false);
          setAcknowledged(false);
        }}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Alert
            type="error"
            showIcon
            message="删除后该团队在 OpenViking 的账户及其全部用户、数据将不可恢复，本地绑定记录同步删除。"
          />
          <Checkbox checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)}>
            我已知晓上述后果，确认删除
          </Checkbox>
        </Space>
      </Modal>
    </>
  );
}
