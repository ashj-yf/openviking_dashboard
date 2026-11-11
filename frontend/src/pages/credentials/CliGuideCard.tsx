import { Alert, App, Button, Card, Typography } from "antd";
import { CopyOutlined } from "@ant-design/icons";
import { useState } from "react";
import { ApiError } from "@/api/client";
import { credentialApi } from "@/api/credentials";

interface Props {
  endpoint: string;
  hasKey: boolean;
}

const CONFIG_TEMPLATE = `{
  "url": "<端点地址>",
  "api_key": "<你的 User Key>"
}`;

export function CliGuideCard({ endpoint, hasKey }: Props) {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);

  async function copyFullConfig() {
    setBusy(true);
    try {
      const revealed = await credentialApi.copyKey();
      try {
        const config = JSON.stringify({ url: endpoint, api_key: revealed.key }, null, 2);
        await navigator.clipboard.writeText(config);
        message.success("已复制完整配置，粘贴到 ~/.openviking/ovcli.conf 即可");
      } catch {
        message.error("复制失败，请手动选择文本复制");
      }
    } catch (error) {
      // 业务错误文案来自后端：{detail} 原样展示（同 CredentialsPage copyKey 范式）。
      message.error(error instanceof ApiError ? error.message : "获取明文失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="ovcli 配置指引" style={{ marginTop: 16 }}>
      <Typography.Paragraph>
        <Typography.Text strong>方式 A：</Typography.Text>
        在终端运行 <Typography.Text code>ov config</Typography.Text>，按交互提示填写端点与 API
        Key，可添加或切换多套配置。
      </Typography.Paragraph>
      <Typography.Paragraph>
        <Typography.Text strong>方式 B：</Typography.Text>
        手工编辑 <Typography.Text code>~/.openviking/ovcli.conf</Typography.Text>，文件为 JSON：
      </Typography.Paragraph>
      <Typography.Paragraph>
        <pre
          style={{
            background: "#fafafa",
            border: "1px solid #f0f0f0",
            borderRadius: 6,
            padding: 12,
          }}
        >
          {CONFIG_TEMPLATE}
        </pre>
      </Typography.Paragraph>
      <Typography.Paragraph>
        <Button
          icon={<CopyOutlined />}
          loading={busy}
          disabled={!hasKey}
          onClick={copyFullConfig}
        >
          复制完整配置
        </Button>
      </Typography.Paragraph>
      <Typography.Paragraph>
        <Typography.Text strong>验证：</Typography.Text>
        终端执行 <Typography.Text code>ov health</Typography.Text>，返回正常即配置完成。
      </Typography.Paragraph>
      <Alert
        type="info"
        showIcon
        message={
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            <li>root key 访问数据面会返回 403：这里必须使用你自己的 User Key，不能使用服务端 root key。</li>
            <li>端点末尾不要带多余的斜杠（使用 {endpoint}，不要追加 /api 或 /）。</li>
          </ul>
        }
      />
    </Card>
  );
}
