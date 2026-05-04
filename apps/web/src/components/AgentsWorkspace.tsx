"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getPrivateOfficeChannelActions,
  getPrivateOfficeChannelMessages,
  getPrivateOfficeChannels,
  getPrivateOfficeGoalDossier,
  type PrivateOfficeChannel,
  type PrivateOfficeChannelAction,
  type PrivateOfficeChannelMessage,
  type PrivateOfficeGoalDossier
} from "@/lib/workspace-data";

export function AgentsWorkspace({ symbol }: { symbol: string }) {
  const channels = useMemo(() => getPrivateOfficeChannels(symbol), [symbol]);
  const goalDossier = useMemo(() => getPrivateOfficeGoalDossier(symbol), [symbol]);
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(channels[0]?.id ?? null);
  const selectedChannel = channels.find((channel) => channel.id === selectedChannelId) ?? channels[0] ?? null;
  const messages = useMemo(
    () => (selectedChannel ? getPrivateOfficeChannelMessages(selectedChannel.id, symbol) : []),
    [selectedChannel, symbol]
  );
  const actions = useMemo(
    () => (selectedChannel ? getPrivateOfficeChannelActions(selectedChannel.id, symbol) : []),
    [selectedChannel, symbol]
  );

  useEffect(() => {
    setSelectedChannelId(channels[0]?.id ?? null);
  }, [channels]);

  return (
    <section className="agents-workspace private-office-console" aria-label="Private office agents console">
      <ChannelRail
        channels={channels}
        selectedChannelId={selectedChannel?.id ?? null}
        onSelectChannel={setSelectedChannelId}
      />
      <ChannelMessageStream
        channel={selectedChannel}
        goalDossier={goalDossier}
        messages={messages}
        symbol={symbol}
      />
      <TriagePanel actions={actions} channel={selectedChannel} goalDossier={goalDossier} />
    </section>
  );
}

function ChannelRail({
  channels,
  selectedChannelId,
  onSelectChannel
}: {
  channels: PrivateOfficeChannel[];
  selectedChannelId: string | null;
  onSelectChannel: (channelId: string) => void;
}) {
  return (
    <aside className="agents-conversation-rail private-channel-rail">
      <header className="panel-header">
        <div>
          <span className="panel-kicker">Private office</span>
          <h2>Agent teams</h2>
        </div>
        <span className="panel-count">{channels.length}</span>
      </header>
      <div className="conversation-list private-channel-list">
        {channels.map((channel) => (
          <button
            className={channel.id === selectedChannelId ? "conversation-item private-channel-item selected" : "conversation-item private-channel-item"}
            key={channel.id}
            type="button"
            onClick={() => onSelectChannel(channel.id)}
          >
            <span className={`conversation-avatar ${channel.urgency}`}>{getChannelInitials(channel.label)}</span>
            <span className="conversation-copy">
              <span className="conversation-row">
                <strong>{channel.label}</strong>
                <time>{formatShortTime(channel.lastActivity)}</time>
              </span>
              <span className="conversation-summary">{channel.description}</span>
              <span className="conversation-meta private-channel-meta">
                <span className={`channel-urgency ${channel.urgency}`}>{channel.urgency}</span>
                <span>{channel.delivery}</span>
                {channel.notifyMichael ? <span>notify</span> : null}
                {channel.unreadCount > 0 ? <span>{channel.unreadCount} unread</span> : null}
              </span>
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function ChannelMessageStream({
  channel,
  goalDossier,
  messages,
  symbol
}: {
  channel: PrivateOfficeChannel | null;
  goalDossier: PrivateOfficeGoalDossier;
  messages: PrivateOfficeChannelMessage[];
  symbol: string;
}) {
  if (!channel) {
    return (
      <section className="agents-message-stream private-message-stream">
        <p className="empty-state">No private-office channels are available.</p>
      </section>
    );
  }

  return (
    <article className="agents-message-stream private-message-stream">
      <header className="message-stream-header private-message-header">
        <div>
          <span className="panel-kicker">{channel.delivery} channel</span>
          <h1>{channel.label}</h1>
        </div>
        <span className={`status-pill channel-status ${channel.urgency}`}>{channel.urgency}</span>
      </header>
      <div className="private-channel-summary">
        <span>{channel.a2uiSurface}</span>
        <p>{channel.description}</p>
      </div>
      <div className="message-list" aria-label={`${channel.label} messages`}>
        {messages.map((message) => (
          <section className="agent-message private-agent-message" key={message.id}>
            <header>
              <span>
                <strong>{message.author}</strong>
                <small>{message.role}</small>
              </span>
              <time>{formatLongTime(message.timestamp)}</time>
            </header>
            <p>{message.body}</p>
            {message.surface ? (
              <A2UISurface message={message} goalDossier={goalDossier} symbol={symbol} />
            ) : null}
          </section>
        ))}
      </div>
    </article>
  );
}

function A2UISurface({
  goalDossier,
  message,
  symbol
}: {
  goalDossier: PrivateOfficeGoalDossier;
  message: PrivateOfficeChannelMessage;
  symbol: string;
}) {
  if (message.surface === "goal-dossier") {
    return (
      <section className="a2ui-surface-card goal-surface" aria-label={`${goalDossier.goalName} A2UI surface`}>
        <div className="a2ui-card-header">
          <div>
            <span className="panel-kicker">A2UI goal dossier</span>
            <strong>{goalDossier.assetTarget}</strong>
          </div>
          <span>{goalDossier.status}</span>
        </div>
        <div className="goal-progress-meter" aria-label={`${goalDossier.fundingProgress}% funding readiness`}>
          <span style={{ width: `${goalDossier.fundingProgress}%` }} />
        </div>
        <div className="goal-surface-grid">
          <span>Location: {goalDossier.desiredLocation}</span>
          <span>Window: {goalDossier.targetWindow}</span>
        </div>
      </section>
    );
  }

  if (message.surface === "approval-triage") {
    return (
      <section className="a2ui-surface-card approval-surface" aria-label={`${symbol} approval triage surface`}>
        <div className="a2ui-card-header">
          <div>
            <span className="panel-kicker">A2UI approval gate</span>
            <strong>{symbol} capital policy</strong>
          </div>
          <span>Human approval required</span>
        </div>
        <div className="approval-grid">
          <span>Max loss</span>
          <span>Opportunity cost</span>
          <span>Tax drag</span>
          <span>Goal impact</span>
        </div>
      </section>
    );
  }

  if (message.surface === "document-checklist") {
    return (
      <section className="a2ui-surface-card document-surface" aria-label="Asset document checklist surface">
        <div className="a2ui-card-header">
          <div>
            <span className="panel-kicker">A2UI document checklist</span>
            <strong>Asset registry shell</strong>
          </div>
          <span>Vault first</span>
        </div>
        <div className="document-chip-row">
          {["Title", "Insurance", "Registration", "Maintenance", "Advisor notes"].map((label) => (
            <span key={label}>{label}</span>
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="a2ui-surface-card morning-surface" aria-label={`${symbol} morning brief surface`}>
      <div className="a2ui-card-header">
        <div>
          <span className="panel-kicker">A2UI morning brief</span>
          <strong>Private office digest</strong>
        </div>
        <span>{symbol}</span>
      </div>
      <div className="morning-brief-grid">
        <span>Goals</span>
        <span>Capital</span>
        <span>Documents</span>
        <span>Communications</span>
      </div>
    </section>
  );
}

function TriagePanel({
  actions,
  channel,
  goalDossier
}: {
  actions: PrivateOfficeChannelAction[];
  channel: PrivateOfficeChannel | null;
  goalDossier: PrivateOfficeGoalDossier;
}) {
  return (
    <aside className="agents-action-panel private-triage-panel">
      <header className="panel-header">
        <div>
          <span className="panel-kicker">Actionable panel</span>
          <h2>Triage</h2>
        </div>
        <span className="panel-count">{actions.length}</span>
      </header>
      <section className="action-context-card private-context-card">
        <span>Selected team</span>
        <strong>{channel?.label ?? "None"}</strong>
        <p>{channel?.description ?? "Select a private-office team to review messages and available actions."}</p>
      </section>
      <div className="action-request-list private-action-list">
        {actions.map((action) => (
          <button className={`action-request private-action-request ${action.status}`} key={action.id} type="button">
            <span>
              <strong>{action.label}</strong>
              <small>{action.detail}</small>
            </span>
            <span className={action.requiresApproval ? "approval-badge required" : "approval-badge"}>
              {formatActionStatus(action)}
            </span>
          </button>
        ))}
      </div>
      <GoalDossierCard dossier={goalDossier} />
    </aside>
  );
}

function GoalDossierCard({ dossier }: { dossier: PrivateOfficeGoalDossier }) {
  return (
    <section className="goal-dossier-card" aria-label={`${dossier.goalName} dossier`}>
      <header>
        <span className="panel-kicker">Material goal</span>
        <h3>{dossier.goalName}</h3>
      </header>
      <div className="goal-dossier-stat">
        <span>{dossier.assetTarget}</span>
        <strong>{dossier.fundingProgress}%</strong>
      </div>
      <div className="goal-progress-meter">
        <span style={{ width: `${dossier.fundingProgress}%` }} />
      </div>
      <p>{dossier.estimatedAcquisitionCost}</p>
      <p>{dossier.operatingCostWatch}</p>
      <div className="goal-section">
        <strong>Capital path</strong>
        {dossier.capitalPath.map((item) => (
          <span className="goal-path-row" key={item}>{item}</span>
        ))}
      </div>
      <div className="goal-section">
        <strong>Blockers</strong>
        {dossier.blockers.map((blocker) => (
          <span className={`goal-blocker ${blocker.severity}`} key={`${blocker.owner}-${blocker.detail}`}>
            <small>{blocker.owner}</small>
            {blocker.detail}
          </span>
        ))}
      </div>
    </section>
  );
}

function getChannelInitials(label: string): string {
  return label
    .split(" ")
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

function formatActionStatus(action: PrivateOfficeChannelAction): string {
  if (action.requiresApproval) return "Approval";

  return action.status
    .split("-")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function formatShortTime(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function formatLongTime(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}
