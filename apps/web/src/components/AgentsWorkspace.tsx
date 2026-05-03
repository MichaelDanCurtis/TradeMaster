"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getAgentConversations,
  getAgentMessages,
  getConversationActions,
  type ActionRequest,
  type AgentConversation,
  type AgentMessage
} from "@/lib/workspace-data";

export function AgentsWorkspace({ symbol }: { symbol: string }) {
  const conversations = useMemo(() => getAgentConversations(symbol), [symbol]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const selectedConversation =
    conversations.find((conversation) => conversation.id === selectedConversationId) ?? conversations[0] ?? null;
  const messages = useMemo(
    () => (selectedConversation ? getAgentMessages(selectedConversation.id) : []),
    [selectedConversation]
  );
  const actions = useMemo(
    () => (selectedConversation ? getConversationActions(selectedConversation.id) : []),
    [selectedConversation]
  );

  useEffect(() => {
    setSelectedConversationId(conversations[0]?.id ?? null);
  }, [conversations]);

  return (
    <section className="agents-workspace" aria-label="Agents workspace">
      <ConversationRail
        conversations={conversations}
        selectedConversationId={selectedConversation?.id ?? null}
        onSelectConversation={setSelectedConversationId}
      />
      <MessageStream conversation={selectedConversation} messages={messages} symbol={symbol} />
      <ActionPanel actions={actions} conversation={selectedConversation} />
    </section>
  );
}

function ConversationRail({
  conversations,
  selectedConversationId,
  onSelectConversation
}: {
  conversations: AgentConversation[];
  selectedConversationId: string | null;
  onSelectConversation: (conversationId: string) => void;
}) {
  return (
    <aside className="agents-conversation-rail">
      <header className="panel-header">
        <div>
          <span className="panel-kicker">Agent inbox</span>
          <h2>Conversations</h2>
        </div>
        <span className="panel-count">{conversations.length}</span>
      </header>
      <div className="conversation-list">
        {conversations.map((conversation) => (
          <button
            className={
              conversation.id === selectedConversationId ? "conversation-item selected" : "conversation-item"
            }
            key={conversation.id}
            type="button"
            onClick={() => onSelectConversation(conversation.id)}
          >
            <span className={`conversation-avatar ${conversation.type}`}>{getConversationInitials(conversation)}</span>
            <span className="conversation-copy">
              <span className="conversation-row">
                <strong>{conversation.label}</strong>
                <time>{formatShortTime(conversation.lastActivity)}</time>
              </span>
              <span className="conversation-summary">{conversation.summary}</span>
              <span className="conversation-meta">
                <span>{conversation.type}</span>
                {conversation.unreadCount > 0 ? <span>{conversation.unreadCount} unread</span> : null}
              </span>
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function MessageStream({
  conversation,
  messages,
  symbol
}: {
  conversation: AgentConversation | null;
  messages: AgentMessage[];
  symbol: string;
}) {
  if (!conversation) {
    return (
      <section className="agents-message-stream">
        <p className="empty-state">No agent conversations are available.</p>
      </section>
    );
  }

  return (
    <article className="agents-message-stream">
      <header className="message-stream-header">
        <div>
          <span className="panel-kicker">{conversation.type}</span>
          <h1>{conversation.label}</h1>
        </div>
        <span className="status-pill paper">{conversation.symbol ?? "System"}</span>
      </header>
      <div className="message-list" aria-label={`${conversation.label} messages`}>
        {messages.map((message) => (
          <section className={`agent-message ${message.author.type}`} key={message.id}>
            <header>
              <strong>{message.author.name}</strong>
              <time>{formatLongTime(message.timestamp)}</time>
            </header>
            <p>{message.body}</p>
            {message.a2uiSurface === "event-chart" ? <EventChartSurface symbol={symbol} /> : null}
          </section>
        ))}
      </div>
    </article>
  );
}

function EventChartSurface({ symbol }: { symbol: string }) {
  const bars = [44, 58, 52, 69, 74, 66, 82, 88];

  return (
    <section className="a2ui-surface-card" aria-label={`${symbol} event chart preview`}>
      <div className="a2ui-card-header">
        <div>
          <span className="panel-kicker">A2UI surface</span>
          <strong>{symbol} event chart</strong>
        </div>
        <span>Constrained preview</span>
      </div>
      <div className="a2ui-chart-grid">
        {bars.map((height, index) => (
          <span
            className={index >= bars.length - 3 ? "a2ui-chart-bar active" : "a2ui-chart-bar"}
            key={`${height}-${index}`}
            style={{ height: `${height}%` }}
          />
        ))}
      </div>
      <div className="a2ui-event-row">
        <span>Demand revision</span>
        <span>Options flow</span>
        <span>Supply update</span>
      </div>
    </section>
  );
}

function ActionPanel({
  actions,
  conversation
}: {
  actions: ActionRequest[];
  conversation: AgentConversation | null;
}) {
  return (
    <aside className="agents-action-panel">
      <header className="panel-header">
        <div>
          <span className="panel-kicker">Context</span>
          <h2>Actions</h2>
        </div>
        <span className="panel-count">{actions.length}</span>
      </header>
      <section className="action-context-card">
        <span>Selected thread</span>
        <strong>{conversation?.label ?? "None"}</strong>
        <p>{conversation?.summary ?? "Select a conversation to review available actions."}</p>
      </section>
      <div className="action-request-list">
        {actions.map((action) => (
          <button className={`action-request ${action.status}`} key={action.id} type="button">
            <span>
              <strong>{action.label}</strong>
              <small>{formatActionType(action.type)}</small>
            </span>
            <span className={action.requiresApproval ? "approval-badge required" : "approval-badge"}>{formatStatus(action)}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function getConversationInitials(conversation: AgentConversation): string {
  if (conversation.type === "platform") return "PA";

  return conversation.label
    .split(" ")
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

function formatActionType(value: ActionRequest["type"]): string {
  return value
    .split("-")
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function formatStatus(action: ActionRequest): string {
  if (action.requiresApproval) return "Approval";

  return action.status.replace("-", " ");
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
