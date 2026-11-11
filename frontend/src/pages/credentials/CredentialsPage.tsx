import { useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import {
  EyeInvisibleOutlined,
  EyeOutlined,
  ReloadOutlined,
  CopyOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { qk } from "@/api/query-keys";
import { credentialApi } from "@/api/credentials";
import { fmtDateTime } from "@/utils/datetime";
import { CliGuideCard } from "./CliGuideCard";
import { RegenerateOwnKeyModal } from "./components/RegenerateOwnKeyModal";

export function CredentialsPage() {
  const { message } = App.useApp();
  const [revealed, setRevealed] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [clipboardBusy, setClipboardBusy] = useState(false);

  const viewQuery = useQuery({
    queryKey: qk.credentials,
    queryFn: credentialApi.get,
    retry: false,
  });

  const revealMutation = useMutation({
    mutationFn: credentialApi.revealKey,
    onSuccess: (data) => setRevealed(data.key),
    onError: (error) => message.error(error instanceof ApiError ? error.message : "获取明文失败"),
  });

  const copyMutation = useMutation({
    mutationFn: credentialApi.copyKey,
    onError: (error) => message.error(error instanceof ApiError ? error.message : "获取明文失败"),
  });

  const regenerateMutation = useMutation({
    mutationFn: (seed?: string) => credentialApi.regenerateOwnKey(seed),
    onSuccess: (data) => {
      setRevealed(data.key);
      setModalOpen(false);
      viewQuery.refetch();
      message.warning("旧 key 已失效，请重新配置所有设备", 6);
    },
    onError: (error) => message.error(error instanceof ApiError ? error.message : "重签失败"),
  });

  if (viewQuery.isLoading) return <Spin size="large" />;
  const view = viewQuery.data;
  if (!view) {
    return <Alert type="warning" showIcon message="凭证信息加载失败，请稍后重试" />;
  }

  async function copyKey() {
    setClipboardBusy(true);
    let revealed: { key: string } | null = null;
    try {
      revealed = await copyMutation.mutateAsync();
    } catch {
      // copyMutation 的 onError 已给出后端错误提示
      setClipboardBusy(false);
      return;
    }
    try {
      await navigator.clipboard.writeText(revealed.key);
      message.success("已复制");
    } catch {
      message.error("复制失败，请手动选择文本复制");
    } finally {
      setClipboardBusy(false);
    }
  }

  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        我的凭证
      </Typography.Title>
      <Card>
        {!view.has_key ? (
          <Alert
            type="warning"
            showIcon
            message="尚未获取到 key，请联系管理员补发；补发后即可在此查看并配置 ovcli。"
          />
        ) : (
          <>
            <Descriptions column={1} bordered size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="端点地址">{view.endpoint}</Descriptions.Item>
              <Descriptions.Item label="团队（account_id）">{view.account_id}</Descriptions.Item>
              <Descriptions.Item label="OV 用户 ID">{view.ov_user_id}</Descriptions.Item>
              <Descriptions.Item label="User Key">
                <Space wrap>
                  <Typography.Text code copyable={false} data-testid="key-text">
                    {revealed ?? view.key_masked ?? "—"}
                  </Typography.Text>
                  <Button
                    size="small"
                    icon={revealed ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                    loading={revealMutation.isPending}
                    onClick={() =>
                      revealed ? setRevealed(null) : revealMutation.mutate()
                    }
                  >
                    {revealed ? "隐藏明文" : "显示明文"}
                  </Button>
                  <Button size="small" icon={<CopyOutlined />} loading={clipboardBusy} onClick={copyKey}>
                    复制 Key
                  </Button>
                  <Button size="small" danger icon={<ReloadOutlined />} onClick={() => setModalOpen(true)}>
                    重签 Key
                  </Button>
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="辨识位（hint）">{view.key_hint ?? "—"}</Descriptions.Item>
              <Descriptions.Item label="Seed 生成">
                {view.seed_used ? <Tag color="purple">是</Tag> : <Tag>否</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="最近签发时间">
                {fmtDateTime(view.key_synced_at)}
              </Descriptions.Item>
            </Descriptions>
          </>
        )}
      </Card>
      <CliGuideCard endpoint={view.endpoint} hasKey={view.has_key} />
      <RegenerateOwnKeyModal
        open={modalOpen}
        pending={!view.has_key}
        loading={regenerateMutation.isPending}
        onCancel={() => setModalOpen(false)}
        onConfirm={(seed) => regenerateMutation.mutate(seed)}
      />
    </>
  );
}
