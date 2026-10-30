import { NextResponse } from "next/server";

import { fetchProviderBackedMarketSnapshot } from "@/lib/market-data-provider";
import type { MarketRange } from "@/lib/market-data";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const symbol = (url.searchParams.get("symbol") ?? "NVDA").trim().toUpperCase();
  const range = parseRange(url.searchParams.get("range"));

  if (!/^[A-Z0-9.-]{1,12}$/.test(symbol)) {
    return NextResponse.json({ error: "Invalid symbol" }, { status: 400 });
  }

  try {
    const period = url.searchParams.get("period") === "previous" ? "previous" : "current";
    const snapshot = await fetchProviderBackedMarketSnapshot(symbol, range, { period });

    return NextResponse.json(snapshot, {
      headers: {
        "Cache-Control": "no-store"
      }
    });
  } catch (error) {
    return NextResponse.json(
      {
        detail: error instanceof Error ? error.message : "Provider request failed",
        error: "Market data unavailable"
      },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}

function parseRange(value: string | null): MarketRange {
  if (
    value === "1D" ||
    value === "5D" ||
    value === "1M" ||
    value === "YTD" ||
    value === "1Y" ||
    value === "3Y" ||
    value === "5Y" ||
    value === "10Y"
  ) {
    return value;
  }

  return "1M";
}
