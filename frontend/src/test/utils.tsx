import { act, render, type RenderResult } from "@testing-library/react";
import { StyleProvider as AntdRegistry } from "@ant-design/cssinjs";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
}

interface RenderOptions {
  route?: string;
}

export function renderWithProviders(
  ui: ReactElement,
  options: RenderOptions = {},
): RenderResult {
  const queryClient = makeQueryClient();
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <AntdRegistry>
        <ConfigProvider locale={zhCN}>
          <AntApp>
            <QueryClientProvider client={queryClient}>
              <MemoryRouter initialEntries={[options.route ?? "/"]}>
                {children}
              </MemoryRouter>
            </QueryClientProvider>
          </AntApp>
        </ConfigProvider>
      </AntdRegistry>
    );
  }
  return render(ui, { wrapper: Wrapper });
}

/** 推进微任务/定时器一个轮次，等待 MSW 响应与 React Query settle。 */
export async function nextFrame(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}
