import { Fragment, type FormEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import { trackAppEvent } from "../../../lib/appLogger";
import { assetUrl, canShowUsage } from "../appUtils";
import type { ContextSource, Conversation, ConversationSummary, ConversationUsage, Message, UsageEvent, UsageSummary } from "../types";

export function ChatPage({ initialConversationId, userAvatar }: { initialConversationId?: string | null; userAvatar?: string | null }) {
  const [summaries, setSummaries] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [composerLimit, setComposerLimit] = useState<{ until?: number; message: string; kind: "burst" | "monthly" } | null>(null);
  const [pauseNow, setPauseNow] = useState(() => Date.now());
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sidePanel, setSidePanel] = useState<"history" | "usage">("history");
  const [runtime, setRuntime] = useState<{ provider?: string; model?: string; available_models?: string[] }>({});
  const [contextSources, setContextSources] = useState<ContextSource[]>([]);
  const [contextMenuOpen, setContextMenuOpen] = useState(false);
  const [usage, setUsage] = useState<ConversationUsage | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageError, setUsageError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const cancelDeleteRef = useRef<HTMLButtonElement | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const composerPauseTimerRef = useRef<number | null>(null);
  const initializedRef = useRef(false);
  const shouldStickToBottomRef = useRef(true);
  const shouldRestoreInputFocusRef = useRef(false);

  async function fetchSummaries() {
    const response = await apiFetch("/api/agent/conversations");
    if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not load chat history."));
    const data = await response.json();
    const rows = (data.conversations || []) as ConversationSummary[];
    setSummaries(rows);
    return rows;
  }

  async function loadConversationUsage(id: string) {
    if (!canShowUsage) return;
    setUsageLoading(true);
    setUsageError("");
    try {
      const response = await apiFetch(`/api/agent/conversations/${id}/usage`);
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Usage unavailable."));
      setUsage((await response.json()) as ConversationUsage);
    } catch (caught) {
      setUsage(null);
      setUsageError(caught instanceof Error ? caught.message : "Usage unavailable.");
    } finally {
      setUsageLoading(false);
    }
  }

  async function openConversation(id: string) {
    setLoading(true);
    setError("");
    shouldStickToBottomRef.current = true;
    setUsage(null);
    setUsageError("");
    try {
      const response = await apiFetch(`/api/agent/conversations/${id}`);
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not load that conversation."));
      const data = (await response.json()) as Conversation;
      setConversation(data);
      trackAppEvent("chat_opened", { conversation_id: data.id }, { page: "chat", target_type: "conversation", target_id: data.id });
      syncChatToBottomAfterRender();
      void loadConversationUsage(data.id);
      const contextResponse = await apiFetch(`/api/agent/conversations/${data.id}/context-sources`);
      if (contextResponse.ok) {
        const contextData = await contextResponse.json();
        setContextSources(contextData.available_sources || []);
      }
      window.localStorage.setItem("omiryn.activeConversationId", data.id);
      const url = new URL("/", window.location.origin);
      url.searchParams.set("conversation_id", data.id);
      window.history.replaceState({}, "", url);
      setHistoryOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load conversation.");
    } finally {
      setLoading(false);
    }
  }

  async function createConversation() {
    setLoading(true);
    setError("");
    try {
      const response = await apiFetch("/api/agent/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_mode: "know_me", agent_tone: "warm", agent_model: runtime.model || null })
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not start a conversation."));
      const created = (await response.json()) as Conversation;
      setConversation(created);
      trackAppEvent("chat_started", { conversation_id: created.id }, { page: "chat", target_type: "conversation", target_id: created.id });
      await fetchSummaries();
      await openConversation(created.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not start a conversation.");
      setLoading(false);
    }
  }

  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    Promise.all([
      apiFetch("/api/agent/status").then((response) => response.ok ? response.json() : {}),
      fetchSummaries()
    ]).then(([status, rows]) => {
      setRuntime(status);
      const saved = window.localStorage.getItem("omiryn.activeConversationId");
      const preferred = initialConversationId || saved || rows[0]?.id;
      if (preferred) return openConversation(preferred);
      setConversation(null);
      setLoading(false);
    }).catch((caught) => {
      setError(caught instanceof Error ? caught.message : "Could not open chat.");
      setLoading(false);
    });
  }, []);

  useLayoutEffect(() => {
    if (!conversation || !window.location.hash.startsWith("#message-")) return;
    const targetId = window.location.hash.slice(1);
    window.requestAnimationFrame(() => {
      const target = document.getElementById(targetId);
      if (!target) return;
      target.scrollIntoView({ block: "center" });
      target.classList.add("evidence-highlight");
      window.setTimeout(() => target.classList.remove("evidence-highlight"), 2400);
    });
  }, [conversation?.id, conversation?.messages.length]);

  function isLogNearBottom() {
    const log = logRef.current;
    if (!log) return true;
    return log.scrollHeight - log.scrollTop - log.clientHeight < 120;
  }

  function focusComposer() {
    window.requestAnimationFrame(() => {
      inputRef.current?.focus({ preventScroll: true });
    });
  }

  function syncChatToBottom() {
    const log = logRef.current;
    if (!log) return;
    log.scrollTop = log.scrollHeight;
  }

  function syncChatToBottomAfterRender() {
    syncChatToBottom();
    window.requestAnimationFrame(() => {
      syncChatToBottom();
    });
  }

  useLayoutEffect(() => {
    if (!shouldStickToBottomRef.current) return;
    syncChatToBottomAfterRender();
  }, [conversation?.id, conversation?.messages.length, loading, sending]);

  useEffect(() => {
    return () => {
      if (composerPauseTimerRef.current !== null) window.clearInterval(composerPauseTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!composerLimit?.until) return;
    if (composerPauseTimerRef.current !== null) window.clearInterval(composerPauseTimerRef.current);
    composerPauseTimerRef.current = window.setInterval(() => {
      setPauseNow(Date.now());
      if (composerLimit.until && Date.now() >= composerLimit.until) {
        setComposerLimit(null);
        if (composerPauseTimerRef.current !== null) {
          window.clearInterval(composerPauseTimerRef.current);
          composerPauseTimerRef.current = null;
        }
      }
    }, 1000);
    return () => {
      if (composerPauseTimerRef.current !== null) {
        window.clearInterval(composerPauseTimerRef.current);
        composerPauseTimerRef.current = null;
      }
    };
  }, [composerLimit]);

  function handleChatScroll() {
    shouldStickToBottomRef.current = isLogNearBottom();
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || !conversation || sending || composerLimit) return;
    shouldStickToBottomRef.current = true;
    const activeElement = document.activeElement;
    shouldRestoreInputFocusRef.current = activeElement instanceof HTMLElement && Boolean(activeElement.closest(".composer"));
    const previousConversation = conversation;
    setDraft("");
    setSending(true);
    setError("");
    setComposerLimit(null);
    setConversation({ ...conversation, messages: [...conversation.messages, { role: "user", content: message, created_at: new Date().toISOString(), delivery_status: "sent" }] });
    syncChatToBottom();
    if (shouldRestoreInputFocusRef.current) focusComposer();
    let handledInlineError = false;
    try {
      const response = await apiFetch(`/api/agent/conversations/${conversation.id}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message })
      });
      if (!response.ok) {
        const detail = await apiErrorMessage(response, "Omiryn could not reply.");
        setConversation(previousConversation);
        if (response.status === 429) {
          const friendly = friendlyQuotaMessage(detail);
          const retryAfterSeconds = retryAfterFromResponse(response);
          if (detail.toLowerCase().includes("short time")) {
            const pausedAt = Date.now();
            setPauseNow(pausedAt);
            setComposerLimit({ until: pausedAt + (retryAfterSeconds || 60) * 1000, message: friendly, kind: "burst" });
            setError("");
            handledInlineError = true;
          } else {
            const pausedAt = Date.now();
            setPauseNow(pausedAt);
            setComposerLimit({
              until: retryAfterSeconds ? pausedAt + retryAfterSeconds * 1000 : undefined,
              message: friendly,
              kind: "monthly"
            });
            setError("");
            handledInlineError = true;
          }
          throw new Error(friendly);
        }
        throw new Error(detail);
      }
      const nextConversation = (await response.json()) as Conversation;
      setSending(false);
      setConversation(nextConversation);
      await fetchSummaries();
      void loadConversationUsage(nextConversation.id);
    } catch (caught) {
      setDraft(message);
      if (!handledInlineError) setError(caught instanceof Error ? caught.message : "Omiryn could not reply.");
    } finally {
      setSending(false);
      if (shouldRestoreInputFocusRef.current) focusComposer();
      shouldRestoreInputFocusRef.current = false;
    }
  }

  async function updateModel(model: string) {
    if (!conversation) return;
    const response = await apiFetch(`/api/agent/conversations/${conversation.id}/settings`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_model: model })
    });
    if (response.ok) setConversation((await response.json()) as Conversation);
  }

  async function toggleContext(sourceId: string) {
    if (!conversation) return;
    const selected = contextSources.filter((source) => source.attached).map((source) => source.id);
    const nextIds = selected.includes(sourceId) ? selected.filter((id) => id !== sourceId) : [...selected, sourceId];
    const response = await apiFetch(`/api/agent/conversations/${conversation.id}/context-sources/attachments`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_ids: nextIds })
    });
    if (!response.ok) {
      setError(await apiErrorMessage(response, "Could not update conversation context."));
      return;
    }
    const data = await response.json();
    setContextSources(data.available_sources || []);
    await fetchSummaries();
  }

  useEffect(() => {
    if (!pendingDelete) return;
    cancelDeleteRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !deleting) setPendingDelete(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [pendingDelete, deleting]);

  async function deleteConversation(id: string) {
    setDeleting(true);
    const response = await apiFetch(`/api/agent/conversations/${id}`, { method: "DELETE" });
    if (!response.ok) {
      setError(await apiErrorMessage(response, "Could not delete this conversation."));
      setDeleting(false);
      return;
    }
    const rows = await fetchSummaries();
    if (conversation?.id === id) {
      window.localStorage.removeItem("omiryn.activeConversationId");
      window.history.replaceState({}, "", "/");
      setConversation(null);
      setContextSources([]);
      setUsage(null);
      setUsageError("");
      setSidePanel("history");
      setLoading(false);
    }
    setPendingDelete(null);
    setDeleting(false);
  }

  const agentName = conversation?.agent_name || "Omiryn";
  const avatar = assetUrl("agent_avatar/saree_female.png");
  const usageSummary = usage?.summary || {};
  const usageEvents = usage?.events || [];
  const averageUsage = averageChatUsage(usageEvents, usageSummary);
  const usageCost = usageSummary.estimated_cost_usd ? ` · $${usageSummary.estimated_cost_usd.toFixed(6)}` : "";
  const usageInrCost = usageSummary.estimated_cost_inr ? ` / Rs ${usageSummary.estimated_cost_inr.toFixed(4)}` : "";
  const pauseRemainingSeconds = composerLimit?.until ? Math.max(0, Math.ceil((composerLimit.until - pauseNow) / 1000)) : 0;
  const composerBlocked = Boolean(composerLimit && (!composerLimit.until || pauseRemainingSeconds > 0));

  return (
    <section className="screen interview-screen legacy-chat-screen">
      <div className="chat-workspace">
        {historyOpen ? <button className="mobile-sheet-backdrop" type="button" onClick={() => setHistoryOpen(false)} aria-label="Close history" /> : null}
        <aside className={`chat-sidebar ${historyOpen ? "is-open" : ""}`}>
          <div className="mobile-sheet-heading"><div><p className="eyebrow">Chat</p><h2>History</h2></div><button className="sheet-close-button" type="button" onClick={() => setHistoryOpen(false)}>Close</button></div>
          <div className="side-tabs" role="tablist" aria-label="Chat details">
            <button className={sidePanel === "history" ? "active" : ""} type="button" onClick={() => setSidePanel("history")}>History</button>
            {canShowUsage ? <button className={sidePanel === "usage" ? "active" : ""} type="button" onClick={() => { setSidePanel("usage"); if (conversation) void loadConversationUsage(conversation.id); }}>Usage</button> : null}
          </div>
          <section className={`side-panel ${sidePanel === "history" ? "active" : ""}`} hidden={sidePanel !== "history"}>
            <p className="eyebrow">Chat History</p><h2>Conversations</h2>
            <div className="history-list">
              {summaries.map((item) => (
                <div className={`history-item ${item.id === conversation?.id ? "active" : ""}`} role="button" tabIndex={0} key={item.id} onClick={() => void openConversation(item.id)} onKeyDown={(event) => event.key === "Enter" && void openConversation(item.id)}>
                  <div className="history-item-copy"><strong>{item.agent_name || "Omiryn"}</strong><span>{item.message_count || 0} messages · {item.context_source_count || 0} signals</span><small>{item.updated_at ? new Date(item.updated_at).toLocaleString() : "New chat"}</small></div>
                  <button className="history-delete" type="button" onClick={(event) => { event.stopPropagation(); setPendingDelete(item); }} aria-label={`Delete conversation ${item.agent_name || "Omiryn"}`}><span aria-hidden="true">×</span></button>
                </div>
              ))}
            </div>
            <button className="secondary-button primary-wide" type="button" onClick={() => void createConversation()}>New conversation</button>
            <p className="quiet-note">{conversation ? `Conversation ${conversation.id.slice(0, 8)}` : "No conversation selected."}</p>
          </section>
          {canShowUsage ? (
            <section className={`side-panel ${sidePanel === "usage" ? "active" : ""}`} hidden={sidePanel !== "usage"}>
              <p className="eyebrow">Agent Usage</p><h2>Runtime cost</h2>
              <div className="usage-summary">
                {!conversation ? "Usage will appear after you select a conversation." : null}
                {conversation && usageLoading ? "Loading usage..." : null}
                {conversation && !usageLoading && usageError ? usageError : null}
                {conversation && !usageLoading && !usageError ? (
                  <>
                    <div className="sidebar-usage-total"><strong>{formatNumber(usageSummary.total_tokens || 0)}</strong><span>total tokens</span></div>
                    <div className="sidebar-usage-total"><strong>{formatNumber(averageUsage.prompt)}</strong><span>avg input / msg</span></div>
                    <div className="sidebar-usage-total"><strong>{formatNumber(averageUsage.completion)}</strong><span>avg output / msg</span></div>
                    <div>{formatNumber(usageSummary.request_count || 0)} requests · {formatNumber(usageSummary.successful_request_count || 0)} successful</div>
                    <div>{formatNumber(usageSummary.prompt_tokens || 0)} input / {formatNumber(usageSummary.completion_tokens || 0)} output{usageCost}{usageInrCost}</div>
                  </>
                ) : null}
              </div>
              <div className="sidebar-usage-list">
                {conversation && !usageLoading && !usageEvents.length ? <div className="sidebar-usage-empty">No calls yet.</div> : null}
                {usageEvents.slice(0, 6).map((event, index) => {
                  const createdAt = event.created_at ? new Date(event.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
                  const tokenText = event.total_tokens ? `${formatNumber(event.prompt_tokens || 0)} in / ${formatNumber(event.completion_tokens || 0)} out` : "tokens unavailable";
                  const totalText = event.total_tokens ? formatNumber(event.total_tokens) : "-";
                  return <div className={`sidebar-usage-item ${event.success ? "ok" : "failed"}`} key={`${event.created_at || "event"}-${index}`}><div><strong>#{usageEvents.length - index} {usageRequestKindLabel(event.request_kind)}</strong><span>{createdAt} · {event.model || event.provider || "-"}</span></div><div className="sidebar-usage-tokens"><strong>{totalText}</strong><span>{tokenText}</span></div></div>;
                })}
              </div>
            </section>
          ) : null}
        </aside>
        <section className={`chat-card agentic-chat ${loading || !conversation ? "conversation-empty" : ""}`}>
          <div className="card-heading">
            <div className="chat-title-lockup"><span className="terminal-mark"><img src={avatar} alt="" /></span><div><h2>{agentName}</h2><p className="agent-status">{runtime.provider || "Agent"} · {conversation?.agent_tone || "warm"}</p></div></div>
            <div className="chat-controls">
              <button className="secondary-button mobile-history-button" type="button" onClick={() => { setSidePanel("history"); setHistoryOpen(true); }}>History</button>
              <div className="model-picker context-multiselect chat-context-control"><span>Context</span><button className="context-picker-button" type="button" onClick={() => setContextMenuOpen((value) => !value)} aria-expanded={contextMenuOpen}>{contextSources.filter((source) => source.attached).length ? `${contextSources.filter((source) => source.attached).length} context` : "No context"}</button>{contextMenuOpen ? <div className="context-picker-menu">{contextSources.length ? contextSources.map((source) => <label className="context-picker-option" key={source.id}><input type="checkbox" checked={Boolean(source.attached)} onChange={() => void toggleContext(source.id)} /><span><strong>{source.title}</strong><small>{source.source_type}</small></span></label>) : <div className="context-picker-empty">Save memories from Style first.</div>}</div> : null}</div>
              <label className="model-picker"><span>Model</span><select value={conversation?.agent_model || runtime.model || ""} onChange={(event) => void updateModel(event.target.value)}>{(runtime.available_models || [runtime.model]).filter(Boolean).map((model) => <option value={model} key={model}>{model}</option>)}</select></label>
            </div>
          </div>
          <div className="chat-log" ref={logRef} onScroll={handleChatScroll} aria-live="polite">
            {loading ? <div className="chat-empty-state"><strong>Loading conversation...</strong><span>Fetching the latest chat and context.</span></div> : null}
            {!loading && !conversation ? <div className="chat-empty-state"><strong>No conversation selected</strong><span>Choose an existing conversation or start fresh.</span><div className="chat-empty-actions"><button className="secondary-button mobile-empty-history-button" type="button" onClick={() => { setSidePanel("history"); setHistoryOpen(true); }}>Open history</button><button type="button" onClick={() => void createConversation()}>New conversation</button></div></div> : null}
            {!loading && conversation ? <p className="privacy-note chat-session-notice">Chats may be used to create learned signals and improve your Omiryn experience. Avoid sharing secrets, IDs, or data you do not want used for personalization.</p> : null}
            {!loading && conversation?.messages.map((message, index) => {
              const agent = message.role === "assistant";
              const currentDate = messageDateKey(message, index);
              const previous = index > 0 ? conversation.messages[index - 1] : null;
              const next = index < conversation.messages.length - 1 ? conversation.messages[index + 1] : null;
              const previousDate = previous ? messageDateKey(previous, index - 1) : "";
              const nextDate = next ? messageDateKey(next, index + 1) : "";
              const sameAsPrevious = Boolean(previous && previous.role === message.role && currentDate === previousDate && minutesBetweenMessages(previous, index - 1, message, index) < 20);
              const sameAsNext = Boolean(next && next.role === message.role && currentDate === nextDate && minutesBetweenMessages(message, index, next, index + 1) < 20);
              const clusterClass = !sameAsPrevious && !sameAsNext ? "cluster-single" : !sameAsPrevious ? "cluster-start" : !sameAsNext ? "cluster-end" : "cluster-middle";
              const showTimeSeparator = !previous || currentDate !== previousDate || minutesBetweenMessages(previous, index - 1, message, index) >= 20;
              const showAvatar = !sameAsNext;
              return (
                <Fragment key={index}>
                  {showTimeSeparator ? <div className="chat-day-separator chat-time-separator" role="separator" aria-label={messageSessionLabel(message, index)} data-day-separator={currentDate}><span>{messageSessionLabel(message, index)}</span></div> : null}
                  <div className={`message-row ${agent ? "agent" : "user"} ${clusterClass} ${sameAsPrevious ? "same-cluster" : ""}`} id={`message-${index}`} data-message-index={index}>
                    {agent ? showAvatar ? <span className="chat-avatar agent"><img src={avatar} alt="" /></span> : <span className="chat-avatar-spacer" aria-hidden="true" /> : null}
                    <div className={`message ${agent ? "agent" : "user"}`}>
                      <div className="message-content">{message.content}</div>
                    </div>
                    {!agent ? showAvatar ? <span className="chat-avatar user">{userAvatar ? <img src={userAvatar} alt="" /> : "You"}</span> : <span className="chat-avatar-spacer" aria-hidden="true" /> : null}
                  </div>
                </Fragment>
              );
            })}
            {sending ? <div className="message-row agent"><span className="chat-avatar agent"><img src={avatar} alt="" /></span><div className="message agent typing-message"><div className="message-content typing-content"><span className="typing-dots"><span /><span /><span /></span></div></div></div> : null}
          </div>
          {error ? <p className="legacy-inline-error" role="alert">{error}</p> : null}
          {composerBlocked ? <p className={`composer-pause-note ${composerLimit?.kind === "monthly" ? "is-monthly" : ""}`} id="composer-pause-note" role="status">{composerLimit?.message}<span>{composerLimit?.kind === "monthly" ? `Resets in ${formatLimitCountdown(pauseRemainingSeconds)}` : `Try again in ${formatLimitCountdown(pauseRemainingSeconds)}`}</span></p> : null}
          <form className={`composer ${composerBlocked ? "is-paused" : ""}`} onSubmit={sendMessage}>
            <textarea ref={inputRef} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); if (!composerBlocked) event.currentTarget.form?.requestSubmit(); } }} placeholder={composerBlocked ? "Hold that thought..." : "Say what matters..."} rows={1} disabled={!conversation} readOnly={sending} aria-describedby={composerBlocked ? "composer-pause-note" : undefined} />
            <button type="submit" disabled={!draft.trim() || sending || composerBlocked} aria-label="Send message"><svg className="send-message-icon" viewBox="0 0 24 24"><path d="M4 20 21 12 4 4l3.3 7.2L15 12l-7.7.8L4 20Z" /></svg></button>
          </form>
        </section>
      </div>
      {pendingDelete ? <div className="confirm-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !deleting) setPendingDelete(null); }}><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-conversation-title" aria-describedby="delete-conversation-copy"><div className="confirm-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M9 3h6l1 2h4v2H4V5h4l1-2Z" /><path d="M6 9h12l-.8 11H6.8L6 9Zm4 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z" /></svg></div><div className="confirm-copy"><p className="eyebrow">Delete Conversation</p><h2 id="delete-conversation-title">Remove this chat history?</h2><p id="delete-conversation-copy">This will permanently remove the chat, attached context, and usage log for this conversation.</p><p className="confirm-session">{pendingDelete.agent_name || "Omiryn"} · {pendingDelete.message_count || 0} messages</p></div><div className="confirm-actions"><button ref={cancelDeleteRef} className="secondary-button" type="button" onClick={() => setPendingDelete(null)} disabled={deleting}>Cancel</button><button className="danger-button" type="button" onClick={() => void deleteConversation(pendingDelete.id)} disabled={deleting}>{deleting ? "Deleting…" : "Delete conversation"}</button></div></section></div> : null}
    </section>
  );
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-IN").format(value);
}

function friendlyQuotaMessage(detail: string) {
  if (detail.toLowerCase().includes("short time")) {
    return randomCooldownMessage();
  }
  if (detail.toLowerCase().includes("monthly limit")) {
    return randomMonthlyQuotaMessage();
  }
  return detail;
}

function retryAfterFromResponse(response: Response) {
  const raw = response.headers.get("X-RateLimit-Reset-Seconds") || response.headers.get("Retry-After");
  const seconds = Number(raw);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

function formatLimitCountdown(totalSeconds: number) {
  const seconds = Math.max(0, Math.ceil(totalSeconds));
  if (seconds <= 0) return "soon";
  if (seconds < 60) return `${seconds} sec`;
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.ceil(minutes / 60);
  if (hours < 24) return `${hours} hr`;
  const days = Math.ceil(hours / 24);
  return `${days} day${days === 1 ? "" : "s"}`;
}

function randomCooldownMessage() {
  const messages = [
    "Arre, aap toh bahut fast ho. Bas 1 minute do, mujhe aapki speed catch karne do.",
    "Aap rocket mode mein ho. Mujhe ek minute do replies thoughtful rakhne ke liye.",
    "Bas ek chhota sa breather. 1 minute mein phir full speed.",
    "Thoda sa pause. Omiryn ko aapki speed se sync hone do.",
    "Speed impressive hai. Main bas ek minute mein catch up karti hoon.",
    "Hold that thought. Ek minute ka tiny cooldown, phir baat continue.",
  ];
  return messages[Math.floor(Math.random() * messages.length)];
}

function randomMonthlyQuotaMessage() {
  const messages = [
    "Aaj ke liye Omiryn ka quota full ho gaya. Your draft is safe, but sending is paused until quota frees up.",
    "You have reached your chat quota for now. Thoda sa pause, thoughtful replies need some breathing room.",
    "Omiryn needs a longer breather now. Chat quota is full, and sending will unlock when quota resets.",
    "Full speed used up for this quota window. Main yahin hoon, bas sending abhi paused hai.",
  ];
  return messages[Math.floor(Math.random() * messages.length)];
}

function messageDate(message: Message, index: number) {
  const parsed = message.created_at ? new Date(message.created_at) : null;
  if (parsed && !Number.isNaN(parsed.getTime())) return parsed;
  const fallback = new Date();
  fallback.setMinutes(fallback.getMinutes() - Math.max(0, 12 - index));
  return fallback;
}

function messageDateKey(message: Message, index: number) {
  const date = messageDate(message, index);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function messageDayLabel(message: Message, index: number) {
  const date = messageDate(message, index);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "Today";
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString("en-IN", {
    weekday: date.getFullYear() === today.getFullYear() ? "short" : undefined,
    day: "numeric",
    month: "short",
    year: date.getFullYear() === today.getFullYear() ? undefined : "numeric",
  });
}

function messageTimeLabel(message: Message, index: number) {
  return messageDate(message, index).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true });
}

function minutesBetweenMessages(first: Message, firstIndex: number, second: Message, secondIndex: number) {
  return Math.abs(messageDate(second, secondIndex).getTime() - messageDate(first, firstIndex).getTime()) / 60000;
}

function messageSessionLabel(message: Message, index: number) {
  const date = messageDate(message, index);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const time = messageTimeLabel(message, index);
  if (date.toDateString() === today.toDateString()) return time;
  if (date.toDateString() === yesterday.toDateString()) return `Yesterday, ${time}`;
  const ageInDays = Math.floor((startOfDay(today).getTime() - startOfDay(date).getTime()) / 86400000);
  if (ageInDays > 1 && ageInDays < 7) {
    return `${date.toLocaleDateString("en-IN", { weekday: "long" })}, ${time}`;
  }
  return `${date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: date.getFullYear() === today.getFullYear() ? undefined : "numeric" })}, ${time}`;
}

function startOfDay(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function titleize(value: string) {
  return value.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function usageRequestKindLabel(kind?: string) {
  const labels: Record<string, string> = {
    chat_reply: "Chat reply",
    input_guardrail: "Input guardrail",
    profile_extract: "Profile draft extraction",
    profile_extract_repair: "Profile extraction repair",
    data_point_extract: "Data point extraction",
    profile_signal_extract: "Profile signal extraction",
    profile_signal_backfill: "Profile signal backfill",
    profile_fact_aggregate: "Profile fact aggregation",
    match_snapshot_generate: "Match snapshot generation"
  };
  if (!kind) return "Agent call";
  return labels[kind] || titleize(String(kind).replaceAll("_", " "));
}

function averageChatUsage(events: UsageEvent[], summary: UsageSummary = {}) {
  if (summary.average_tokens_per_message || summary.average_prompt_tokens_per_message || summary.average_completion_tokens_per_message) {
    return {
      total: summary.average_tokens_per_message || 0,
      prompt: summary.average_prompt_tokens_per_message || 0,
      completion: summary.average_completion_tokens_per_message || 0
    };
  }

  const chatEvents = events.filter((event) => event.success && event.request_kind === "chat_reply" && event.total_tokens);
  if (!chatEvents.length) return { total: 0, prompt: 0, completion: 0 };

  return {
    total: Math.round(chatEvents.reduce((total, event) => total + (event.total_tokens || 0), 0) / chatEvents.length),
    prompt: Math.round(chatEvents.reduce((total, event) => total + (event.prompt_tokens || 0), 0) / chatEvents.length),
    completion: Math.round(chatEvents.reduce((total, event) => total + (event.completion_tokens || 0), 0) / chatEvents.length)
  };
}

