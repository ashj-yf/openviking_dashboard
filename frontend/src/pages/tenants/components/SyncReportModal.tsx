import { useState } from "react";
import { App, Button, Descriptions, Modal, Table } from "antd";
import { useMutation } from "@tanstack/react-query";
import type { ColumnsType } from "antd/es/table";
import { ApiError } from "@/api/client";
import { tenantApi, type TenantListItem, type TenantSyncReport } from "@/api/tenants";
import type { Schema } from "@/types/api";

type SyncUserInfo = Schema["SyncUserInfo"];

const userColumns: ColumnsType<SyncUserInfo> = [
  { title: "OV 用户 ID", dataIndex: "ov_user_id" },
  { title: "OV 角色", dataIndex: "ov_role", render: (v: string | null) => v ?? "—" },
  { title: "登录名", dataIndex: "username", render: (v: string | null) => v ?? "—" },
];

export function SyncReportModal({ tenant }: { tenant: TenantListItem }) {
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState<TenantSyncReport | null>(null);
  const { message } = App.useApp();

  const mutation = useMutation({
    mutationFn: () => tenantApi.sync(tenant.id),
    onSuccess: (data) => {
      setReport(data);
      setOpen(true);
    },
    onError: (error) => {
      message.error(error instanceof ApiError ? error.message : "同步失败，请稍后重试");
    },
  });

  return (
    <>
      <Button size="small" loading={mutation.isPending} onClick={() => mutation.mutate()}>
        同步
      </Button>
      <Modal
        title={`同步报告 · ${tenant.account_id}`}
        open={open}
        footer={null}
        width={720}
        onCancel={() => setOpen(false)}
      >
        {report && (
          <>
            <Descriptions column={3} size="small" bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="OpenViking 用户数">{report.ov_user_count}</Descriptions.Item>
              <Descriptions.Item label="本地用户数">{report.local_user_count}</Descriptions.Item>
              <Descriptions.Item label="已匹配">{report.matched}</Descriptions.Item>
            </Descriptions>
            <h4>本地缺失（OpenViking 已存在）</h4>
            <Table
              rowKey="ov_user_id"
              size="small"
              pagination={false}
              columns={userColumns}
              dataSource={report.missing_local}
              locale={{ emptyText: "无差异" }}
            />
            <h4 style={{ marginTop: 16 }}>本地多余（OpenViking 不存在）</h4>
            <Table
              rowKey="ov_user_id"
              size="small"
              pagination={false}
              columns={userColumns}
              dataSource={report.extra_local}
              locale={{ emptyText: "无差异" }}
            />
          </>
        )}
      </Modal>
    </>
  );
}
