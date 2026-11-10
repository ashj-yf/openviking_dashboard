import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";
import { resetHealthMock } from "@mocks/domains/health";
import { resetTenantsMock } from "@mocks/domains/tenants";
import { resetUsersMock } from "@mocks/domains/users";
import {
  PLAIN_CREDENTIAL_KEY,
  ROTATED_CREDENTIAL_KEY,
  getCredentialRequests,
  makeCredential,
  resetCredentialsMock,
  setCredentialError,
} from "@mocks/domains/credentials";

// 可选注入凭证视图：默认 makeCredential()；空态用例传 has_key:false 夹具，
// 避免 renderAliceAt 内部重置把夹具覆盖回默认值。
function renderAliceAt(view: ReturnType<typeof makeCredential> | null = null) {
  localStorage.setItem("ov-dashboard-token", "jwt-alice");
  resetAuthMock(
    makeMe({ id: 3, username: "alice", role: "user", tenant_id: 1, account_id: "acme", ov_user_id: "alice", has_ov_key: true }),
  );
  resetHealthMock();
  resetTenantsMock([]);
  resetUsersMock([]);
  resetCredentialsMock(view);
  return renderWithProviders(<AppRoutes />, { route: "/credentials" });
}

// jsdom 的 navigator.clipboard 是只读 getter，Object.assign 会抛 TypeError，须用 defineProperty 替换；
// 且必须晚于 userEvent.setup()——setup 会用自己的剪贴板 stub 覆盖 navigator.clipboard。
function stubClipboard(writeText: (text: string) => Promise<void>): void {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
}

describe("CredentialsPage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("默认展示打码视图：端点/账户/OV ID/提示位可见，明文不出现", async () => {
    renderAliceAt();
    expect(await screen.findByText("https://ov.example.com")).toBeInTheDocument();
    expect(screen.getByText("acme")).toBeInTheDocument();
    // 布局头部当前用户与 OV 用户 ID 各渲染一份 alice，故取 all 变体（同 T6/T7）。
    expect(screen.getAllByText("alice")).not.toHaveLength(0);
    expect(screen.getByText("ovk-a************wxyz")).toBeInTheDocument();
    expect(screen.getByText("2026-10-29 08:00")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(PLAIN_CREDENTIAL_KEY);
  });

  it("点显示调用 reveal 取明文并展示；隐藏不再发请求", async () => {
    const user = userEvent.setup();
    renderAliceAt();
    await screen.findByText("ovk-a************wxyz");

    // 带图标按钮的可访问名含图标 aria-label 前缀（如 "eye 显示明文"），故用子串匹配。
    await user.click(screen.getByRole("button", { name: /显示明文/ }));
    await waitFor(() => expect(screen.getByText(PLAIN_CREDENTIAL_KEY)).toBeInTheDocument());
    expect(getCredentialRequests("POST").filter((r) => r.url.includes("reveal"))).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: /隐藏明文/ }));
    expect(screen.getByText("ovk-a************wxyz")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(PLAIN_CREDENTIAL_KEY);
    expect(getCredentialRequests("POST")).toHaveLength(1);
  }, 30000);

  it("复制 Key 走 copy 端点并把明文写入剪贴板", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    stubClipboard(writeText);
    renderAliceAt();
    await screen.findByText("ovk-a************wxyz");

    await user.click(screen.getByRole("button", { name: /复制 Key/ }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(PLAIN_CREDENTIAL_KEY));
    expect(getCredentialRequests("POST").some((r) => r.url.includes("copy"))).toBe(true);
  }, 30000);

  it("剪贴板失败时给出错误提示且不假装成功", async () => {
    const writeText = vi.fn().mockRejectedValueOnce(new Error("denied"));
    const user = userEvent.setup();
    stubClipboard(writeText);
    renderAliceAt();
    await screen.findByText("ovk-a************wxyz");

    await user.click(screen.getByRole("button", { name: /复制 Key/ }));
    expect(await screen.findByText("复制失败，请手动选择文本复制")).toBeInTheDocument();
  }, 30000);

  it("自助重签：强提示后请求 regenerate，新明文直接展示且旧 key 失效告警", async () => {
    const user = userEvent.setup();
    renderAliceAt();
    await screen.findByText("ovk-a************wxyz");

    await user.click(screen.getByRole("button", { name: /重签 Key/ }));
    expect(
      await screen.findByText(/旧 key 立即失效，所有设备上的 ovcli 都需要重新配置/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认重签" }));

    await waitFor(() =>
      expect(getCredentialRequests("POST").some((r) => r.url.includes("regenerate"))).toBe(true),
    );
    const regenerated = getCredentialRequests("POST").find((r) => r.url.includes("regenerate"))!;
    expect(regenerated.body).toEqual({ seed: null });
    expect(await screen.findByText(ROTATED_CREDENTIAL_KEY)).toBeInTheDocument();
    expect(screen.getByText("旧 key 已失效，请重新配置所有设备")).toBeInTheDocument();
  }, 30000);

  it("未留存 key 时显示联系管理员空态，不出现显示/复制/重签按钮", async () => {
    renderAliceAt(
      makeCredential({ has_key: false, key_masked: null, key_hint: null, key_synced_at: null }),
    );
    expect(await screen.findByText(/尚未获取到 key，请联系管理员补发/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /显示明文/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /复制 Key/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /重签 Key/ })).toBeNull();
  }, 30000);

  it("ovcli 指引含两种配置方式、验证命令与常见错误", async () => {
    renderAliceAt();
    await screen.findByText("ovk-a************wxyz");
    expect(screen.getByText("ov config", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/~\/\.openviking\/ovcli\.conf/)).toBeInTheDocument();
    expect(screen.getByText("ov health")).toBeInTheDocument();
    expect(screen.getByText(/root key 访问数据面会返回 403/)).toBeInTheDocument();
    expect(screen.getByText(/端点末尾不要带/)).toBeInTheDocument();
  });

  it("复制完整配置写入含端点与明文 key 的 JSON，且只调用 copy 端点", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    stubClipboard(writeText);
    renderAliceAt();
    await screen.findByText("ovk-a************wxyz");

    await user.click(screen.getByRole("button", { name: /复制完整配置/ }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const written = String(writeText.mock.calls[0][0]);
    expect(JSON.parse(written)).toEqual({
      url: "https://ov.example.com",
      api_key: PLAIN_CREDENTIAL_KEY,
    });
  }, 30000);

  it("复制完整配置遇后端业务错误时展示 detail 原文而非本地兜底文案", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    stubClipboard(writeText);
    renderAliceAt();
    await screen.findByText("ovk-a************wxyz");
    // 注入须在 renderAliceAt 之后：resetCredentialsMock 会清空 actionError。
    setCredentialError("copy", 409, { detail: "key 已被重签，请刷新后重试" });

    await user.click(screen.getByRole("button", { name: /复制完整配置/ }));
    expect(await screen.findByText("key 已被重签，请刷新后重试")).toBeInTheDocument();
    expect(screen.queryByText("复制失败，请手动选择文本复制")).toBeNull();
    expect(writeText).not.toHaveBeenCalled();
  }, 30000);

  it("密钥泄漏扫描：列表页与未揭示的凭证页任何位置都不含明文 key", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-admin");
    resetAuthMock(makeMe({ role: "admin" }));
    resetHealthMock();
    resetTenantsMock();
    resetUsersMock();
    resetCredentialsMock();

    const { unmount } = renderWithProviders(<AppRoutes />, { route: "/users" });
    await screen.findAllByText("alice");
    expect(document.body.textContent).not.toContain(PLAIN_CREDENTIAL_KEY);
    expect(document.body.textContent).not.toContain(ROTATED_CREDENTIAL_KEY);
    unmount();

    localStorage.setItem("ov-dashboard-token", "jwt-alice");
    resetAuthMock(
      makeMe({ id: 3, username: "alice", role: "user", tenant_id: 1, account_id: "acme", ov_user_id: "alice", has_ov_key: true }),
    );
    renderWithProviders(<AppRoutes />, { route: "/credentials" });
    await screen.findByText("ovk-a************wxyz");
    expect(document.body.textContent).not.toContain(PLAIN_CREDENTIAL_KEY);
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i)!;
      expect(localStorage.getItem(key)).not.toContain(PLAIN_CREDENTIAL_KEY);
    }
  }, 30000);
});
