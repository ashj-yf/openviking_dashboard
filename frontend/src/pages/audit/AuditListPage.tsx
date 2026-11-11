import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Input,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { Dayjs } from "dayjs";
import { useQuery } from "@tanstack/react-query";
import { auditApi, type AuditListParams, type AuditLog } from "@/api/audit";
import { qk } from "@/api/query-keys";
import { useAuth } from "@/auth/auth-context";
import { fmtDateTime } from "@/utils/datetime";
import { JsonDrawer } from "@/pages/tenants/components/JsonDrawer";

const INITIAL_FILTERS: AuditListParams = {
  action: null,
  actor: null,
  range: null,
  page: 1,
  pageSize: 20,
};

/** action 域筛选项：后端按前缀匹配（audit_service.list_logs startswith），空串表示全部。 */
const ACTION_OPTIONS = [
  { value: "", label: "全部" },
  { value: "auth.", label: "auth." },
  { value: "tenant.", label: "tenant." },
  { value: "user.", label: "user." },
  { value: "key.", label: "key." },
  { value: "ldap.", label: "ldap." },
];

/** JsonDrawer 同款 pre 样式：本地 detail 与 OV 原始 JSON 共用。 */
const PRE_STYLE = {
  background: "#fafafa",
  border: "1px solid #f0f0f0",
  borderRadius: 6,
  padding: 12,
  overflow: "auto",
} as const;

type RangeValue = [Dayjs, Dayjs] | null;

function targetText(record: AuditLog): string {
  return [record.target_type, record.target_id].filter(Boolean).join(":") || "—";
}

/** 本平台审计：草稿筛选 + 显式查询提交；受控分页由 Table onChange 直接驱动重查。 */
function LocalAuditSection() {
  const [filters, setFilters] = useState<AuditListParams>(INITIAL_FILTERS);
  const [draftAction, setDraftAction] = useState("");
  const [draftActor, setDraftActor] = useState("");
  const [draftRange, setDraftRange] = useState<RangeValue>(null);
  const [current, setCurrent] = useState<AuditLog | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.auditLogs(filters),
    queryFn: () => auditApi.list(filters),
  });

  const applyFilters = () => {
    setFilters((prev) => ({
      action: draftAction === "" ? null : draftAction,
      actor: draftActor.trim() || null,
      range: draftRange ? [draftRange[0].toISOString(), draftRange[1].toISOString()] : null,
      page: 1,
      pageSize: prev.pageSize,
    }));
  };

  const resetFilters = () => {
    setDraftAction("");
    setDraftActor("");
    setDraftRange(null);
    setFilters((prev) => ({ ...INITIAL_FILTERS, pageSize: prev.pageSize }));
  };

  const columns: ColumnsType<AuditLog> = [
    {
      title: "时间",
      dataIndex: "created_at",
      width: 170,
      render: (value: string) => fmtDateTime(value),
    },
    { title: "操作人", dataIndex: "actor_name" },
    { title: "动作", dataIndex: "action", render: (value: string) => <Tag>{value}</Tag> },
    { title: "目标", key: "target", render: (_, record) => targetText(record) },
    { title: "IP", dataIndex: "ip", render: (value: string | null) => value ?? "—" },
    {
      title: "操作",
      key: "actions",
      width: 90,
      render: (_, record) => (
        <Button size="small" onClick={() => setCurrent(record)}>
          详情
        </Button>
      ),
    },
  ];

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            allowClear
            style={{ width: 140 }}
            value={draftAction}
            onChange={(value: string | undefined) => setDraftAction(value ?? "")}
            options={ACTION_OPTIONS}
          />
          <Input
            allowClear
            style={{ width: 180 }}
            placeholder="操作人"
            value={draftActor}
            onChange={(e) => setDraftActor(e.target.value)}
          />
          <DatePicker.RangePicker
            showTime
            value={draftRange}
            onChange={(values) =>
              setDraftRange(values && values[0] && values[1] ? [values[0], values[1]] : null)
            }
          />
          <Button type="primary" onClick={applyFilters}>
            查询
          </Button>
          <Button onClick={resetFilters}>重置</Button>
        </Space>
      </Card>
      {/* 查询失败必须显式呈错，不能以空表假装成功；列表级错误用页面内 Alert（项目约定不用 message）。 */}
      {isError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={error.message}
          action={
            <Button size="small" danger onClick={() => refetch()}>
              重试
            </Button>
          }
        />
      )}
      <Table
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={data?.items ?? []}
        pagination={{
          // 全库首个受控分页：current/pageSize/total 完全由服务端响应驱动，
          // onChange 写回 filters（queryKey 含 page/pageSize）从而触发重查。
          current: data?.page ?? filters.page,
          pageSize: data?.page_size ?? filters.pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          onChange: (page, pageSize) => setFilters((prev) => ({ ...prev, page, pageSize })),
        }}
      />
      <Drawer
        open={current !== null}
        title={current ? `审计详情 #${current.id}` : "审计详情"}
        width={560}
        onClose={() => setCurrent(null)}
      >
        {current && (
          <>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="操作人">{current.actor_name}</Descriptions.Item>
              <Descriptions.Item label="动作">{current.action}</Descriptions.Item>
              <Descriptions.Item label="目标">{targetText(current)}</Descriptions.Item>
              <Descriptions.Item label="IP">{current.ip ?? "—"}</Descriptions.Item>
              <Descriptions.Item label="时间">{fmtDateTime(current.created_at)}</Descriptions.Item>
            </Descriptions>
            <Typography.Title level={5} style={{ marginTop: 16 }}>
              detail
            </Typography.Title>
            {current.detail ? (
              <pre style={PRE_STYLE}>{JSON.stringify(current.detail, null, 2)}</pre>
            ) : (
              <Typography.Text type="secondary">无详情</Typography.Text>
            )}
          </>
        )}
      </Drawer>
    </>
  );
}

/** OV 审计透传：唯一数据源即 OV，失败为非 200 直接呈错并可重试（不经降级分节）。 */
function OvAuditSection() {
  const [jsonOpen, setJsonOpen] = useState(false);
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.auditOv,
    queryFn: () => auditApi.listOv(),
  });

  return (
    <Card>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="OV 侧审计原始数据，字段随真机抓包固化"
      />
      {isError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={error.message}
          action={
            <Button size="small" danger onClick={() => refetch()}>
              重试
            </Button>
          }
        />
      )}
      {isLoading ? (
        <Spin />
      ) : isError ? null : (
        <>
          <pre style={PRE_STYLE}>{JSON.stringify(data, null, 2)}</pre>
          <Button style={{ marginTop: 12 }} onClick={() => setJsonOpen(true)}>
            查看完整 JSON
          </Button>
        </>
      )}
      <JsonDrawer
        open={jsonOpen}
        title="OV 审计原始 JSON"
        value={data ?? null}
        onClose={() => setJsonOpen(false)}
      />
    </Card>
  );
}

export function AuditListPage() {
  const { me } = useAuth();
  const [activeKey, setActiveKey] = useState("local");
  // OV Tab 仅 admin：后端对 team_admin 403，前端不渲染该 Tab 是体验层双保险。
  const items = [
    {
      key: "local",
      // team_admin 的数据经后端强制收窄为本团队（AUD-3），标签按角色呈现避免「全平台」误判。
      label: me?.role === "admin" ? "本平台审计" : "本团队审计",
      children: <LocalAuditSection />,
    },
    ...(me?.role === "admin"
      ? [{ key: "ov", label: "OV 审计", children: <OvAuditSection /> }]
      : []),
  ];
  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        审计日志
      </Typography.Title>
      <Tabs activeKey={activeKey} items={items} onChange={setActiveKey} />
    </>
  );
}
