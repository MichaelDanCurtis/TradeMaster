export type WorkspaceId = "dashboard" | "research" | "agents" | "transactions" | "historicals";
export type NewsSentiment = "positive" | "neutral" | "negative";
export type AgentConversationType = "agent" | "group" | "platform";
export type AgentMessageAuthorType = "agent" | "human" | "system";
export type AgentMessageSurface = "event-chart";
export type ActionRequestType = "proceed" | "ask-follow-up" | "create-report" | "preview-order";
export type ActionRequestStatus = "available" | "requires-approval" | "queued" | "complete";
export type NotificationSeverity = "info" | "success" | "warning" | "critical";

export type MarketTickerItem = {
  id: string;
  label: string;
  value: number;
  change: number;
  changePercent: number;
  sparkline: number[];
};

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

export type AgentMessage = {
  id: string;
  conversationId: string;
  author: {
    type: AgentMessageAuthorType;
    name: string;
  };
  body: string;
  timestamp: string;
  a2uiSurface?: AgentMessageSurface;
};

export type ActionRequest = {
  id: string;
  conversationId: string;
  type: ActionRequestType;
  label: string;
  requiresApproval: boolean;
  status: ActionRequestStatus;
  backendIntentId?: string;
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

export type PrivateOfficeRiskClass = "information" | "recommendation" | "paper" | "approval-gated";
export type PrivateOfficeTeamKind =
  | "goals"
  | "advisor"
  | "research"
  | "capital"
  | "control"
  | "property"
  | "communications";

export type PrivateOfficeTeam = {
  id: string;
  kind: PrivateOfficeTeamKind;
  name: string;
  mission: string;
  cadence: string;
  riskClass: PrivateOfficeRiskClass;
  responsibilities: string[];
  a2uiSurfaces: string[];
  currentFocus: string;
};

export type PrivateOfficeBrief = {
  symbol: string;
  headline: string;
  generatedAt: string;
  priorityItems: string[];
  goalSignals: Array<{
    goalName: string;
    status: string;
    detail: string;
  }>;
  controlSignals: Array<{
    team: string;
    severity: "info" | "watch" | "urgent";
    detail: string;
  }>;
};

export type PrivateOfficeRunQueueItem = {
  id: string;
  title: string;
  team: string;
  status: "running" | "queued" | "waiting" | "complete";
  startedAt: string;
  steps: Array<{
    label: string;
    status: "running" | "queued" | "waiting" | "complete";
  }>;
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
type PrivateOfficeBriefTemplate = Omit<PrivateOfficeBrief, "symbol">;
type AgentMessageTemplate = Omit<AgentMessage, "id" | "conversationId" | "body"> & {
  bodyTemplate: string;
};
type ActionRequestTemplate = Omit<ActionRequest, "id" | "conversationId" | "label" | "backendIntentId"> & {
  labelTemplate: string;
  backendIntentIdTemplate?: string;
};

const MARKET_TICKER_ITEMS: MarketTickerItem[] = [
  {
    id: "spx",
    label: "S&P 500",
    value: 7230.12,
    change: 21.11,
    changePercent: 0.29,
    sparkline: [7196, 7211, 7238, 7224, 7244, 7237, 7250, 7231, 7229, 7236, 7221, 7230]
  },
  {
    id: "dji",
    label: "Dow Jones",
    value: 49499.27,
    change: -152.871,
    changePercent: -0.31,
    sparkline: [49780, 49712, 49682, 49610, 49592, 49541, 49588, 49520, 49498, 49430, 49475, 49499]
  },
  {
    id: "ndx",
    label: "Nasdaq",
    value: 27710.36,
    change: 258.238,
    changePercent: 0.94,
    sparkline: [27380, 27520, 27618, 27692, 27736, 27688, 27780, 27715, 27742, 27708, 27732, 27710]
  },
  {
    id: "tipranks50",
    label: "TipRanks 50",
    value: 3520.06,
    change: 3.88,
    changePercent: 0.11,
    sparkline: [3508, 3516, 3522, 3519, 3527, 3521, 3526, 3518, 3524, 3519, 3523, 3520]
  },
  {
    id: "btc",
    label: "Bitcoin",
    value: 78113.19,
    change: -556.365,
    changePercent: -0.71,
    sparkline: [78680, 78420, 78560, 78210, 78330, 78190, 78288, 78070, 78152, 77980, 78240, 78113]
  },
  {
    id: "eth",
    label: "Ethereum",
    value: 2297.6,
    change: -19.048,
    changePercent: -0.82,
    sparkline: [2322, 2314, 2328, 2310, 2304, 2312, 2298, 2306, 2291, 2300, 2294, 2297.6]
  }
];

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

const PRIVATE_OFFICE_TEAMS: PrivateOfficeTeam[] = [
  {
    id: "goals",
    kind: "goals",
    name: "Goals Team",
    mission: "Translate Michael's material goals into measurable funding paths, blockers, and decision gates.",
    cadence: "Daily brief, monthly goal dossier, quarterly plan review",
    riskClass: "recommendation",
    responsibilities: [
      "Track yacht, property, liquidity, business-capital, and lifestyle goals against portfolio trajectory.",
      "Convert {symbol} opportunity changes into goal-progress impact rather than isolated trade excitement.",
      "Request tax, legal, insurance, and capital committee reviews when a goal becomes actionable."
    ],
    a2uiSurfaces: ["goal-progress view", "capital path planner", "decision gate card"],
    currentFocus: "{symbol} concentration can accelerate the yacht goal, but only if risk and tax drag stay inside policy."
  },
  {
    id: "advisor",
    kind: "advisor",
    name: "Advisor Synthesis Team",
    mission: "Create the morning private-office synopsis from every team without flooding Michael with raw agent chatter.",
    cadence: "Pre-market, urgent escalation, weekly management packet",
    riskClass: "information",
    responsibilities: [
      "Summarize research, property, tax, capital, and communication signals into one operator brief.",
      "Rank what needs attention now, what can wait, and what should stay in the archive.",
      "Route {symbol} evidence to the correct report, goal, and capital committee surface."
    ],
    a2uiSurfaces: ["morning brief", "evidence board", "advisor memo"],
    currentFocus: "Morning brief is prioritizing {symbol} research, Webull readiness, and private-office setup work."
  },
  {
    id: "research-bodies",
    kind: "research",
    name: "Always-On Research Bodies",
    mission: "Watch markets, smart money, filings, options flow, news, macro, and company evidence on a schedule.",
    cadence: "Pre-market scan, intraday alerts, post-market wrap",
    riskClass: "information",
    responsibilities: [
      "Track smart-money signals, congressional disclosure lag, unusual options flow, and issuer news.",
      "Trigger deep research when {symbol} events meaningfully affect goals or portfolio risk.",
      "Grade data quality before a signal reaches the capital committee."
    ],
    a2uiSurfaces: ["event markers", "source pack", "research trigger card"],
    currentFocus: "{symbol} signal stack is queued for company intelligence, market watch, and options-flow review."
  },
  {
    id: "capital-committee",
    kind: "capital",
    name: "TradingAgents / Capital Committee",
    mission: "Act as CFO-style stewards deciding whether an opportunity deserves capital and under what guardrails.",
    cadence: "On-demand for proposals, end-of-day P&L, weekly allocation review",
    riskClass: "approval-gated",
    responsibilities: [
      "Weigh cash, buying power, loss history, goal impact, taxes, opportunity cost, and downside.",
      "Compare {symbol} proposals against SPY, treasuries, cash, debt paydown, and waiting.",
      "Stage paper or live-preview intents only after policy, risk, and human approval gates are satisfied."
    ],
    a2uiSurfaces: ["capital committee memo", "approval card", "risk-adjusted allocation panel"],
    currentFocus: "{symbol} remains report-first until Webull data and approval policy are configured."
  },
  {
    id: "property",
    kind: "property",
    name: "Asset & Property Management Team",
    mission: "Maintain non-portfolio asset records, documents, maintenance, insurance, and liability reminders.",
    cadence: "Daily exceptions, weekly document audit, monthly valuation review",
    riskClass: "recommendation",
    responsibilities: [
      "Track houses, cars, boats, firearms, equipment, titles, registrations, insurance, and service records.",
      "Flag missing documents, expiring registrations, insurance mismatches, and entity-ownership issues.",
      "Connect major purchase goals to document, insurance, tax, and liability requirements."
    ],
    a2uiSurfaces: ["asset dossier", "document checklist", "liability issue card"],
    currentFocus: "Yacht ownership dossier needs Hawaii insurance, moorage, entity, and operating-cost inputs."
  },
  {
    id: "tax-structure",
    kind: "control",
    name: "Tax & Structure Body",
    mission: "Surface tax drag, entity structure, holding period, wash-sale, and CPA-reviewable implications.",
    cadence: "Trade proposal review, monthly tax issue scan, quarterly estimated-tax packet",
    riskClass: "recommendation",
    responsibilities: [
      "Review realized and unrealized gains, option assignment risk, dividend treatment, and loss-harvesting candidates.",
      "Translate outside CPA and attorney guidance into dated, source-linked notes.",
      "Block any {symbol} action from being presented as tax advice without professional review language."
    ],
    a2uiSurfaces: ["tax issue card", "advisor guidance memo", "structure comparison table"],
    currentFocus: "{symbol} concentration and future yacht-goal funding need tax drag visibility before capital decisions."
  },
  {
    id: "communications",
    kind: "communications",
    name: "Communications Team",
    mission: "Triage agent messages, route inbound notes, suppress noise, and mirror important communications into records.",
    cadence: "Always on, digest by urgency",
    riskClass: "information",
    responsibilities: [
      "Decide whether an event becomes internal inbox only, notification, email, or iMessage-style message.",
      "Allow Hermes to route sanitized messages without giving Hermes financial system-of-record access.",
      "Record important approvals and outside-advisor statements in the decision journal."
    ],
    a2uiSurfaces: ["inbox triage", "notification policy card", "decision journal entry"],
    currentFocus: "Team identities are drafted, but outbound messaging remains stubbed until the router is designed."
  }
];

const PRIVATE_OFFICE_BRIEF: PrivateOfficeBriefTemplate = {
  headline: "Private Office Morning Brief",
  generatedAt: "2026-05-03T06:30:00.000Z",
  priorityItems: [
    "{symbol} research is report-first: Webull remains the trading cockpit and Wealth Agents records the thesis.",
    "Capital Committee should compare any {symbol} opportunity against cash, SPY, treasuries, and the yacht goal.",
    "Property Team has an open yacht dossier for Hawaii liability, moorage, insurance, and ownership structure.",
    "Communications Team is the gate for agent outreach; Hermes can route sanitized messages but not vault data.",
    "Backup design is now a control issue because the MacBook server becomes a private-office record system."
  ],
  goalSignals: [
    {
      goalName: "Absolute / Navetta 68 yacht acquisition",
      status: "planning",
      detail: "Funding path depends on portfolio trajectory, Hawaii operating liabilities, tax structure, insurance, and entity review."
    },
    {
      goalName: "MacBook private-office server",
      status: "build-ready",
      detail: "Needs encrypted local snapshot, off-machine backup target, and restore test before production documents land."
    }
  ],
  controlSignals: [
    {
      team: "Communications Team",
      severity: "watch",
      detail: "Agent emails and iMessage-style routing should flow through one triage layer to prevent alert fatigue."
    },
    {
      team: "Security & Access Team",
      severity: "urgent",
      detail: "Hermes must remain separated from broker, banking, and document-vault authority."
    },
    {
      team: "Tax & Structure Body",
      severity: "info",
      detail: "Tax and entity memos should remain CPA/attorney-reviewable recommendations, not final advice."
    }
  ]
};

const PRIVATE_OFFICE_RUN_QUEUE: PrivateOfficeRunQueueItem[] = [
  {
    id: "private-office-morning-brief",
    title: "{symbol} private-office morning synthesis",
    team: "Advisor Synthesis Team",
    status: "running",
    startedAt: "2026-05-03T06:30:00.000Z",
    steps: [
      { label: "Collect research body updates", status: "complete" },
      { label: "Merge goal and capital signals", status: "running" },
      { label: "Prepare A2UI brief", status: "queued" }
    ]
  },
  {
    id: "capital-committee-preview",
    title: "{symbol} capital committee readiness review",
    team: "TradingAgents / Capital Committee",
    status: "waiting",
    startedAt: "2026-05-03T06:38:00.000Z",
    steps: [
      { label: "Wait for Webull provider keys", status: "waiting" },
      { label: "Compare opportunity cost", status: "queued" },
      { label: "Create approval-gated memo", status: "queued" }
    ]
  },
  {
    id: "property-yacht-dossier",
    title: "Yacht ownership liability and document checklist",
    team: "Asset & Property Management Team",
    status: "queued",
    startedAt: "2026-05-03T06:45:00.000Z",
    steps: [
      { label: "Collect ownership structure questions", status: "queued" },
      { label: "List insurance and moorage documents", status: "queued" },
      { label: "Escalate CPA and attorney review items", status: "queued" }
    ]
  }
];

const CONVERSATION_MESSAGE_TEMPLATES: Record<string, AgentMessageTemplate[]> = {
  "research-lead": [
    {
      author: { type: "agent", name: "Research Lead" },
      bodyTemplate:
        "{symbol} evidence is converging around demand revision, breadth improvement, and a still-defined invalidation level.",
      timestamp: "2026-05-02T20:21:00.000Z"
    },
    {
      author: { type: "agent", name: "News Analyst" },
      bodyTemplate:
        "I pinned the highest-relevance demand, options, and supply events into the chart context for review.",
      timestamp: "2026-05-02T20:24:00.000Z",
      a2uiSurface: "event-chart"
    },
    {
      author: { type: "agent", name: "Research Lead" },
      bodyTemplate:
        "Recommendation is proceed to report refresh first, then preview the staged paper order before any approval.",
      timestamp: "2026-05-02T20:32:00.000Z"
    }
  ],
  "portfolio-manager": [
    {
      author: { type: "agent", name: "Portfolio Manager" },
      bodyTemplate:
        "{symbol} paper intent is staged below full allocation while the risk room waits on volume confirmation.",
      timestamp: "2026-05-02T20:13:00.000Z"
    },
    {
      author: { type: "system", name: "Paper Broker" },
      bodyTemplate: "Buying power and concentration checks are clear for a preview-only ticket.",
      timestamp: "2026-05-02T20:18:00.000Z"
    }
  ],
  "risk-room": [
    {
      author: { type: "agent", name: "Risk Manager" },
      bodyTemplate:
        "Entry can remain conditional: staged add above support, no escalation if policy headlines widen the scenario band.",
      timestamp: "2026-05-02T20:02:00.000Z"
    },
    {
      author: { type: "agent", name: "Execution Agent" },
      bodyTemplate: "Preview order is available, but approval must stay human-gated in paper mode.",
      timestamp: "2026-05-02T20:10:00.000Z"
    }
  ],
  "platform-alerts": [
    {
      author: { type: "system", name: "Platform Alerts" },
      bodyTemplate: "Local workspace data is online and serving deterministic agent snapshots.",
      timestamp: "2026-05-02T19:58:00.000Z"
    },
    {
      author: { type: "system", name: "Paper Broker" },
      bodyTemplate: "Routing health is green. Approval-required intents remain blocked until explicit confirmation.",
      timestamp: "2026-05-02T20:05:00.000Z"
    }
  ]
};

const CONVERSATION_ACTION_TEMPLATES: Record<string, ActionRequestTemplate[]> = {
  "research-lead": [
    {
      type: "proceed",
      labelTemplate: "Proceed with {symbol} synthesis",
      requiresApproval: false,
      status: "available"
    },
    {
      type: "ask-follow-up",
      labelTemplate: "Ask follow-up about policy risk",
      requiresApproval: false,
      status: "available"
    },
    {
      type: "create-report",
      labelTemplate: "Create refreshed research report",
      requiresApproval: false,
      status: "queued"
    },
    {
      type: "preview-order",
      labelTemplate: "Preview staged {symbol} paper order",
      requiresApproval: true,
      status: "requires-approval",
      backendIntentIdTemplate: "{slug}-approval-intent"
    }
  ],
  "portfolio-manager": [
    {
      type: "preview-order",
      labelTemplate: "Preview {symbol} paper ticket",
      requiresApproval: true,
      status: "requires-approval",
      backendIntentIdTemplate: "{slug}-approval-intent"
    },
    {
      type: "ask-follow-up",
      labelTemplate: "Ask about allocation sizing",
      requiresApproval: false,
      status: "available"
    }
  ],
  "risk-room": [
    {
      type: "ask-follow-up",
      labelTemplate: "Ask risk room for invalidation check",
      requiresApproval: false,
      status: "available"
    },
    {
      type: "create-report",
      labelTemplate: "Create risk addendum",
      requiresApproval: false,
      status: "available"
    }
  ],
  "platform-alerts": [
    {
      type: "proceed",
      labelTemplate: "Open linked platform notice",
      requiresApproval: false,
      status: "available"
    }
  ]
};

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

export function getAgentMessages(conversationId: string): AgentMessage[] {
  const conversationKey = getConversationTemplateKey(conversationId);
  const symbol = getSymbolFromConversationId(conversationId);
  const slug = symbol.toLowerCase();
  const templates = CONVERSATION_MESSAGE_TEMPLATES[conversationKey] ?? CONVERSATION_MESSAGE_TEMPLATES["platform-alerts"];

  return templates.map((message, index) => ({
    ...message,
    author: { ...message.author },
    id: `${conversationId}-message-${String(index + 1).padStart(2, "0")}`,
    conversationId,
    body: message.bodyTemplate.replaceAll("{symbol}", symbol).replaceAll("{slug}", slug)
  }));
}

export function getConversationActions(conversationId: string): ActionRequest[] {
  const conversationKey = getConversationTemplateKey(conversationId);
  const symbol = getSymbolFromConversationId(conversationId);
  const slug = symbol.toLowerCase();
  const templates = CONVERSATION_ACTION_TEMPLATES[conversationKey] ?? CONVERSATION_ACTION_TEMPLATES["platform-alerts"];

  return templates.map((action, index) => ({
    ...action,
    id: `${conversationId}-action-${String(index + 1).padStart(2, "0")}`,
    conversationId,
    label: action.labelTemplate.replaceAll("{symbol}", symbol).replaceAll("{slug}", slug),
    backendIntentId: action.backendIntentIdTemplate
      ?.replaceAll("{symbol}", symbol)
      .replaceAll("{slug}", slug)
  }));
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
    reportId: `${normalizedSymbol.toLowerCase()}-outcome-${String(index + 1).padStart(2, "0")}`,
    reviewTags: [...outcome.reviewTags]
  })).filter((outcome) => outcome.symbol === normalizedSymbol);
}

export function getResearchReports(symbol: string): ResearchReport[] {
  const normalizedSymbol = normalizeSymbol(symbol);

  return RESEARCH_REPORT_TEMPLATES.map((report, index) => ({
    ...report,
    id: `${normalizedSymbol.toLowerCase()}-research-${String(index + 1).padStart(2, "0")}`,
    symbol: normalizedSymbol,
    title: report.titleTemplate.replace("{symbol}", normalizedSymbol),
    ledgerState: [...report.ledgerState],
    riskNotes: [...report.riskNotes],
    synthesisSteps: [...report.synthesisSteps]
  })).filter((report) => report.symbol === normalizedSymbol);
}

export function getPrivateOfficeTeams(symbol: string): PrivateOfficeTeam[] {
  const normalizedSymbol = normalizeSymbol(symbol);

  return PRIVATE_OFFICE_TEAMS.map((team) => ({
    ...team,
    responsibilities: team.responsibilities.map((responsibility) =>
      responsibility.replaceAll("{symbol}", normalizedSymbol)
    ),
    a2uiSurfaces: [...team.a2uiSurfaces],
    currentFocus: team.currentFocus.replaceAll("{symbol}", normalizedSymbol)
  }));
}

export function getPrivateOfficeBrief(symbol: string): PrivateOfficeBrief {
  const normalizedSymbol = normalizeSymbol(symbol);

  return {
    ...PRIVATE_OFFICE_BRIEF,
    symbol: normalizedSymbol,
    priorityItems: PRIVATE_OFFICE_BRIEF.priorityItems.map((item) => item.replaceAll("{symbol}", normalizedSymbol)),
    goalSignals: PRIVATE_OFFICE_BRIEF.goalSignals.map((signal) => ({ ...signal })),
    controlSignals: PRIVATE_OFFICE_BRIEF.controlSignals.map((signal) => ({ ...signal }))
  };
}

export function getPrivateOfficeRunQueue(symbol: string): PrivateOfficeRunQueueItem[] {
  const normalizedSymbol = normalizeSymbol(symbol);

  return PRIVATE_OFFICE_RUN_QUEUE.map((item) => ({
    ...item,
    title: item.title.replaceAll("{symbol}", normalizedSymbol),
    steps: item.steps.map((step) => ({ ...step }))
  }));
}

export function getInitialNotifications(symbol: string): TerminalNotification[] {
  const normalizedSymbol = normalizeSymbol(symbol);
  const slug = normalizedSymbol.toLowerCase();

  return [
    {
      id: `${slug}-news-notification`,
      severity: "info",
      title: `${normalizedSymbol} news refresh complete`,
      body: "Market context events were reseeded for the current research session.",
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

export function getMarketTickerItems(): MarketTickerItem[] {
  return MARKET_TICKER_ITEMS.map((item) => ({
    ...item,
    sparkline: [...item.sparkline]
  }));
}

function normalizeSymbol(symbol: string): string {
  return symbol.trim().toUpperCase();
}

function getConversationTemplateKey(conversationId: string): string {
  if (conversationId.startsWith("research-lead-")) return "research-lead";
  if (conversationId.startsWith("portfolio-manager-")) return "portfolio-manager";
  if (conversationId.startsWith("risk-room-")) return "risk-room";

  return "platform-alerts";
}

function getSymbolFromConversationId(conversationId: string): string {
  const parts = conversationId.split("-");
  const lastPart = parts[parts.length - 1] ?? "NVDA";

  if (conversationId === "platform-alerts") return "SYSTEM";

  return normalizeSymbol(lastPart);
}
