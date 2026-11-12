export type DetailTab = "catalyst" | "charts" | "company";
export type Dock = "left" | "right" | "bottom";
export type DeskLayout = { dock: Dock; width: number; tab: DetailTab };
export const DEFAULT_DESK: DeskLayout = {
  dock: "right",
  width: 420,
  tab: "catalyst",
};
export const DESK_KEY = "trademaster.market-pulse.desk.v1";
export function readDesk(value: string | null): DeskLayout {
  try {
    const raw = JSON.parse(value ?? "null");
    return {
      dock: ["left", "right", "bottom"].includes(raw?.dock)
        ? raw.dock
        : "right",
      width:
        typeof raw?.width === "number" && Number.isFinite(raw.width)
          ? Math.max(320, Math.min(680, raw.width))
          : 420,
      tab: ["catalyst", "charts", "company"].includes(raw?.tab)
        ? raw.tab
        : "catalyst",
    };
  } catch {
    return { ...DEFAULT_DESK };
  }
}
export type SecurityIdentity = {
  symbol: string;
  name: string | null;
  exchange?: string | null;
  security_type?: string;
  status: string;
  source: string;
  retrieved_at: string;
};
export type ReportedHolder = {
  name: string;
  shares: number;
  percent?: number | null;
  reported_at: string;
  position?: string | null;
  holding_type?: string;
};
export type CompanyProfile = {
  symbol: string;
  status: string;
  retrieved_at: string;
  name: string | null;
  description?: string;
  sector?: string | null;
  industry?: string | null;
  country?: string | null;
  website?: string | null;
  parent?: string | null;
  fund_family?: string | null;
  currency?: string | null;
  security_type?: string | null;
  insider_percent?: number | null;
  institutional_percent?: number | null;
  holders: ReportedHolder[];
  insiders: ReportedHolder[];
  metrics: Record<string, number | null>;
  ownership_note?: string;
  profile_url?: string;
  holders_url?: string;
  gaps: string[];
};
