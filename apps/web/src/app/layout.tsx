import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TradingAgents UI",
  description: "Local trading research terminal for TradingAgents"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
