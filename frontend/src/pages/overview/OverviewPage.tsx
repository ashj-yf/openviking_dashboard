import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { overviewApi, type ObserverAggregate, type OverviewSummary } from "@/api/overview";
import { qk } from "@/api/query-keys";
import { useAuth } from "@/auth/auth-context";
import { JsonDrawer } from "@/pages/tenants/components/JsonDrawer";

/** summary 与 observer 双查询共用 30s 轮询（OVR-6 自动刷新）。 */
export const OVERVIEW_REFRESH_INTERVAL_MS = 30_000;

/** observer 组件中文名；原始 key 以次要文本同卡展示，未知 key 兜底显示原值。 */
const COMPONENT_LABELS: Record<string, string> = {
  queue: "队列",
  models: "模型",
  retrieval: "检索",
  system: "系统",
  vikingdb: "VikingDB",
  filesystem: "文件系统",
  lock: "锁",
};

/** ov_health 字段容错读取：键可能缺失或类型漂移，缺失显「—」；latency_ms 数值补 ms 单位。 */
function healthText(health: OverviewSummary["ov_health"], key: string): string {
  const value = health?.[key];
  if (value === null || value === undefined || value === "") return "—";
  if (key === "latency_ms" && typeof value === "number") return `${value} ms`;
  return String(value);
}

function KpiSection({ summary, isAdmin }: { summary: OverviewSummary; isAdmin: boolean }) {
  const span = isAdmin ? 6 : 8;
  return (
    <Row gutter={[16, 16]}>
      {isAdmin && (
        <Col span={span}>
          <Card>
            {/* tenant_count 仅 admin 恒有值；null 属防御分支，显占位不崩。 */}
            <Statistic title="团队数" value={summary.tenant_count ?? "—"} />
          </Card>
        </Col>
      )}
      <Col span={span}>
        <Card>
          <Statistic
            title={isAdmin ? "用户总数" : "本团队用户总数"}
            value={summary.users_total}
          />
        </Card>
      </Col>
      <Col span={span}>
        <Card>
          <Statistic title="启用" value={summary.users_active} />
        </Card>
      </Col>
      <Col span={span}>
        <Card>
          <Statistic title="禁用" value={summary.users_disabled} />
        </Card>
      </Col>
    </Row>
  );
}

function HealthCard({ summary }: { summary: OverviewSummary }) {
  // 连接状态仅由 ov_error 驱动：非空即「OV 未连接」（此时 ov_health/ov_summary 已降级为 null）。
  const connected = !summary.ov_error;
  return (
    <Card
      title="OV 健康"
      style={{ marginTop: 16 }}
      extra={
        <Tag color={connected ? "success" : "error"}>
          {connected ? "已连接" : "OV 未连接"}
        </Tag>
      }
    >
      <Row gutter={16}>
        <Col span={8}>
          <Statistic title="状态" value={healthText(summary.ov_health, "status")} />
        </Col>
        <Col span={8}>
          <Statistic title="版本" value={healthText(summary.ov_health, "version")} />
        </Col>
        <Col span={8}>
          <Statistic title="延迟" value={healthText(summary.ov_health, "latency_ms")} />
        </Col>
      </Row>
      {!connected && (
        <Alert
          type="error"
          showIcon
          style={{ marginTop: 16 }}
          message={summary.ov_error ?? "OV 未连接"}
        />
      )}
    </Card>
  );
}

function OvSummaryCard({
  summary,
  onOpenJson,
}: {
  summary: OverviewSummary;
  onOpenJson: () => void;
}) {
  return (
    <Card title="OV 摘要" style={{ marginTop: 16 }}>
      {summary.ov_summary ? (
        <Button onClick={onOpenJson}>原始 JSON</Button>
      ) : (
        <Typography.Text type="secondary">OV 摘要暂不可用</Typography.Text>
      )}
    </Card>
  );
}

function ObserverSection({
  observer,
  isLoading,
  error,
  onRetry,
  onOpen,
}: {
  observer: ObserverAggregate | null;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
  onOpen: (key: string) => void;
}) {
  return (
    <>
      <Typography.Title level={4} style={{ marginTop: 24 }}>
        OV Observer 组件
      </Typography.Title>
      {/* 聚合接口失败显式呈错，不能以空网格假装成功（同审计页 Alert 先例）。 */}
      {error && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={error}
          action={
            <Button size="small" danger onClick={onRetry}>
              重试
            </Button>
          }
        />
      )}
      {isLoading ? (
        <Spin />
      ) : observer ? (
        <Row gutter={[16, 16]}>
          {Object.entries(observer.components).map(([key, entry]) => (
            <Col span={6} key={key}>
              {/* 点击整卡查看该组件原始 JSON（data 已随聚合返回，无需二次请求）。 */}
              <Card
                size="small"
                hoverable
                title={COMPONENT_LABELS[key] ?? key}
                extra={
                  entry.error ? (
                    <Tooltip title={entry.error ?? undefined}>
                      <Tag color="error">异常</Tag>
                    </Tooltip>
                  ) : entry.data ? (
                    <Tag color="success">正常</Tag>
                  ) : (
                    <Tag>未知</Tag>
                  )
                }
                onClick={() => onOpen(key)}
              >
                <Typography.Text type="secondary">{key}</Typography.Text>
              </Card>
            </Col>
          ))}
        </Row>
      ) : null}
    </>
  );
}

export function OverviewPage() {
  const { me } = useAuth();
  // observer 仅 admin：Permission 类型无 "admin" 成员，can() 不能直判，
  // 与 F2 审计 OV Tab 同款用 role 直判；后端对 team_admin 403，enabled:false 不发起是双保险。
  const isAdmin = me?.role === "admin";
  const [summaryJsonOpen, setSummaryJsonOpen] = useState(false);
  const [observerJsonKey, setObserverJsonKey] = useState<string | null>(null);

  const summaryQuery = useQuery({
    queryKey: qk.overviewSummary,
    queryFn: overviewApi.summary,
    refetchInterval: OVERVIEW_REFRESH_INTERVAL_MS,
  });
  const observerQuery = useQuery({
    queryKey: qk.observer,
    queryFn: overviewApi.observer,
    enabled: isAdmin,
    refetchInterval: OVERVIEW_REFRESH_INTERVAL_MS,
  });

  const summary = summaryQuery.data ?? null;
  const observer = observerQuery.data ?? null;

  const handleRefresh = () => {
    void summaryQuery.refetch();
    if (isAdmin) void observerQuery.refetch();
  };

  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        总览看板
      </Typography.Title>
      <Space style={{ marginBottom: 16 }}>
        <Typography.Text type="secondary">数据每 30 秒自动刷新</Typography.Text>
        <Button icon={<ReloadOutlined />} onClick={handleRefresh}>
          刷新
        </Button>
      </Space>
      {summaryQuery.isError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={summaryQuery.error.message}
          action={
            <Button size="small" danger onClick={() => void summaryQuery.refetch()}>
              重试
            </Button>
          }
        />
      )}
      {summaryQuery.isLoading ? (
        <Spin />
      ) : summary ? (
        <>
          <KpiSection summary={summary} isAdmin={isAdmin} />
          <HealthCard summary={summary} />
          {isAdmin && (
            <OvSummaryCard
              summary={summary}
              onOpenJson={() => setSummaryJsonOpen(true)}
            />
          )}
        </>
      ) : null}
      {isAdmin && (
        <ObserverSection
          observer={observer}
          isLoading={observerQuery.isLoading}
          error={observerQuery.isError ? observerQuery.error.message : null}
          onRetry={() => void observerQuery.refetch()}
          onOpen={setObserverJsonKey}
        />
      )}
      <JsonDrawer
        open={summaryJsonOpen}
        title="OV 摘要原始 JSON"
        value={summary?.ov_summary ?? null}
        onClose={() => setSummaryJsonOpen(false)}
      />
      <JsonDrawer
        open={observerJsonKey !== null}
        title={observerJsonKey ? `Observer · ${observerJsonKey}` : "Observer"}
        value={observerJsonKey ? (observer?.components[observerJsonKey]?.data ?? null) : null}
        onClose={() => setObserverJsonKey(null)}
      />
    </>
  );
}
