import { buildUserMenu } from "@/layouts/AppLayout";

describe("AppLayout 用户菜单", () => {
  it("普通账号包含修改密码入口", () => {
    const items = buildUserMenu(false);
    expect(items?.some((item) => item?.key === "change-password")).toBe(true);
  });

  it("超管账号不提供修改密码入口（密码仅可经 .env 轮换）", () => {
    const items = buildUserMenu(true);
    expect(items?.some((item) => item?.key === "change-password")).toBe(false);
    expect(items?.some((item) => item?.key === "logout")).toBe(true);
  });
});
