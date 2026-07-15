import { type FormEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { apiErrorMessage, apiFetch, signOut } from "../../lib/api";

type Page = "chat" | "style" | "matches" | "profile";
type Message = { role?: string; content?: string; quality?: string };
type Conversation = {
  id: string;
  status?: string;
  agent_name?: string | null;
  agent_model?: string | null;
  agent_tone?: string;
  messages: Message[];
};
type ConversationSummary = {
  id: string;
  agent_name?: string | null;
  message_count?: number;
  context_source_count?: number;
  updated_at?: string | null;
};
type AuthUser = { email?: string | null; display_name?: string | null; avatar_url?: string | null };
type Profile = {
  display_name?: string;
  age?: number;
  gender?: string;
  interested_in?: string;
  city?: string;
  phone?: string;
  profile_photo_url?: string;
  profile_photo_urls?: string[];
};
type ContextSource = {
  id: string;
  title?: string;
  source_type?: string;
  preview?: string;
  content_length?: number;
  attached?: boolean;
};
type ProfileFact = {
  id: string;
  label?: string;
  key?: string;
  category?: string;
  confidence?: number;
  status?: string;
  evidence?: unknown[];
};
type ProfileResponse = {
  user?: AuthUser;
  profile?: Profile;
  memory_sources?: ContextSource[];
  style_sources?: ContextSource[];
  learned_facts?: ProfileFact[];
  learned_fact_groups?: Record<string, ProfileFact[]>;
};
type UsageSummary = {
  request_count?: number;
  successful_request_count?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  estimated_cost_usd?: number;
  estimated_cost_inr?: number;
  average_tokens_per_message?: number;
  average_prompt_tokens_per_message?: number;
  average_completion_tokens_per_message?: number;
};
type UsageEvent = {
  request_kind?: string;
  provider?: string;
  model?: string;
  created_at?: string;
  success?: boolean;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
};
type ConversationUsage = {
  summary?: UsageSummary;
  events?: UsageEvent[];
};
const canShowUsage = import.meta.env.DEV;

const pageFromPath = (): Page => {
  if (window.location.pathname.startsWith("/style")) return "style";
  if (window.location.pathname.startsWith("/matches")) return "matches";
  if (window.location.pathname.startsWith("/profile")) return "profile";
  return "chat";
};

const pathForPage: Record<Page, string> = {
  chat: "/app",
  style: "/style",
  matches: "/matches",
  profile: "/profile"
};

const assetUrl = (path: string) => `${import.meta.env.BASE_URL}assets/${path}`;

export function MainApp({ initialConversationId }: { initialConversationId?: string | null }) {
  const [page, setPage] = useState<Page>(pageFromPath);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!canShowUsage && window.location.pathname.startsWith("/usage")) {
      window.history.replaceState({}, "", "/app");
    }
    apiFetch("/api/auth/me").then((response) => response.ok ? response.json() : null).then(setUser).catch(() => undefined);
    apiFetch("/api/me/profile")
      .then((response) => response.ok ? response.json() : null)
      .then((data: ProfileResponse | null) => setProfile(data?.profile || null))
      .catch(() => undefined);
    const sync = () => setPage(pageFromPath());
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  function navigate(next: Page) {
    window.history.pushState({}, "", pathForPage[next]);
    setPage(next);
    setMenuOpen(false);
    setAccountOpen(false);
  }

  const displayName = user?.display_name || user?.email || "Account";
  const initial = displayName.trim().slice(0, 1).toUpperCase() || "O";
  const profileAvatar = profile?.profile_photo_urls?.find(Boolean) || profile?.profile_photo_url || user?.avatar_url || null;

  return (
    <div className="app-shell legacy-react-shell">
      <header className="app-header">
        <button className="brand" type="button" onClick={() => navigate("chat")} aria-label="Omiryn home">
          <span className="brand-mark"><img src={assetUrl("omiryn-logo-neon.png")} alt="" /></span>
          <span className="brand-copy"><strong>Omiryn</strong><small>Talk first. Match better.</small></span>
        </button>
        <nav className={`app-nav ${menuOpen ? "is-open" : ""}`} aria-label="Main navigation">
          {(["chat", "style", "matches"] as Page[]).map((item) => (
            <a
              className={page === item ? "active" : ""}
              data-nav={item === "chat" ? "interview" : item}
              href={pathForPage[item]}
              key={item}
              onClick={(event) => { event.preventDefault(); navigate(item); }}
            >{item[0].toUpperCase() + item.slice(1)}</a>
          ))}
        </nav>
        <div className="header-actions">
          <button className="secondary-button menu-button" type="button" onClick={() => setMenuOpen((value) => !value)} aria-label="Open menu">
            <span className="menu-icon"><span /><span /><span /></span>
          </button>
          <div className="auth-control">
            <button className="auth-user" type="button" onClick={() => setAccountOpen((value) => !value)} aria-expanded={accountOpen}>
              <span className="auth-avatar">{profileAvatar ? <img src={profileAvatar} alt="" /> : initial}</span>
              <span className="auth-email">{displayName}</span>
            </button>
            {accountOpen ? (
              <div className="account-menu">
                <button type="button" onClick={() => navigate("profile")}>Profile</button>
                <button type="button" onClick={() => void signOut()}>Sign out</button>
              </div>
            ) : null}
          </div>
        </div>
      </header>
      <main>
        {page === "chat" ? <ChatPage initialConversationId={initialConversationId} userAvatar={profileAvatar} /> : null}
        {page === "style" ? <StylePage /> : null}
        {page === "matches" ? <MatchesPage /> : null}
        {page === "profile" ? <ProfilePage /> : null}
      </main>
    </div>
  );
}

function ChatPage({ initialConversationId, userAvatar }: { initialConversationId?: string | null; userAvatar?: string | null }) {
  const [summaries, setSummaries] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
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
      syncChatToBottomAfterRender();
      void loadConversationUsage(data.id);
      const contextResponse = await apiFetch(`/api/agent/conversations/${data.id}/context-sources`);
      if (contextResponse.ok) {
        const contextData = await contextResponse.json();
        setContextSources(contextData.available_sources || []);
      }
      window.localStorage.setItem("omiryn.activeConversationId", data.id);
      const url = new URL("/app", window.location.origin);
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

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || !conversation || sending) return;
    shouldStickToBottomRef.current = true;
    const activeElement = document.activeElement;
    shouldRestoreInputFocusRef.current = activeElement instanceof HTMLElement && Boolean(activeElement.closest(".composer"));
    setDraft("");
    setSending(true);
    setError("");
    setConversation({ ...conversation, messages: [...conversation.messages, { role: "user", content: message }] });
    syncChatToBottom();
    if (shouldRestoreInputFocusRef.current) focusComposer();
    try {
      const response = await apiFetch(`/api/agent/conversations/${conversation.id}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message })
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Omiryn could not reply."));
      const nextConversation = (await response.json()) as Conversation;
      setSending(false);
      setConversation(nextConversation);
      await fetchSummaries();
      void loadConversationUsage(nextConversation.id);
    } catch (caught) {
      setDraft(message);
      setError(caught instanceof Error ? caught.message : "Omiryn could not reply.");
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
      window.history.replaceState({}, "", "/app");
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
              <button className="secondary-button mobile-history-button" type="button" onClick={() => setHistoryOpen(true)}>History</button>
              <div className="model-picker context-multiselect chat-context-control"><span>Context</span><button className="context-picker-button" type="button" onClick={() => setContextMenuOpen((value) => !value)} aria-expanded={contextMenuOpen}>{contextSources.filter((source) => source.attached).length ? `${contextSources.filter((source) => source.attached).length} context` : "No context"}</button>{contextMenuOpen ? <div className="context-picker-menu">{contextSources.length ? contextSources.map((source) => <label className="context-picker-option" key={source.id}><input type="checkbox" checked={Boolean(source.attached)} onChange={() => void toggleContext(source.id)} /><span><strong>{source.title}</strong><small>{source.source_type}</small></span></label>) : <div className="context-picker-empty">Save memories from Style first.</div>}</div> : null}</div>
              <label className="model-picker"><span>Model</span><select value={conversation?.agent_model || runtime.model || ""} onChange={(event) => void updateModel(event.target.value)}>{(runtime.available_models || [runtime.model]).filter(Boolean).map((model) => <option value={model} key={model}>{model}</option>)}</select></label>
            </div>
          </div>
          <div className="chat-log" ref={logRef} onScroll={() => { shouldStickToBottomRef.current = isLogNearBottom(); }} aria-live="polite">
            {loading ? <div className="chat-empty-state"><strong>Loading conversation...</strong><span>Fetching the latest chat and context.</span></div> : null}
            {!loading && !conversation ? <div className="chat-empty-state"><strong>No conversation selected</strong><span>Choose a conversation from History or start a new chat.</span></div> : null}
            {!loading && conversation?.messages.map((message, index) => {
              const agent = message.role === "assistant";
              return <div className={`message-row ${agent ? "agent" : "user"}`} key={index}>{agent ? <span className="chat-avatar agent"><img src={avatar} alt="" /></span> : null}<div className={`message ${agent ? "agent" : "user"}`}><div className="message-content">{message.content}</div></div>{!agent ? <span className="chat-avatar user">{userAvatar ? <img src={userAvatar} alt="" /> : "You"}</span> : null}</div>;
            })}
            {sending ? <div className="message-row agent"><span className="chat-avatar agent"><img src={avatar} alt="" /></span><div className="message agent typing-message"><div className="message-content typing-content"><span className="typing-dots"><span /><span /><span /></span></div></div></div> : null}
          </div>
          {error ? <p className="legacy-inline-error" role="alert">{error}</p> : null}
          <form className="composer" onSubmit={sendMessage}>
            <textarea ref={inputRef} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="Say what matters..." rows={1} disabled={!conversation} readOnly={sending} />
            <button type="submit" disabled={!draft.trim() || sending} aria-label="Send message"><svg className="send-message-icon" viewBox="0 0 24 24"><path d="M4 20 21 12 4 4l3.3 7.2L15 12l-7.7.8L4 20Z" /></svg></button>
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

function StylePage() {
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [error, setError] = useState("");
  const [showImport, setShowImport] = useState(false);
  const [importMode, setImportMode] = useState<"memory" | "whatsapp">("memory");
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("Imported context");
  const [userSender, setUserSender] = useState("");
  const [saving, setSaving] = useState(false);

  async function load() {
    const response = await apiFetch("/api/me/profile");
    if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not load saved memories."));
    setData(await response.json());
  }
  useEffect(() => { load().catch((caught) => setError(caught.message)); }, []);

  const sources = [...(data?.memory_sources || []), ...(data?.style_sources || [])];
  const facts = data?.learned_facts || [];

  async function importContext(event: FormEvent) {
    event.preventDefault();
    if (content.trim().length < 20) return;
    setSaving(true);
    setError("");
    try {
      let listResponse = await apiFetch("/api/agent/conversations");
      const list = await listResponse.json();
      let conversationId = list.conversations?.[0]?.id as string | undefined;
      if (!conversationId) {
        const createResponse = await apiFetch("/api/agent/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ agent_mode: "know_me" }) });
        conversationId = (await createResponse.json()).id;
      }
      const endpoint = importMode === "whatsapp"
        ? `/api/agent/conversations/${conversationId}/whatsapp-import`
        : `/api/agent/conversations/${conversationId}/context-sources`;
      const payload = importMode === "whatsapp"
        ? { title: title.trim(), content: content.trim(), user_sender: userSender.trim() || null, style_kind: "user_style", style_name: title.trim() }
        : { source_type: "llm_profile", title: title.trim(), content: content.trim() };
      const response = await apiFetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not save memory."));
      setContent(""); setShowImport(false); await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not save memory."); }
    finally { setSaving(false); }
  }

  async function removeSource(id: string) {
    const response = await apiFetch(`/api/me/context-sources/${id}`, { method: "DELETE" });
    if (response.ok) await load();
  }

  return <section className="screen style-screen"><div className="style-hero"><div className="screen-copy compact"><p className="eyebrow">Style</p><h1>Saved memories.</h1><p>Keep useful context and imported chat references in one simple library.</p></div></div><div className="style-layout">
    <section className="profile-panel profile-panel-wide style-context-panel"><div className="context-intro"><span className="context-visual">M</span><div><p className="eyebrow">Library</p><h2>Saved memories</h2><p>Use WhatsApp exports or pasted GPT summaries to give Omiryn better context.</p></div></div>
      <div className="context-card context-card-muted"><div className="context-card-heading"><span className="context-card-icon">✓</span><div><h3>Saved memories</h3><p>These sources can shape chat and matching signals when useful.</p></div></div><div className="context-source-list">{sources.length ? sources.map((source) => <article className="profile-source-item" key={source.id}><div><strong>{source.title}</strong><span>{source.source_type} · {source.content_length || 0} chars</span></div><p>{source.preview}</p><button className="secondary-button" type="button" onClick={() => void removeSource(source.id)}>Remove</button></article>) : <div className="table-empty">No saved memories yet.</div>}</div></div>
      <div className="context-action-grid"><button className="context-action-button" type="button" onClick={() => { setImportMode("whatsapp"); setTitle("My WhatsApp style"); setShowImport(true); }}><span className="context-card-icon">Aa</span><strong>Upload WhatsApp chat</strong><small>Learn tone from a WhatsApp export.</small></button><button className="context-action-button" type="button" onClick={() => { setImportMode("memory"); setTitle("Imported context"); setShowImport(true); }}><span className="context-card-icon">+</span><strong>Paste GPT content</strong><small>Paste a profile summary, chat export, or notes.</small></button></div>
      {showImport ? <form className="react-memory-form" onSubmit={importContext}><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Memory title" />{importMode === "whatsapp" ? <><input type="file" accept=".txt,text/plain" onChange={(event) => { const file = event.target.files?.[0]; if (file) void file.text().then(setContent); }} /><input value={userSender} onChange={(event) => setUserSender(event.target.value)} placeholder="Your sender name (optional)" /></> : null}<textarea value={content} onChange={(event) => setContent(event.target.value)} rows={7} placeholder={importMode === "whatsapp" ? "Choose a WhatsApp .txt export or paste it here…" : "Paste at least 20 characters…"} /><div><button className="secondary-button" type="button" onClick={() => setShowImport(false)}>Cancel</button><button type="submit" disabled={saving || content.trim().length < (importMode === "whatsapp" ? 50 : 20)}>{saving ? "Saving…" : importMode === "whatsapp" ? "Import chat" : "Save memory"}</button></div></form> : null}
      {error ? <p className="legacy-inline-error">{error}</p> : null}
    </section>
    <section className="profile-panel profile-panel-wide style-learning-panel"><div className="panel-heading profile-facts-heading"><div><p className="eyebrow">Learned About You</p><h2>Internal matching signals</h2></div><span className="profile-fact-total">{facts.length} facts</span></div><div className="profile-fact-groups">{facts.length ? Object.entries(data?.learned_fact_groups || {}).map(([category, rows]) => <section className="profile-fact-group" key={category}><div className="profile-fact-group-heading"><h3>{category.replaceAll("_", " ")}</h3><span>{rows.length} signals</span></div><div className="profile-fact-list">{rows.map((fact) => <article className="profile-fact-card" key={fact.id}><div className="profile-fact-card-top"><strong>{fact.label || fact.key}</strong><span className="confidence-pill">{Math.round((fact.confidence || 0) * 100)}%</span></div><div className="profile-fact-meta"><span className="fact-tag fact-tag-key">{fact.key}</span><span className="fact-tag fact-tag-status">{fact.status || "active"}</span></div></article>)}</div></section>) : <div className="profile-facts-empty"><strong>No learned signals yet.</strong><span>Chat naturally with Omiryn and this section will fill up.</span></div>}</div></section>
  </div></section>;
}

function MatchesPage() {
  return <section className="screen matches-screen"><div className="matches-coming-soon"><div className="coming-soon-mark" aria-hidden="true"><span /></div><p className="eyebrow">Matches</p><h1>Coming soon.</h1><p>Omiryn is still learning how to turn your conversations, memories, and preferences into thoughtful introductions.</p><div className="coming-soon-notes"><span>Private by default</span><span>Compatibility-first</span><span>No swipe noise</span></div></div></section>;
}

function ProfilePage() {
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [form, setForm] = useState<Profile>({});
  const [status, setStatus] = useState("Loading profile…");
  const photoInput = useRef<HTMLInputElement | null>(null);
  const [photoSlot, setPhotoSlot] = useState(0);
  const [uploadingPhotoSlot, setUploadingPhotoSlot] = useState<number | null>(null);
  async function load() { const response = await apiFetch("/api/me/profile"); if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not load profile.")); const next = await response.json() as ProfileResponse; setData(next); setForm(next.profile || {}); setStatus(""); }
  useEffect(() => { load().catch((caught) => setStatus(caught.message)); }, []);
  async function save(event: FormEvent) { event.preventDefault(); setStatus("Saving profile…"); const response = await apiFetch("/api/me/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name: form.display_name || null, age: Number(form.age), gender: form.gender, interested_in: form.interested_in, city: form.city || null, phone: form.phone || null }) }); if (!response.ok) { setStatus(await apiErrorMessage(response, "Could not save profile.")); return; } setStatus("Profile saved."); await load(); }
  async function upload(file?: File) {
    if (!file) return;
    const slot = photoSlot;
    setUploadingPhotoSlot(slot);
    setStatus("Uploading photo...");
    try {
      const response = await apiFetch(`/api/me/profile-photo?slot=${slot}`, { method: "PUT", headers: { "Content-Type": file.type }, body: await file.arrayBuffer() });
      if (!response.ok) {
        setStatus(await apiErrorMessage(response, "Could not upload photo."));
        return;
      }
      await load();
      setStatus("Photo uploaded.");
    } finally {
      setUploadingPhotoSlot(null);
      if (photoInput.current) photoInput.current.value = "";
    }
  }
  const photos = form.profile_photo_urls?.length ? form.profile_photo_urls : form.profile_photo_url ? [form.profile_photo_url] : [];
  return <section className="screen profile-screen"><div className="usage-hero"><div className="screen-copy compact"><p className="eyebrow">Profile</p><h1>Your profile.</h1><p>Keep photos, basics, and match direction clean before conversation takes over.</p></div></div><div className="profile-layout">
    <section className="profile-panel profile-photo-panel"><div className="panel-heading"><div><p className="eyebrow">Photos</p><h2>Profile gallery</h2></div><input ref={photoInput} className="profile-photo-input" type="file" accept="image/*" onChange={(event) => void upload(event.target.files?.[0])} /></div><div className="profile-photo-gallery"><button className={`profile-main-photo ${photos[0] ? "has-photo" : ""} ${uploadingPhotoSlot === 0 ? "is-uploading" : ""}`} type="button" disabled={uploadingPhotoSlot !== null} onClick={() => { setPhotoSlot(0); photoInput.current?.click(); }}>{photos[0] ? <img className="profile-gallery-img" src={photos[0]} alt="Profile" /> : <span className="profile-photo-empty">{form.display_name?.slice(0, 1) || "O"}</span>}{uploadingPhotoSlot === 0 ? <span className="profile-upload-overlay"><span className="profile-upload-spinner" />Uploading...</span> : null}<span className="profile-main-badge">Main photo</span></button><div className="profile-thumb-stack">{[1,2,3].map((slot) => <button className={`profile-thumb ${photos[slot] ? "has-photo" : ""} ${uploadingPhotoSlot === slot ? "is-uploading" : ""}`} type="button" key={slot} disabled={uploadingPhotoSlot !== null} onClick={() => { setPhotoSlot(slot); photoInput.current?.click(); }}>{photos[slot] ? <img className="profile-gallery-img" src={photos[slot]} alt={`Profile ${slot + 1}`} /> : <span className="profile-photo-empty">+</span>}{uploadingPhotoSlot === slot ? <span className="profile-upload-overlay"><span className="profile-upload-spinner" />Uploading...</span> : null}</button>)}</div></div><div className="profile-photo-copy"><strong>Show the real you.</strong><span>Upload up to 4 clear photos.</span></div></section>
    <section className="profile-panel profile-info-panel"><div className="panel-heading"><div><p className="eyebrow">Account</p><h2>Basic info</h2></div></div><form className="profile-form" onSubmit={save}><label>Name<input value={form.display_name || ""} onChange={(e) => setForm({...form, display_name:e.target.value})} /></label><label>Age<input type="number" min="18" max="100" value={form.age || ""} onChange={(e) => setForm({...form, age:Number(e.target.value)})} /></label><label>Email<input value={data?.user?.email || ""} readOnly /></label><label>Gender<select value={form.gender || "prefer_not_to_say"} onChange={(e) => setForm({...form, gender:e.target.value})}><option value="man">Man</option><option value="woman">Woman</option><option value="non_binary">Non-binary</option><option value="prefer_not_to_say">Prefer not to say</option></select></label><label>Interested in<select value={form.interested_in || "everyone"} onChange={(e) => setForm({...form, interested_in:e.target.value})}><option value="women">Women</option><option value="men">Men</option><option value="everyone">Everyone</option></select></label><label className="wide-field">Location<input value={form.city || ""} onChange={(e) => setForm({...form, city:e.target.value})} /></label><label className="wide-field">Mobile (optional)<input type="tel" value={form.phone || ""} onChange={(e) => setForm({...form, phone:e.target.value})} /></label><button type="submit">Save profile</button><p className="quiet-note">{status}</p></form></section>
  </div></section>;
}
