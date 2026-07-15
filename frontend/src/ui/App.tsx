import { type FormEvent, useEffect, useState } from "react";
import { Menu, MessageCircle, Plus, Send, Sparkles } from "lucide-react";
import { apiErrorMessage, apiFetch, ensureAuthenticatedSession, signInWithGoogle } from "../lib/api";
import { OmirynLogo } from "./brand/OmirynLogo";
import { ProfileSetupWizard } from "./onboarding/ProfileSetupWizard";

type ConversationMessage = {
  role?: string;
  content?: string;
};

type Conversation = {
  id: string;
  agent_name?: string | null;
  messages: ConversationMessage[];
};

function useConversationId() {
  const [conversationId, setConversationId] = useState<string | null>(null);

  useEffect(() => {
    const sync = () => {
      const params = new URLSearchParams(window.location.search);
      setConversationId(params.get("conversation_id"));
    };
    sync();
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  return conversationId;
}

function ConversationApp({ conversationId }: { conversationId: string }) {
  const [activeConversationId, setActiveConversationId] = useState(conversationId);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setConversation(null);
    setError(null);

    const openConversation = async () => {
      let activeId = conversationId;
      if (activeId.startsWith("local-")) {
        window.localStorage.removeItem("omiryn-first-conversation");
        const createResponse = await apiFetch("/api/agent/conversations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent_mode: "know_me", agent_tone: "warm" })
        });
        if (!createResponse.ok) {
          throw new Error(await apiErrorMessage(createResponse, "Could not create your first conversation."));
        }
        const created = (await createResponse.json()) as Conversation;
        activeId = created.id;
        const nextUrl = new URL("/app", window.location.origin);
        nextUrl.searchParams.set("conversation_id", activeId);
        window.history.replaceState({}, "", nextUrl);
      }

      const response = await apiFetch(`/api/agent/conversations/${activeId}`);
      if (!response.ok) {
        throw new Error(await apiErrorMessage(response, "Conversation not found."));
      }
      return { activeId, data: (await response.json()) as Conversation };
    };

    openConversation()
      .then(({ activeId, data }) => {
        if (cancelled) return;
        setActiveConversationId(activeId);
        setConversation(data);
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not open conversation.");
      });

    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || isSending) return;

    setDraft("");
    setError(null);
    setIsSending(true);
    setConversation((current) => current ? {
      ...current,
      messages: [...current.messages, { role: "user", content: message }]
    } : current);

    try {
      const response = await apiFetch(`/api/agent/conversations/${activeConversationId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message })
      });
      if (!response.ok) {
        throw new Error(await apiErrorMessage(response, "Omiryn could not reply. Please retry."));
      }
      setConversation((await response.json()) as Conversation);
    } catch (caught) {
      setDraft(message);
      setError(caught instanceof Error ? caught.message : "Omiryn could not reply. Please retry.");
    } finally {
      setIsSending(false);
    }
  }

  async function startNewConversation() {
    setError(null);
    try {
      const response = await apiFetch("/api/agent/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_mode: "know_me", agent_tone: "warm" })
      });
      if (!response.ok) {
        throw new Error(await apiErrorMessage(response, "Could not start a new conversation."));
      }
      const created = (await response.json()) as Conversation;
      const nextUrl = new URL("/app", window.location.origin);
      nextUrl.searchParams.set("conversation_id", created.id);
      window.location.assign(nextUrl.toString());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not start a new conversation.");
    }
  }

  const agentName = conversation?.agent_name || "Omiryn";

  return (
    <main className="conversation-app">
      {sidebarOpen ? <button className="sidebar-backdrop" type="button" onClick={() => setSidebarOpen(false)} aria-label="Close menu" /> : null}
      <aside className={`conversation-sidebar ${sidebarOpen ? "open" : ""}`}>
        <OmirynLogo />
        <button className="new-chat-button" type="button" onClick={() => void startNewConversation()}>
          <Plus /> New conversation
        </button>
        <div className="conversation-list-label">Conversations</div>
        <button className="conversation-list-item active" type="button">
          <MessageCircle />
          <span><strong>Getting to know you</strong><small>Open now</small></span>
        </button>
      </aside>

      <section className="conversation-main">
        <header className="conversation-header">
          <button className="mobile-menu-button" type="button" onClick={() => setSidebarOpen(true)} aria-label="Open menu"><Menu /></button>
          <div className="agent-avatar"><Sparkles /></div>
          <div><strong>{agentName}</strong><span>Here with you</span></div>
        </header>

        <div className="message-scroll" aria-live="polite">
          <div className="message-column">
            {conversation?.messages.map((message, index) => (
              <article className={`chat-message ${message.role === "user" ? "user" : "assistant"}`} key={index}>
                {message.role !== "user" ? <div className="message-avatar"><Sparkles /></div> : null}
                <div className="message-bubble">{message.content}</div>
              </article>
            ))}
            {!conversation && !error ? <p className="conversation-state">Opening your conversation…</p> : null}
            {isSending ? <p className="conversation-state">{agentName} is thinking…</p> : null}
          </div>
        </div>

        <div className="composer-wrap">
          {error ? <p className="conversation-error" role="alert">{error}</p> : null}
          <form className="chat-composer" onSubmit={sendMessage}>
            <textarea
              aria-label="Message Omiryn"
              disabled={!conversation || isSending}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="Share what’s on your mind…"
              rows={1}
              value={draft}
            />
            <button type="submit" disabled={!draft.trim() || isSending} aria-label="Send message"><Send /></button>
          </form>
          <small>Your conversations stay private.</small>
        </div>
      </section>
    </main>
  );
}

export function App() {
  const [authState, setAuthState] = useState<"checking" | "signed_in" | "signed_out">("checking");
  const [authError, setAuthError] = useState<string | null>(null);
  const [isSigningIn, setIsSigningIn] = useState(false);
  const conversationId = useConversationId();

  useEffect(() => {
    let cancelled = false;
    const requireAuth = () => setAuthState("signed_out");
    window.addEventListener("omiryn:auth-required", requireAuth);
    ensureAuthenticatedSession()
      .then((ready) => {
        if (!cancelled) setAuthState(ready ? "signed_in" : "signed_out");
      })
      .catch((caught: unknown) => {
        if (!cancelled) setAuthError(caught instanceof Error ? caught.message : "Could not check sign in.");
      });
    return () => {
      cancelled = true;
      window.removeEventListener("omiryn:auth-required", requireAuth);
    };
  }, []);

  async function beginGoogleSignIn() {
    if (isSigningIn) return;
    setAuthError(null);
    setIsSigningIn(true);
    try {
      await signInWithGoogle();
    } catch (caught) {
      setAuthError(caught instanceof Error ? caught.message : "Could not start Google sign-in.");
      setIsSigningIn(false);
    }
  }

  if (authState === "checking") {
    return (
      <main className="auth-redirect-screen" aria-live="polite">
        <OmirynLogo />
        <div className="auth-redirect-spinner" aria-hidden="true" />
        <p>Checking your sign-in…</p>
      </main>
    );
  }

  if (authState === "signed_out") {
    return (
      <main className="auth-screen-page">
        <section className="auth-card">
          <OmirynLogo />
          <div className="auth-icon"><Sparkles /></div>
          <p className="eyebrow">Talk first. Match better.</p>
          <h1>Welcome to Omiryn</h1>
          <p className="auth-copy">Sign in to keep your conversations, profile, and matches securely connected to you.</p>
          <button className="google-signin-button" type="button" onClick={() => void beginGoogleSignIn()} disabled={isSigningIn}>
            <span className="google-mark" aria-hidden="true">G</span>
            {isSigningIn ? "Opening Google…" : "Continue with Google"}
          </button>
          {authError ? <p className="auth-error" role="alert">{authError}</p> : null}
          <small>By continuing, you agree to Omiryn’s Terms and Privacy Policy.</small>
        </section>
      </main>
    );
  }

  return conversationId ? <ConversationApp conversationId={conversationId} /> : <ProfileSetupWizard />;
}
