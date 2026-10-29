import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { AppRoutes } from "@/router/AppRoutes";
import { makeMe, resetAuthMock } from "@mocks/domains/auth";

describe("AppLayout 用户菜单", () => {
  beforeEach(() => {
    localStorage.clear();
    resetAuthMock();
  });

  it("注销调用登出端点、清除 token 并回到登录页", async () => {
    localStorage.setItem("ov-dashboard-token", "jwt-admin");
    resetAuthMock(makeMe({ role: "admin" }));
    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { route: "/" });

    expect(await screen.findByTestId("user-menu")).toBeInTheDocument();
    await user.click(screen.getByTestId("user-menu"));
    await user.click(await screen.findByText("注销"));

    await waitFor(() => expect(screen.getByLabelText("用户名")).toBeInTheDocument());
    expect(localStorage.getItem("ov-dashboard-token")).toBeNull();
  });
});
