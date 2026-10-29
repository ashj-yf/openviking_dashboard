import { useQuery } from "@tanstack/react-query";
import { Tooltip } from "antd";
import { getHealth } from "@/api/health";
import { qk } from "@/api/query-keys";

type Tone = "green" | "gold" | "red";

const COLOR: Record<Tone, string> = {
  green: "#52c41a",
  gold: "#faad14",
  red: "#ff4d4f",
};

export function HealthDot() {
  const { data, isError } = useQuery({
    queryKey: qk.health,
    queryFn: ({ signal }) => getHealth(signal),
    refetchInterval: 30_000,
    retry: false,
  });

  let tone: Tone;
  let label: string;
  if (isError || !data) {
    tone = "red";
    label = "无法连接服务器";
  } else if (!data.db) {
    tone = "red";
    label = "本地数据库异常";
  } else if (!data.openviking) {
    tone = "gold";
    label = "OpenViking 连接异常（本地功能可用）";
  } else {
    tone = "green";
    label = `系统正常（版本 ${data.version ?? "未知"}）`;
  }

  return (
    <Tooltip title={label}>
      <span
        role="img"
        aria-label={label}
        style={{
          display: "inline-block",
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: COLOR[tone],
        }}
      />
    </Tooltip>
  );
}
