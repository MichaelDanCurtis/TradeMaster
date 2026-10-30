import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Serif } from "next/font/google";
import "@xyflow/react/dist/style.css";
import "./globals.css";

// Trade-desk typography: IBM Plex Sans for UI, IBM Plex Serif (italic) for
// room headlines and editorial labels, IBM Plex Mono for numerals. Loaded
// via Next/Font so the fonts self-host at build and ship with zero layout
// shift. CSS reads the family via the `--font-plex-sans`, `--font-plex-serif`,
// and `--font-plex-mono` custom properties below.
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-plex-sans",
  display: "swap"
});

const plexSerif = IBM_Plex_Serif({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-plex-serif",
  display: "swap"
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-mono",
  display: "swap"
});

export const metadata: Metadata = {
  title: "TradeMaster",
  description: "Personal trade desk built on TradingAgents — research, decision, execution."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexSerif.variable} ${plexMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
