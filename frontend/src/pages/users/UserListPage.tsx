import { useEffect, useState } from "react";
import { Alert, Button, Card, Input, Select, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { qk } from "@/api/query-keys";
import { tenantApi, type TenantListItem } from "@/api/tenants";
import { userApi, type UserListItem } from "@/api/users";
import { useAuth } from "@/auth/auth-context";
import { fmtDateTime } from "@/utils/datetime";
import { ProvisionUserModal } from "./components/ProvisionUserModal";
import { UserActions } from "./components/UserActions";

export function UserListPage() {
  const { me } = useAuth();
  const isAdmin = me?.role === "admin";
  const [searchParams, setSearchParams] = useSearchParams();
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keyword, setKeyword] = useState("");
  const [provisionOpen, setProvisionOpen] = useState(false);

  const tenantIdParam = searchParams.get("tenant_id");
  const tenantFilter = isAdmin && tenantIdParam ? Number(tenantIdParam) : null;

  useEffect(() => {
    const timer = setTimeout(() => setKeyword(keywordDraft.trim()), 300);
    return () => clearTimeout(timer);
  }, [keywordDraft]);

  const tenantsQuery = useQuery({
    queryKey: qk.tenants(""),
    queryFn: () => tenantApi.list(undefined),
    enabled: isAdmin,
  });
  const usersQuery = useQuery({
    queryKey: qk.users({
      tenant_id: isAdmin ? tenantFilter : null,
      keyword: keyword || null,
    }),
    queryFn: () =>
      userApi.list({
        tenant_id: isAdmin ? tenantFilter : null,
        keyword: keyword || null,
      }),
  });

  const columns: ColumnsType<UserListItem> = [
    { title: "用户名", dataIndex: "username" },
    ...(isAdmin
      ? ([{ title: "团队", dataIndex: "account_id", render: (v: string | null) => v ?? "—" }] as ColumnsType<UserListItem>)
      : []),
    { title: "OV 用户 ID", dataIndex: "ov_user_id", render: (v: string | null) => v ?? "—" },
    {
      title: "OV 角色",
      dataIndex: "ov_role",
      render: (v: string | null) => (v === "admin" ? "团队管理员" : v === "user" ? "普通用户" : "—"),
    },
    {
      title: "密钥",
      key: "key",
      render: (_, record) =>
        record.key_state === "pending" || !record.has_key ? (
          <Tag color="orange">待签发</Tag>
        ) : (
          <Tag color="green">已托管</Tag>
        ),
    },
    {
      title: "状态",
      dataIndex: "is_active",
      render: (active: boolean, record) =>
        // 未开通行（无团队归属且非 env 超管，LDAP 自动建档或两段式创建）：专用 Tag 标识，待 admin 开通
        record.tenant_id == null && !record.is_env_admin ? (
          <Tag color="orange">未开通</Tag>
        ) : active ? (
          <Tag color="blue">启用</Tag>
        ) : (
          <Tag>停用</Tag>
        ),
    },
    {
      title: "最近登录",
      dataIndex: "last_login_at",
      width: 170,
      render: (v: string | null) => fmtDateTime(v),
    },
    {
      title: "操作",
      key: "actions",
      width: 360,
      render: (_, record) => <UserActions user={record} />,
    },
  ];

  const tenantOptions = (tenantsQuery.data ?? []).map((t: TenantListItem) => ({
    value: t.id,
    label: t.account_id,
  }));

  return (
    <>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        用户管理
      </Typography.Title>
      <Card
        extra={
          <Space>
            {isAdmin && (
              <Select
                allowClear
                style={{ width: 180 }}
                placeholder="全部团队"
                options={tenantOptions}
                value={tenantFilter}
                onChange={(value: number | undefined) => {
                  const next = new URLSearchParams(searchParams);
                  if (value) next.set("tenant_id", String(value));
                  else next.delete("tenant_id");
                  setSearchParams(next);
                }}
              />
            )}
            <Input.Search
              allowClear
              style={{ width: 240 }}
              placeholder="搜索登录名 / OV 用户 ID"
              value={keywordDraft}
              onChange={(e) => setKeywordDraft(e.target.value)}
            />
            {/* LDAP 模式下本地创建入口整体隐藏：账号来源与 LDAP 单源互斥（admin/team_admin 一致） */}
            {!me?.ldap_enabled && (
              <Button
                type="primary"
                aria-label="开通用户"
                icon={<PlusOutlined />}
                onClick={() => setProvisionOpen(true)}
              >
                开通用户
              </Button>
            )}
          </Space>
        }
      >
        {/* 查询失败必须显式呈错，不能以空表假装成功；重试按钮复用同一查询。 */}
        {usersQuery.isError && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message={usersQuery.error.message}
            action={
              <Button size="small" danger onClick={() => usersQuery.refetch()}>
                重试
              </Button>
            }
          />
        )}
        <Table
          rowKey="id"
          loading={usersQuery.isLoading}
          columns={columns}
          dataSource={usersQuery.data ?? []}
          pagination={false}
        />
      </Card>
      <ProvisionUserModal open={provisionOpen} onClose={() => setProvisionOpen(false)} />
    </>
  );
}
