import { useEffect, useState } from "react";
import { Button, Card, Input, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { qk } from "@/api/query-keys";
import { tenantApi, type TenantListItem } from "@/api/tenants";
import { fmtDateTime } from "@/utils/datetime";
import { CreateTenantModal } from "./components/CreateTenantModal";
import { DeleteTenantModal } from "./components/DeleteTenantModal";
import { SyncReportModal } from "./components/SyncReportModal";

export function TenantListPage() {
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setQ(draft.trim()), 300);
    return () => clearTimeout(timer);
  }, [draft]);

  const { data, isLoading } = useQuery({
    queryKey: qk.tenants(q),
    queryFn: () => tenantApi.list(q || undefined),
  });

  const columns: ColumnsType<TenantListItem> = [
    {
      title: "团队 ID",
      dataIndex: "account_id",
      render: (value: string, record) => <Link to={`/tenants/${record.id}`}>{value}</Link>,
    },
    { title: "显示名", dataIndex: "display_name", render: (v: string | null) => v ?? "—" },
    { title: "初始管理员", dataIndex: "admin_user_id" },
    { title: "用户数", dataIndex: "user_count", width: 90 },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string | null) => fmtDateTime(v),
    },
    {
      title: "操作",
      key: "actions",
      width: 200,
      render: (_, record) => (
        <Space>
          <Link to={`/tenants/${record.id}`}>
            <Button size="small">详情</Button>
          </Link>
          <SyncReportModal tenant={record} />
          <DeleteTenantModal tenant={record} />
        </Space>
      ),
    },
  ];

  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        团队管理
      </Typography.Title>
      <Card
        extra={
          <Space>
            <Input.Search
              allowClear
              placeholder="搜索团队 ID / 显示名 / 管理员"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              style={{ width: 280 }}
            />
            <Button
              type="primary"
              aria-label="新建团队"
              icon={<PlusOutlined />}
              onClick={() => setCreateOpen(true)}
            >
              新建团队
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          loading={isLoading}
          columns={columns}
          dataSource={data ?? []}
          pagination={false}
        />
      </Card>
      <CreateTenantModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </>
  );
}
