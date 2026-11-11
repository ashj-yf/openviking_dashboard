import { useState } from "react";
import { App, Button, Descriptions, Modal, Tag } from "antd";
import { useMutation } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { userApi, type UserListItem, type UserSyncReport } from "@/api/users";

export function UserSyncModal({ user }: { user: UserListItem }) {
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState<UserSyncReport | null>(null);
  const { message } = App.useApp();

  const mutation = useMutation({
    mutationFn: () => userApi.sync(user.id),
    onSuccess: (data) => {
      setReport(data);
      setOpen(true);
    },
    onError: (error) => {
      message.error(error instanceof ApiError ? error.message : "校准失败，请稍后重试");
    },
  });

  return (
    <>
      <Button size="small" loading={mutation.isPending} onClick={() => mutation.mutate()}>
        校准
      </Button>
      <Modal title={`绑定校准 · ${user.username}`} open={open} footer={null} onCancel={() => setOpen(false)}>
        {report && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="OpenViking 侧存在">
              {report.ov_exists ? "是" : "否"}
            </Descriptions.Item>
            <Descriptions.Item label="一致性">
              {report.consistent ? <Tag color="green">一致</Tag> : <Tag color="red">不一致</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="本地 OV 角色">{report.local_ov_role ?? "—"}</Descriptions.Item>
            <Descriptions.Item label="OV 侧角色">{report.ov_role ?? "—"}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </>
  );
}
