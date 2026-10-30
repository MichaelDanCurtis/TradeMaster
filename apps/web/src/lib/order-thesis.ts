export type OrderThesisStatus = "proposed" | "sent_to_broker";

export type OrderThesisDecisionAction = "accept" | "revise" | "defer" | "escalate" | "reject";

export type OrderThesisInput = {
  action: string;
  catalysts: string[];
  conviction: string;
  horizon: string;
  invalidation: string;
  riskNotes: string;
  sourceReportId?: string | null;
  symbol: string;
  thesisText: string;
};

export type OrderThesisDraft = {
  action: string;
  catalysts: string[];
  conviction: string;
  horizon: string;
  invalidation: string;
  isBrokerOrder: false;
  label: "Advisory research-to-brokerage handoff";
  preview: string;
  riskNotes: string;
  sourceReportId: string | null;
  status: OrderThesisStatus;
  statusFlow: OrderThesisStatus[];
  decisionActions: OrderThesisDecisionAction[];
  summary: string;
  symbol: string;
  thesisText: string;
};

export const orderThesisStatusFlow: OrderThesisStatus[] = ["proposed", "sent_to_broker"];

export const orderThesisDecisionActions: OrderThesisDecisionAction[] = [
  "accept",
  "revise",
  "defer",
  "escalate",
  "reject"
];

export function buildOrderThesisDraft(input: OrderThesisInput): OrderThesisDraft {
  const symbol = normalizeSymbol(input.symbol);
  const action = cleanValue(input.action, "Needs research action");
  const horizon = cleanValue(input.horizon, "Needs investment horizon");
  const conviction = cleanValue(input.conviction, "Needs conviction level");
  const thesisText = cleanValue(input.thesisText, "Needs research thesis text.");
  const invalidation = cleanValue(input.invalidation, "Needs invalidation condition.");
  const riskNotes = cleanValue(input.riskNotes, "Needs risk review notes.");
  const catalysts = normalizeCatalysts(input.catalysts);
  const sourceReportId = input.sourceReportId?.trim() ? input.sourceReportId.trim() : null;
  const summary = [
    `Advisory research-to-brokerage handoff for ${symbol}.`,
    `Research action: ${action}.`,
    `Horizon: ${horizon}.`,
    `Conviction: ${conviction}.`,
    "This is not a broker order and does not submit, route, or place a trade."
  ].join(" ");

  return {
    action,
    catalysts,
    conviction,
    horizon,
    invalidation,
    isBrokerOrder: false,
    label: "Advisory research-to-brokerage handoff",
    preview: [
      "Advisory research-to-brokerage handoff",
      `Symbol: ${symbol}`,
      `Research action: ${action}`,
      `Horizon: ${horizon}`,
      `Conviction: ${conviction}`,
      `Thesis: ${thesisText}`,
      `Catalysts: ${catalysts.join("; ")}`,
      `Invalidation: ${invalidation}`,
      `Risk notes: ${riskNotes}`,
      sourceReportId ? `Source report: ${sourceReportId}` : "Source report: Not linked",
      "Brokerage/execution agents must convert this thesis into an execution intent before any broker review or order entry."
    ].join("\n"),
    riskNotes,
    sourceReportId,
    status: "proposed",
    statusFlow: [...orderThesisStatusFlow],
    decisionActions: [...orderThesisDecisionActions],
    summary,
    symbol,
    thesisText
  };
}

function normalizeSymbol(symbol: string): string {
  const normalized = symbol.trim().toUpperCase();
  return normalized.length > 0 ? normalized : "UNSPECIFIED";
}

function normalizeCatalysts(catalysts: string[]): string[] {
  const normalized = catalysts.map((catalyst) => catalyst.trim()).filter(Boolean);
  return normalized.length > 0 ? normalized : ["Catalysts need broker-review detail."];
}

function cleanValue(value: string, fallback: string): string {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : fallback;
}
