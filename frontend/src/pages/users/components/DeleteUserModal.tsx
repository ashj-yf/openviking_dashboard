import { useState } from "react";
import { Alert, App, Button, Checkbox, Modal, Space } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { userApi, type UserListItem } from "@/api/users";

export function DeleteUserModal({ user }: { user: UserListItem }) {
  const [open, setOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => userApi.remove(user.id),
    onSuccess: () => {
      message.success(`用户 ${user.username} 已销户`);
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setOpen(false);
      setAcknowledged(false);
    },
    onError: (error) => {
      message.error(error instanceof ApiError ? error.message : "销户失败，请稍后重试");
    },
  });

  return (
    <>
      <Button size="small" danger onClick={() => setOpen(true)}>
        销户
      </Button>
      <Modal
        title={`销户 · ${user.username}`}
        open={open}
        okText="确认销户"
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
            message="销户将同时删除其 OpenViking 用户与本地账号，全部数据不可恢复。"
          />
          <Checkbox checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)}>
            我已知晓上述后果，确认销户
          </Checkbox>
        </Space>
      </Modal>
    </>
  );
}
