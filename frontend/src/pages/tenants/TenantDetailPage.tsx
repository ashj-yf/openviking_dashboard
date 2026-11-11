import { useState } from "react";
import { Alert, Button, Card, Descriptions, Empty, Result, Space, Spin, Typography } from "antd";
import { ArrowLeftOutlined, EditOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { qk } from "@/api/query-keys";
import { tenantApi, type TenantDetail } from "@/api/tenants";
import { fmtDateTime } from "@/utils/datetime";
import { EditTenantModal } from "./components/EditTenantModal";
import { JsonDrawer } from "./components/JsonDrawer";

interface JsonSection {
  key: string;
  title: string;
  value: Record<string, unknown> | null;
}

export function TenantDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const [editOpen, setEditOpen] = useState(false);
  const [drawer, setDrawer] = useState<JsonSection | null>(null);

  const { data, isLoading, error } = useQuery<TenantDetail, ApiError>({
    queryKey: qk.tenant(id),
    queryFn: () => tenantApi.get(id),
    retry: false,
  });

  if (isLoading) return <Spin size="large" />;
  if (error?.status === 404) {
    return (
      <Result
        status="404"
        title="团队不存在"
        subTitle="该团队可能已被删除"
        extra={
          <Link to="/tenants">
            <Button type="primary">返回团队列表</Button>
          </Link>
        }
      />
    );
  }
  if (!data) {
    return (
      <Result
        status="warning"
        title="团队信息加载失败"
        subTitle={error?.message ?? "请稍后重试"}
        extra={
          <Link to="/tenants">
            <Button>返回团队列表</Button>
          </Link>
        }
      />
    );
  }

  const sections: JsonSection[] = [
    { key: "ov_account", title: "账户信息", value: data.ov_account ?? null },
    { key: "configuration", title: "账户配置", value: data.configuration ?? null },
    { key: "settings", title: "账户设置", value: data.settings ?? null },
  ];

  return (
    <>
      <Space style={{ justifyContent: "space-between", width: "100%", marginBottom: 16 }}>
        <Space>
          <Link to="/tenants">
            <Button icon={<ArrowLeftOutlined />}>返回</Button>
          </Link>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {data.account_id}
          </Typography.Title>
        </Space>
        <Space>
          <Button
            aria-label="编辑"
            icon={<EditOutlined />}
            onClick={() => setEditOpen(true)}
          >
            编辑
          </Button>
          <Link to={`/users?tenant_id=${data.id}`}>
            <Button>查看团队用户</Button>
          </Link>
        </Space>
      </Space>

      {data.ov_error && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`OpenViking 信息获取失败：${data.ov_error}`}
        />
      )}

      <Card style={{ marginBottom: 16 }}>
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="团队 ID">{data.account_id}</Descriptions.Item>
          <Descriptions.Item label="显示名">{data.display_name ?? "—"}</Descriptions.Item>
          <Descriptions.Item label="初始管理员">{data.admin_user_id}</Descriptions.Item>
          <Descriptions.Item label="用户数">{data.user_count}</Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            {data.remark ?? "—"}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">{fmtDateTime(data.created_at)}</Descriptions.Item>
          <Descriptions.Item label="最近同步">{fmtDateTime(data.synced_at)}</Descriptions.Item>
        </Descriptions>
      </Card>

      {sections.map((section) => (
        <Card
          key={section.key}
          style={{ marginBottom: 16 }}
          title={section.title}
          extra={
            section.value ? (
              <Button size="small" onClick={() => setDrawer(section)}>
                查看原始 JSON
              </Button>
            ) : undefined
          }
        >
          {section.value ? (
            <Typography.Text type="secondary">
              OpenViking 返回 {Object.keys(section.value).length} 个顶层字段，点击右上角查看原文
            </Typography.Text>
          ) : (
            <Empty description="OpenViking 信息暂不可用" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </Card>
      ))}

      <EditTenantModal open={editOpen} tenant={data} onClose={() => setEditOpen(false)} />
      <JsonDrawer
        open={drawer !== null}
        title={drawer?.title ?? ""}
        value={drawer?.value ?? null}
        onClose={() => setDrawer(null)}
      />
    </>
  );
}
