import type { Metadata } from "next";
import "./fonts.css";
import "@xyflow/react/dist/style.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "TradeMaster",
  description: "Personal trade desk built on TradingAgents — research, decision, execution."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
