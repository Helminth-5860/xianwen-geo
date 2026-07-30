import { AntdRegistry } from "@ant-design/nextjs-registry";
import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "显问 GEO 智能体系统",
  description: "显问 GEO 智能体系统 V1",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <AntdRegistry>{children}</AntdRegistry>
      </body>
    </html>
  );
}
