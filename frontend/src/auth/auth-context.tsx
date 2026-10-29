import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { authExpired } from "@/api/client";
import * as authApi from "@/api/auth";
import type { Me } from "@/api/auth";
import { qk } from "@/api/query-keys";
import { clearToken, getToken, setToken } from "@/auth/token-store";

interface AuthContextValue {
  me: Me | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<{ role: string }>;
  logout: () => Promise<void>;
  changePassword: (oldPassword: string, newPassword: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const meQuery = useQuery({
    queryKey: qk.me,
    queryFn: authApi.fetchMe,
    enabled: getToken() !== null,
    retry: false,
  });

  const loginMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      authApi.login({ username, password }),
  });

  // 401 事件触发时复位会话状态：client 只清了持久化 token，还需清掉内存中的 me，
  // 否则 LoginPage 会把残留会话弹回 "/" 形成弹跳。
  useEffect(() => {
    const onExpired = () => {
      clearToken();
      queryClient.removeQueries({ queryKey: qk.me });
    };
    authExpired.addEventListener("expired", onExpired);
    return () => authExpired.removeEventListener("expired", onExpired);
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({
      me: meQuery.data ?? null,
      // 只有"本地有 token 且正在拉 /me"才算引导加载；查询失败不算无限加载
      isLoading: getToken() !== null && meQuery.isLoading,
      login: async (username, password) => {
        const token = await loginMutation.mutateAsync({ username, password });
        setToken(token.access_token);
        await queryClient.invalidateQueries({ queryKey: qk.me });
        return { role: token.role };
      },
      logout: async () => {
        try {
          await authApi.logout();
        } finally {
          clearToken();
          queryClient.clear();
        }
      },
      changePassword: async (oldPassword, newPassword) => {
        await authApi.changePassword({ old_password: oldPassword, new_password: newPassword });
        // 立即更新缓存中的门禁位，避免 invalidate 的 refetch 窗口内被 ForceChangeGate 弹回；
        // invalidate 兜底同步服务端其余字段。
        queryClient.setQueryData(qk.me, (old: Me | undefined) =>
          old ? { ...old, must_change_password: false } : old,
        );
        await queryClient.invalidateQueries({ queryKey: qk.me });
      },
    }),
    [meQuery.data, meQuery.isLoading, loginMutation, queryClient],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return context;
}
