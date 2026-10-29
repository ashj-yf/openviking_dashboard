import { clearToken, getToken, setToken } from "@/auth/token-store";

describe("token-store", () => {
  beforeEach(() => localStorage.clear());

  it("未登录时 getToken 返回 null", () => {
    expect(getToken()).toBeNull();
  });

  it("setToken 写入后 getToken 返回同值", () => {
    setToken("jwt-abc");
    expect(localStorage.getItem("ov-dashboard-token")).toBe("jwt-abc");
    expect(getToken()).toBe("jwt-abc");
  });

  it("clearToken 清除登录态", () => {
    setToken("jwt-abc");
    clearToken();
    expect(getToken()).toBeNull();
  });
});
