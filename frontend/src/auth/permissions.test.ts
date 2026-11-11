import { can } from "@/auth/permissions";

describe("can() 审计与总览新增权限矩阵", () => {
  it.each([
    ["admin", true],
    ["team_admin", true],
    ["user", false],
    [undefined, false],
  ])("audit:view — role=%s", (role, expected) => {
    expect(can(role, "audit:view")).toBe(expected);
  });

  it.each([
    ["admin", true],
    ["team_admin", true],
    ["user", false],
    [undefined, false],
  ])("overview:view — role=%s", (role, expected) => {
    expect(can(role, "overview:view")).toBe(expected);
  });
});
