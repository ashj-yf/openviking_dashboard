import React from "react";
import ReactDOM from "react-dom/client";
import { StyleProvider as AntdRegistry } from "@ant-design/cssinjs";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "@/App";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

async function bootstrap(): Promise<void> {
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK !== "false") {
    const { worker } = await import("@mocks/browser");
    await worker.start({ onUnhandledRequest: "error" });
  }
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <AntdRegistry>
        <ConfigProvider locale={zhCN} button={{ autoInsertSpace: false }}>
          <AntApp>
            <QueryClientProvider client={queryClient}>
              <App />
            </QueryClientProvider>
          </AntApp>
        </ConfigProvider>
      </AntdRegistry>
    </React.StrictMode>,
  );
}

void bootstrap();
