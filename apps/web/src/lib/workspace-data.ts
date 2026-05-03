export type WorkspaceId = "dashboard" | "research" | "agents" | "transactions" | "historicals";
export type NewsSentiment = "positive" | "neutral" | "negative";
export type AgentConversationType = "agent" | "group" | "platform";
export type NotificationSeverity = "info" | "success" | "warning" | "critical";

export type NewsEvent = {
  id: string;
  symbol: string;
  timestamp: string;
  title: string;
  source: string;
  url: string;
  sentiment: NewsSentiment;
  relevance: number;
  markerLabel: string;
  summary: string;
};

export type AgentConversation = {
  id: string;
  type: AgentConversationType;
  label: string;
  symbol: string | null;
  unreadCount: number;
  lastActivity: string;
  summary: string;
};

export type TransactionPosition = {
  symbol: string;
  quantity: number;
  marketValue: number;
  dayChangePercent: number;
};

export type TransactionOrder = {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  status: "filled" | "pending" | "canceled";
  submittedAt: string;
};

export type TransactionOrderIntent = {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  notional: number;
  limitPrice: number;
  confidence: number;
  requiresApproval: boolean;
  rationale: string;
};

export type TransactionSnapshot = {
  symbol: string;
  mode: "paper";
  portfolioValue: number;
  buyingPower: number;
  positions: TransactionPosition[];
  recentOrders: TransactionOrder[];
  orderIntent: TransactionOrderIntent;
};

export type HistoricalOutcome = {
  symbol: string;
  reportId: string;
  predictionDate: string;
  horizon: string;
  predictedStance: string;
  actualOutcome: string;
  expectedReturn: number;
  actualReturn: number;
  reviewTags: string[];
  notes: string;
};

export type ResearchReport = {
  id: string;
  symbol: string;
  title: string;
  createdAt: string;
  horizon: string;
  stance: "bullish" | "neutral" | "bearish";
  confidence: number;
  summary: string;
  ledgerState: string[];
  riskNotes: string[];
  synthesisSteps: string[];
};

export type TerminalNotification = {
  id: string;
  severity: NotificationSeverity;
  title: string;
  body: string;
  linkedWorkspace: WorkspaceId;
  linkedEntityId?: string;
  ttl?: number;
};

type NewsTemplate = Omit<NewsEvent, "id" | "symbol" | "url">;
type HistoricalTemplate = Omit<HistoricalOutcome, "symbol" | "reportId">;
type ResearchReportTemplate = Omit<ResearchReport, "id" | "symbol" | "title"> & {
  titleTemplate: string;
};

const NEWS_TEMPLATES: NewsTemplate[] = [
  {
    timestamp: "2026-05-02T20:45:00.000Z",
    title: "Datacenter demand revision lifts forward sales model",
    source: "TA Market Desk",
    sentiment: "positive",
    relevance: 99,
    markerLabel: "Demand",
    summary: "Channel checks point to stronger accelerator backlog and improved second-half visibility."
  },
  {
    timestamp: "2026-05-02T19:30:00.000Z",
    title: "Options flow clusters around upside call spreads",
    source: "Derivatives Wire",
    sentiment: "positive",
    relevance: 96,
    markerLabel: "Options",
    summary: "Large premium call-spread activity increased near the weekly high-volume strike band."
  },
  {
    timestamp: "2026-05-02T18:10:00.000Z",
    title: "Supply partner commentary indicates capacity expansion",
    source: "Semiconductor Daily",
    sentiment: "positive",
    relevance: 94,
    markerLabel: "Supply",
    summary: "Packaging capacity plans were reiterated, reducing concern about near-term shipment constraints."
  },
  {
    timestamp: "2026-05-02T16:25:00.000Z",
    title: "Sell-side raises target on sustained AI infrastructure spend",
    source: "Street Notes",
    sentiment: "positive",
    relevance: 91,
    markerLabel: "Target",
    summary: "Updated scenario work assigns more weight to durable hyperscaler capital expenditure."
  },
  {
    timestamp: "2026-05-02T15:05:00.000Z",
    title: "Intraday breadth improves across chip leadership basket",
    source: "Market Pulse",
    sentiment: "positive",
    relevance: 88,
    markerLabel: "Breadth",
    summary: "Sector participation broadened after the opening hour, with mega-cap semis leading volume."
  },
  {
    timestamp: "2026-05-01T21:00:00.000Z",
    title: "Management conference slot added to May calendar",
    source: "Issuer Calendar",
    sentiment: "neutral",
    relevance: 84,
    markerLabel: "Event",
    summary: "Investor relations added a late-May technology conference appearance to the public schedule."
  },
  {
    timestamp: "2026-05-01T19:45:00.000Z",
    title: "Peer earnings highlight strong accelerator attach rates",
    source: "Earnings Monitor",
    sentiment: "positive",
    relevance: 82,
    markerLabel: "Peer",
    summary: "Adjacent supplier results indicated continued demand for high-end compute deployments."
  },
  {
    timestamp: "2026-05-01T18:20:00.000Z",
    title: "Export policy update leaves current quarter assumptions intact",
    source: "Policy Desk",
    sentiment: "neutral",
    relevance: 79,
    markerLabel: "Policy",
    summary: "Initial policy language did not alter the baseline shipment assumptions in the model."
  },
  {
    timestamp: "2026-05-01T16:10:00.000Z",
    title: "Volatility premium compresses after morning reversal",
    source: "Vol Monitor",
    sentiment: "neutral",
    relevance: 76,
    markerLabel: "Vol",
    summary: "Implied volatility fell as spot recovered and put skew normalized from the open."
  },
  {
    timestamp: "2026-05-01T14:55:00.000Z",
    title: "Pre-market note flags support at prior breakout",
    source: "Technical Desk",
    sentiment: "neutral",
    relevance: 74,
    markerLabel: "Support",
    summary: "Price held the prior breakout zone on elevated early volume."
  },
  {
    timestamp: "2026-04-30T21:10:00.000Z",
    title: "Cloud budget survey shows continued AI cluster priority",
    source: "CIO Survey",
    sentiment: "positive",
    relevance: 72,
    markerLabel: "Survey",
    summary: "Respondents kept AI infrastructure at the top of discretionary technology budgets."
  },
  {
    timestamp: "2026-04-30T19:05:00.000Z",
    title: "Inventory commentary stays balanced into quarter close",
    source: "Channel Tracker",
    sentiment: "neutral",
    relevance: 70,
    markerLabel: "Inventory",
    summary: "Distributor checks showed no material inventory build across monitored enterprise channels."
  },
  {
    timestamp: "2026-04-30T17:40:00.000Z",
    title: "Short interest update shows modest covering",
    source: "Positioning Lab",
    sentiment: "positive",
    relevance: 68,
    markerLabel: "Positioning",
    summary: "Borrow data suggests some reduction in crowded short-term hedges."
  },
  {
    timestamp: "2026-04-30T15:15:00.000Z",
    title: "AI server bill of materials estimates edge higher",
    source: "Hardware Ledger",
    sentiment: "positive",
    relevance: 65,
    markerLabel: "BOM",
    summary: "Component mix analysis implies richer accelerator content in new server programs."
  },
  {
    timestamp: "2026-04-29T20:50:00.000Z",
    title: "Regulatory headline creates brief risk-off move",
    source: "Macro Flash",
    sentiment: "negative",
    relevance: 61,
    markerLabel: "Risk",
    summary: "A policy headline pressured semiconductor shares before details narrowed the perceived impact."
  },
  {
    timestamp: "2026-04-29T18:35:00.000Z",
    title: "Dealer gamma map shows resistance near weekly highs",
    source: "Options Desk",
    sentiment: "neutral",
    relevance: 58,
    markerLabel: "Gamma",
    summary: "Open interest concentrations may slow follow-through unless spot clears the upper band."
  },
  {
    timestamp: "2026-04-29T16:00:00.000Z",
    title: "Asia session supplier basket closes mixed",
    source: "Global Tape",
    sentiment: "neutral",
    relevance: 55,
    markerLabel: "Asia",
    summary: "Overnight supplier performance was mixed, leaving limited read-through for the US session."
  },
  {
    timestamp: "2026-04-28T21:20:00.000Z",
    title: "Analyst debate centers on margin durability",
    source: "Research Roundup",
    sentiment: "neutral",
    relevance: 52,
    markerLabel: "Margins",
    summary: "Model updates focused on mix, memory costs, and whether gross margin assumptions are conservative."
  },
  {
    timestamp: "2026-04-28T19:10:00.000Z",
    title: "ETF rebalance preview implies passive demand",
    source: "Flow Desk",
    sentiment: "positive",
    relevance: 49,
    markerLabel: "ETF",
    summary: "Preliminary rebalance estimates indicate incremental passive buying later in May."
  },
  {
    timestamp: "2026-04-28T15:45:00.000Z",
    title: "Profit-taking accelerates after multi-day advance",
    source: "Tape Reader",
    sentiment: "negative",
    relevance: 46,
    markerLabel: "Profit",
    summary: "Volume increased during a late-morning pullback following several strong sessions."
  }
];

const HISTORICAL_TEMPLATES: HistoricalTemplate[] = [
  {
    predictionDate: "2026-01-12",
    horizon: "20 trading days",
    predictedStance: "constructive",
    actualOutcome: "outperformed semiconductor basket",
    expectedReturn: 5.8,
    actualReturn: 7.1,
    reviewTags: ["directionally-correct", "underestimated-magnitude"],
    notes: "Demand checks and breadth signals both confirmed, but the move arrived faster than expected."
  },
  {
    predictionDate: "2026-02-06",
    horizon: "10 trading days",
    predictedStance: "neutral",
    actualOutcome: "range-bound with elevated volatility",
    expectedReturn: 1.2,
    actualReturn: 0.6,
    reviewTags: ["directionally-correct", "volatility-captured"],
    notes: "The stance avoided chasing strength while volatility stayed above the desk threshold."
  },
  {
    predictionDate: "2026-03-18",
    horizon: "30 trading days",
    predictedStance: "constructive",
    actualOutcome: "initial drawdown followed by higher close",
    expectedReturn: 4.4,
    actualReturn: 3.2,
    reviewTags: ["directionally-correct", "timing-early"],
    notes: "The report caught the medium-term direction but entered before the policy-driven shakeout."
  },
  {
    predictionDate: "2026-04-08",
    horizon: "5 trading days",
    predictedStance: "cautious",
    actualOutcome: "small decline before support held",
    expectedReturn: -1.5,
    actualReturn: -0.9,
    reviewTags: ["risk-managed"],
    notes: "Short-horizon caution helped reduce exposure during a crowded positioning reset."
  }
];

const RESEARCH_REPORT_TEMPLATES: ResearchReportTemplate[] = [
  {
    titleTemplate: "{symbol} accelerator demand and breadth synthesis",
    createdAt: "2026-05-02T20:48:00.000Z",
    horizon: "10 trading days",
    stance: "bullish",
    confidence: 0.74,
    summary:
      "Channel checks, options positioning, and semiconductor breadth all point to a constructive short-horizon setup, with confirmation still tied to follow-through above the weekly volume shelf.",
    ledgerState: [
      "Demand checks raised second-half accelerator backlog assumptions.",
      "Options desk observed upside call spreads clustered near weekly resistance.",
      "Market breadth improved across the chip leadership basket after the open.",
      "Final stance favors a staged overweight while preserving invalidation near prior breakout support."
    ],
    riskNotes: [
      "Policy headlines can still compress multiples intraday.",
      "Dealer gamma remains a friction point near the upper weekly band.",
      "Position size should stay below full allocation until volume confirms the breakout."
    ],
    synthesisSteps: [
      "News analyst normalized event relevance across issuer, peer, and policy feeds.",
      "Market analyst compared spot action against volume profile and breadth.",
      "Risk manager checked invalidation levels against current paper exposure."
    ]
  },
  {
    titleTemplate: "{symbol} policy sensitivity review",
    createdAt: "2026-05-01T21:35:00.000Z",
    horizon: "20 trading days",
    stance: "neutral",
    confidence: 0.62,
    summary:
      "The base case remains intact, but recent regulatory language keeps the medium-horizon stance balanced until shipment assumptions and customer concentration risk are rechecked.",
    ledgerState: [
      "Policy desk found no immediate change to current-quarter shipment assumptions.",
      "Historical review flagged that policy-driven drawdowns have tended to reverse when demand checks stay firm.",
      "Fundamentals agent kept margin durability unchanged but widened the scenario band.",
      "Final stance holds exposure steady until the next supplier confirmation window."
    ],
    riskNotes: [
      "Export-control language can change faster than the local model refresh cadence.",
      "Multiple expansion is vulnerable if gross margin assumptions stop improving.",
      "Neutral stance should not auto-stage a paper ticket."
    ],
    synthesisSteps: [
      "Policy analyst scored current restrictions against prior report assumptions.",
      "Fundamentals analyst updated bull, base, and bear revenue sensitivities.",
      "Portfolio manager reconciled stance with existing position concentration."
    ]
  },
  {
    titleTemplate: "{symbol} support-zone reversal memo",
    createdAt: "2026-04-30T18:15:00.000Z",
    horizon: "5 trading days",
    stance: "bullish",
    confidence: 0.68,
    summary:
      "The prior breakout zone held through a risk-off headline, creating a tactical rebound setup supported by reduced volatility premium and improving short-term positioning.",
    ledgerState: [
      "Technical desk confirmed price held the prior breakout support zone.",
      "Volatility monitor saw implied premium compress after spot recovered.",
      "Positioning lab recorded modest short covering into the close.",
      "Final stance supports a tactical add only if support remains intact."
    ],
    riskNotes: [
      "A break below support invalidates the tactical setup.",
      "Compressed volatility can reverse quickly around macro events.",
      "Short-covering evidence is modest, not a durable demand signal by itself."
    ],
    synthesisSteps: [
      "Market analyst aligned support, VWAP, and volume-profile evidence.",
      "Sentiment analyst separated headline shock from persistent negative revisions.",
      "Risk manager converted invalidation into a clear no-trade boundary."
    ]
  }
];

export function getDashboardNewsEvents(symbol: string): NewsEvent[] {
  const normalizedSymbol = normalizeSymbol(symbol);

  return NEWS_TEMPLATES.map((event, index) => ({
    ...event,
    id: `${normalizedSymbol.toLowerCase()}-news-${String(index + 1).padStart(2, "0")}`,
    symbol: normalizedSymbol,
    title: `${normalizedSymbol}: ${event.title}`,
    url: `https://local.tradingagents.test/news/${normalizedSymbol.toLowerCase()}/${index + 1}`
  })).sort((left, right) => right.relevance - left.relevance);
}

export function getAgentConversations(symbol: string): AgentConversation[] {
  const normalizedSymbol = normalizeSymbol(symbol);
  const slug = normalizedSymbol.toLowerCase();

  return [
    {
      id: `research-lead-${slug}`,
      type: "agent",
      label: `${normalizedSymbol} Research Lead`,
      symbol: normalizedSymbol,
      unreadCount: 3,
      lastActivity: "2026-05-02T20:32:00.000Z",
      summary: "Synthesizing news, market structure, and prior outcome review before the next report update."
    },
    {
      id: `portfolio-manager-${slug}`,
      type: "agent",
      label: `${normalizedSymbol} Portfolio Manager`,
      symbol: normalizedSymbol,
      unreadCount: 1,
      lastActivity: "2026-05-02T20:18:00.000Z",
      summary: "Waiting on approval for the paper order intent and monitoring risk budget usage."
    },
    {
      id: `risk-room-${slug}`,
      type: "group",
      label: `${normalizedSymbol} Risk Room`,
      symbol: normalizedSymbol,
      unreadCount: 5,
      lastActivity: "2026-05-02T20:10:00.000Z",
      summary: "Research, execution, and risk agents are aligned on entry conditions and invalidation levels."
    },
    {
      id: "platform-alerts",
      type: "platform",
      label: "Platform Alerts",
      symbol: null,
      unreadCount: 2,
      lastActivity: "2026-05-02T19:58:00.000Z",
      summary: "Paper brokerage routing is healthy; one notification is linked to the transactions workspace."
    }
  ];
}

export function getTransactionSnapshot(symbol: string): TransactionSnapshot {
  const normalizedSymbol = normalizeSymbol(symbol);

  return {
    symbol: normalizedSymbol,
    mode: "paper",
    portfolioValue: 250000,
    buyingPower: 87650,
    positions: [
      {
        symbol: normalizedSymbol,
        quantity: 80,
        marketValue: 72800,
        dayChangePercent: 2.4
      },
      {
        symbol: "SPY",
        quantity: 120,
        marketValue: 62400,
        dayChangePercent: 0.6
      },
      {
        symbol: "TLT",
        quantity: 150,
        marketValue: 13875,
        dayChangePercent: -0.3
      }
    ],
    recentOrders: [
      {
        id: `${normalizedSymbol.toLowerCase()}-paper-order-1`,
        symbol: normalizedSymbol,
        side: "buy",
        quantity: 10,
        status: "pending",
        submittedAt: "2026-05-02T20:20:00.000Z"
      },
      {
        id: "spy-paper-order-1",
        symbol: "SPY",
        side: "sell",
        quantity: 15,
        status: "filled",
        submittedAt: "2026-05-01T18:45:00.000Z"
      }
    ],
    orderIntent: {
      id: `${normalizedSymbol.toLowerCase()}-approval-intent`,
      symbol: normalizedSymbol,
      side: "buy",
      notional: 12500,
      limitPrice: 910,
      confidence: 0.72,
      requiresApproval: true,
      rationale: "Positive demand revision and improving breadth support a staged paper add."
    }
  };
}

export function getHistoricalOutcomes(symbol: string): HistoricalOutcome[] {
  const normalizedSymbol = normalizeSymbol(symbol);

  return HISTORICAL_TEMPLATES.map((outcome, index) => ({
    ...outcome,
    symbol: normalizedSymbol,
    reportId: `${normalizedSymbol.toLowerCase()}-outcome-${String(index + 1).padStart(2, "0")}`
  })).filter((outcome) => outcome.symbol === normalizedSymbol);
}

export function getResearchReports(symbol: string): ResearchReport[] {
  const normalizedSymbol = normalizeSymbol(symbol);

  return RESEARCH_REPORT_TEMPLATES.map((report, index) => ({
    ...report,
    id: `${normalizedSymbol.toLowerCase()}-research-${String(index + 1).padStart(2, "0")}`,
    symbol: normalizedSymbol,
    title: report.titleTemplate.replace("{symbol}", normalizedSymbol)
  })).filter((report) => report.symbol === normalizedSymbol);
}

export function getInitialNotifications(symbol: string): TerminalNotification[] {
  const normalizedSymbol = normalizeSymbol(symbol);
  const slug = normalizedSymbol.toLowerCase();

  return [
    {
      id: `${slug}-news-notification`,
      severity: "info",
      title: `${normalizedSymbol} news refresh complete`,
      body: "Dashboard events were reseeded for the current research session.",
      linkedWorkspace: "dashboard",
      linkedEntityId: `${slug}-news-01`,
      ttl: 900
    },
    {
      id: `${slug}-approval-required`,
      severity: "warning",
      title: "Paper order approval required",
      body: `${normalizedSymbol} order intent is staged and waiting for human approval.`,
      linkedWorkspace: "transactions",
      linkedEntityId: `${slug}-approval-intent`
    },
    {
      id: "platform-health",
      severity: "success",
      title: "Local workspace data online",
      body: "Seeded data selectors are serving deterministic local snapshots.",
      linkedWorkspace: "agents",
      ttl: 1200
    }
  ];
}

function normalizeSymbol(symbol: string): string {
  return symbol.trim().toUpperCase();
}
