import { useState } from "react";
import { Alert, App, Button, Checkbox, Collapse, Form, Input, Modal } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { userApi, type UserListItem, type UserResetPasswordBody } from "@/api/users";

export function ResetPasswordModal({ user }: { user: UserListItem }) {
  const [open, setOpen] = useState(false);
  const [regenerate, setRegenerate] = useState(false);
  const [topError, setTopError] = useState<string | null>(null);
  const [form] = Form.useForm<UserResetPasswordBody>();
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (body: UserResetPasswordBody) => userApi.resetPassword(user.id, body),
    onSuccess: () => {
      message.success(`已重置 ${user.username} 的登录密码`);
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setOpen(false);
      form.resetFields();
      setRegenerate(false);
    },
    onError: (error) => {
      setTopError(error instanceof ApiError ? error.message : "重置失败，请稍后重试");
    },
  });

  return (
    <>
      <Button size="small" onClick={() => setOpen(true)}>
        重置密码
      </Button>
      <Modal
        title={`重置密码 · ${user.username}`}
        open={open}
        okText="确认重置"
        cancelText="取消"
        confirmLoading={mutation.isPending}
        onOk={() => form.submit()}
        onCancel={() => {
          // 成功路径才会重置状态；取消后重开不得残留勾选联动与上次错误。
          setOpen(false);
          setRegenerate(false);
          setTopError(null);
        }}
        destroyOnHidden
      >
        {topError && <Alert type="error" showIcon style={{ marginBottom: 16 }} message={topError} />}
        <Form
          form={form}
          layout="vertical"
          initialValues={{ regenerate_key: false }}
          onFinish={(values) =>
            mutation.mutate({
              new_password: values.new_password,
              regenerate_key: regenerate,
              seed: regenerate ? values.seed || null : null,
            })
          }
        >
          <Form.Item
            label="新密码"
            name="new_password"
            rules={[
              { required: true, message: "请输入新密码" },
              { min: 8, max: 128, message: "密码长度需为 8-128 位" },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="regenerate_key" valuePropName="checked" style={{ marginBottom: 8 }}>
            <Checkbox
              checked={regenerate}
              onChange={(e) => setRegenerate(e.target.checked)}
            >
              同时作废并重新生成其 OpenViking key（旧 key 立即失效）
            </Checkbox>
          </Form.Item>
          {regenerate && (
            <Collapse
              destroyOnHidden
              items={[
                {
                  key: "advanced",
                  label: "高级选项",
                  children: (
                    <Form.Item label="Seed（可选）" name="seed">
                      <Input maxLength={256} autoComplete="off" />
                    </Form.Item>
                  ),
                },
              ]}
            />
          )}
        </Form>
      </Modal>
    </>
  );
}
