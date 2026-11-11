import { useState } from "react";
import { App, Button, Popconfirm, Select, Space, Switch, Tooltip } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { userApi, type UserListItem } from "@/api/users";
import { useAuth } from "@/auth/auth-context";
import { ProvisionJitModal } from "./ProvisionJitModal";
import { ResetPasswordModal } from "./ResetPasswordModal";
import { RegenerateKeyModal } from "./RegenerateKeyModal";
import { DeleteUserModal } from "./DeleteUserModal";
import { UserSyncModal } from "./UserSyncModal";

export function UserActions({ user }: { user: UserListItem }) {
  const { me } = useAuth();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [provisionOpen, setProvisionOpen] = useState(false);

  const isSelf = me?.id === user.id;
  const isPlatformAdmin = me?.role === "admin";
  const targetIsTeamAdmin = user.role === "team_admin";
  // JIT 未开通行：LDAP 自动建档但尚无团队归属，仅平台 admin 可为其开通（后端 403/409 兜底）。
  const isUnprovisionedJit = user.auth_source === "ldap" && user.tenant_id == null;
  const canManage =
    isPlatformAdmin ||
    (me?.role === "team_admin" &&
      me.tenant_id === user.tenant_id &&
      !targetIsTeamAdmin);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["users"] });

  const roleMutation = useMutation({
    mutationFn: (role: "team_admin" | "user") => userApi.setRole(user.id, role),
    onSuccess: refresh,
    onError: (error) => {
      message.error(error instanceof ApiError ? error.message : "角色设置失败");
      refresh();
    },
  });

  const enabledMutation = useMutation({
    mutationFn: (enabled: boolean) => userApi.setEnabled(user.id, enabled),
    onSuccess: refresh,
    onError: (error) => message.error(error instanceof ApiError ? error.message : "操作失败"),
  });

  if (!canManage) {
    return (
      <Tooltip title="仅平台管理员可操作团队管理员">
        <Space size={4} data-testid="user-actions" data-ready={me ? "true" : "false"}>
          {user.auth_source !== "ldap" && <Button size="small" disabled>重置密码</Button>}
          <Button size="small" disabled>重签密钥</Button>
          <Button size="small" disabled>校准</Button>
        </Space>
      </Tooltip>
    );
  }

  return (
    <Space size={4} wrap data-testid="user-actions" data-ready="true">
      {isPlatformAdmin && isUnprovisionedJit && (
        <Button size="small" type="primary" onClick={() => setProvisionOpen(true)}>
          开通账号
        </Button>
      )}
      {isPlatformAdmin && !isSelf && (
        <Select
          size="small"
          style={{ width: 110 }}
          value={user.role === "team_admin" ? "team_admin" : "user"}
          onChange={(role: "team_admin" | "user") => roleMutation.mutate(role)}
          options={[
            { value: "user", label: "普通用户" },
            { value: "team_admin", label: "团队管理员" },
          ]}
        />
      )}
      {!isSelf && user.auth_source !== "ldap" && <ResetPasswordModal user={user} />}
      {user.ov_user_id && <RegenerateKeyModal user={user} />}
      {!isSelf &&
        (user.is_active ? (
          // 停用不可逆影响登录，走二次确认；Switch 受控且不接 onChange，仅作 Popconfirm 触发器。
          <Popconfirm
            title={`确认停用 ${user.username}？停用后立即无法登录`}
            okText="停用"
            cancelText="取消"
            onConfirm={() => enabledMutation.mutate(false)}
          >
            <Switch size="small" checked checkedChildren="启" unCheckedChildren="停" />
          </Popconfirm>
        ) : (
          // 从停用态恢复无破坏性，直接发送 enable（用例契约：启用直接发送 enable）。
          <Switch
            size="small"
            checked={false}
            checkedChildren="启"
            unCheckedChildren="停"
            onChange={() => enabledMutation.mutate(true)}
          />
        ))}
      {user.ov_user_id && <UserSyncModal user={user} />}
      {!isSelf && <DeleteUserModal user={user} />}
      {isPlatformAdmin && isUnprovisionedJit && (
        <ProvisionJitModal
          open={provisionOpen}
          user={user}
          onClose={() => setProvisionOpen(false)}
        />
      )}
    </Space>
  );
}
