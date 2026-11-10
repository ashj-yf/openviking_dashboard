import { useState } from "react";
import { Alert, Collapse, Form, Input, Modal } from "antd";

interface Props {
  open: boolean;
  pending: boolean;
  onCancel: () => void;
  onConfirm: (seed: string | undefined) => void;
  loading: boolean;
}

export function RegenerateOwnKeyModal({ open, pending, onCancel, onConfirm, loading }: Props) {
  const [seed, setSeed] = useState("");
  return (
    <Modal
      title={pending ? "补发我的 key" : "重新生成 key"}
      open={open}
      okText="确认重签"
      cancelText="取消"
      confirmLoading={loading}
      onOk={() => onConfirm(seed || undefined)}
      onCancel={onCancel}
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
  );
}
