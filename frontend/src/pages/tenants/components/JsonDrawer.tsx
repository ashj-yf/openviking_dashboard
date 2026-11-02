import { Drawer, Typography } from "antd";

interface Props {
  open: boolean;
  title: string;
  value: unknown;
  onClose: () => void;
}

export function JsonDrawer({ open, title, value, onClose }: Props) {
  return (
    <Drawer title={title} open={open} width={560} onClose={onClose}>
      <Typography.Paragraph>
        <pre
          style={{
            background: "#fafafa",
            border: "1px solid #f0f0f0",
            borderRadius: 6,
            padding: 12,
            overflow: "auto",
          }}
        >
          {JSON.stringify(value, null, 2)}
        </pre>
      </Typography.Paragraph>
    </Drawer>
  );
}
