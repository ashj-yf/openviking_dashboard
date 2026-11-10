import { useState } from "react";
import { Alert, App, Button, Collapse, Form, Input, Modal } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { userApi, type UserListItem } from "@/api/users";

interface Props {
  user: UserListItem;
}

export function RegenerateKeyModal({ user }: Props) {
  const [open, setOpen] = useState(false);
  const [seed, setSeed] = useState("");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const pending = user.key_state === "pending" || !user.has_key;

  const mutation = useMutation({
    mutationFn: () => userApi.regenerateKey(user.id, seed || undefined),
    onSuccess: () => {
      message.success(pending ? `已为 ${user.username} 补发 key` : `${user.username} 的 key 已重签`);
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setOpen(false);
      setSeed("");
    },
    onError: (error) => {
      message.error(error instanceof ApiError ? error.message : "操作失败，请稍后重试");
    },
  });

  return (
    <>
      <Button size="small" danger={!pending} onClick={() => setOpen(true)}>
        {pending ? "补发密钥" : "重签密钥"}
      </Button>
      <Modal
        title={pending ? `补发密钥 · ${user.username}` : `重签密钥 · ${user.username}`}
        open={open}
        okText="确认重签"
        cancelText="取消"
        confirmLoading={mutation.isPending}
        onOk={() => mutation.mutate()}
        onCancel={() => {
          // 成功路径才会清空；取消后重开不得残留上次输入的 seed。
          setOpen(false);
          setSeed("");
        }}
        destroyOnHidden
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="旧 key 立即失效，所有设备上的 ovcli 都需要重新配置。"
        />
        <Collapse
          destroyOnHidden
          items={[
            {
              key: "advanced",
              label: "高级选项",
              children: (
                <Form layout="vertical">
                  <Form.Item label="Seed（可选）" extra="同 seed 可确定性重建密钥">
                    <Input
                      maxLength={256}
                      autoComplete="off"
                      value={seed}
                      onChange={(e) => setSeed(e.target.value)}
                    />
                  </Form.Item>
                </Form>
              ),
            },
          ]}
        />
      </Modal>
    </>
  );
}
