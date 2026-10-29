import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { HealthDot } from "@/components/HealthDot";
import { resetHealthMock } from "@mocks/domains/health";

describe("HealthDot", () => {
  afterEach(() => resetHealthMock());

  it("db 与 OpenViking 均正常时显示绿色与版本", async () => {
    resetHealthMock({ db: true, openviking: true, version: "v0.4.14" });
    renderWithProviders(<HealthDot />);
    expect(
      await screen.findByRole("img", { name: "系统正常（版本 v0.4.14）" }),
    ).toBeInTheDocument();
  });

  it("OpenViking 不通但 db 正常时显示黄色降级提示", async () => {
    resetHealthMock({ status: "degraded", db: true, openviking: false });
    renderWithProviders(<HealthDot />);
    expect(
      await screen.findByRole("img", { name: "OpenViking 连接异常（本地功能可用）" }),
    ).toBeInTheDocument();
  });

  it("探针网络失败时显示红色且不白屏", async () => {
    resetHealthMock({ networkError: true });
    renderWithProviders(<HealthDot />);
    expect(
      await screen.findByRole("img", { name: "无法连接服务器" }),
    ).toBeInTheDocument();
  });
});
