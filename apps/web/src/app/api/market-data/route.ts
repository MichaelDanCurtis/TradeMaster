import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const symbol = (url.searchParams.get("symbol") ?? "NVDA").trim().toUpperCase();

  if (!/^[A-Z0-9.-]{1,12}$/.test(symbol)) {
    return NextResponse.json({ error: "Invalid symbol" }, { status: 400 });
  }

  return NextResponse.json(
    {
      error:
        "Webull market-data credentials are not configured yet. Wealth Agents is using simulated private-office market context until Webull OpenAPI keys are added.",
      provider: "webull",
      symbol
    },
    {
      headers: {
        "Cache-Control": "no-store"
      },
      status: 503
    }
  );
}
