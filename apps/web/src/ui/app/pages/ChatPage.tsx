import { Fragment, lazy, Suspense, useMemo, type Dispatch, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type SetStateAction, type TouchEvent as ReactTouchEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { EmojiClickData, EmojiStyle, Theme } from "emoji-picker-react";
import { Archive, ArchiveRestore, BarChart3, Check, ChevronRight, Copy, History, MessageCircleDashed, ListChecks, Lock, Menu, MoreHorizontal, Reply, RotateCw, Smile, Sparkles, Trash2, X } from "lucide-react";
import { apiErrorDetail, apiErrorMessage, apiFetch } from "../../../lib/api";
import { trackAppEvent } from "../../../lib/appLogger";
import { RealtimeClient, type RealtimeEvent } from "../../../lib/realtime";
import { AgentOrb } from "../AgentOrb";
import { AvatarImage } from "../AvatarImage";
import { nextBubbleDelay } from "../bubbleReveal";
import { notedLinesByMessage, type NotedLine } from "../notedLines";
import { Notice, StateView } from "../StateView";
import { isUnread, loadSeen, markSeen, saveSeen, withNewChatsSeen, type SeenCounts } from "../unread";
import { isFailedMessage } from "../messageDelivery";
import { isDeletedMessage, markDeleted, messageDeletionImpactLines, replyQuoteFor, replyQuoteLabel, toggleSelected, type MessageDeletionImpact } from "../messageSelection";
import { AGENT_TYPING_TIMEOUT_MS, typingAfterEvent } from "../agentTyping";
import { canShowUsage, pathForPage } from "../appUtils";
import { type DeletionImpact, type Vibe, type VibeArea, deletionImpactLines, milestoneFromEvent, vibeStepNote } from "../vibe";
import { findEmojiQuery, loadEmojiRecords, replaceEmojiQuery, searchEmojiSuggestions, type EmojiQuery, type EmojiRecord, type EmojiSuggestion } from "../emojiShortcodes";
import type { ContextSource, Conversation, ConversationSummary, ConversationUsage, Message, MessageRecovery, ReplyQuote, UsageEvent, UsageSummary } from "../types";
import { cognitionResultLabel } from "../usagePresentation";

const EmojiPicker = lazy(() => import("emoji-picker-react"));
const CHAT_INPUT_MAX_LENGTH = 800;
// Four menu items plus padding, in pixels.
const MESSAGE_MENU_HEIGHT = 190;

// One ongoing chat with Omi; older chats open read-only from the "Earlier chats" drawer.
export type OmiStatus = { typing: boolean; preview: string; viewingEarlier: boolean };

export function ChatPage({ initialConversationId, userAvatar, onOpenNavigation, onOmiStatus }: { initialConversationId?: string | null; userAvatar?: string | null; onOpenNavigation?: () => void; onOmiStatus?: (status: OmiStatus) => void }) {
  const [summaries, setSummaries] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  // Chats waiting on a reply. Each chat has its own: switching chats never carries the typing state.
  const [sendingIds, setSendingIds] = useState<ReadonlySet<string>>(() => new Set());
  // How many messages are on screen; later bubbles of one reply are revealed one by one.
  const [shownCount, setShownCount] = useState(0);
  // Set after a reply has been pending a while, to say so under the typing dots.
  const [slowReply, setSlowReply] = useState(false);
  // Conversation where the companion is writing a message of its own (from realtime).
  const [typingConversationId, setTypingConversationId] = useState<string | null>(null);
  // A vibe milestone reached while this chat is open.
  const [vibeNote, setVibeNote] = useState<{ conversationId: string; milestone: string } | null>(null);
  const shownConversationIdRef = useRef<string | null>(null);
  const sending = Boolean(conversation && sendingIds.has(conversation.id));
  // Messages seen per chat; a chat with more is highlighted in History instead of opening by itself.
  const [seen, setSeen] = useState<SeenCounts>(loadSeen);
  // The chat the user picked; the History row highlights at once, before the chat finishes loading.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const openRequestRef = useRef(0);
  // Chats already opened this session, so going back to one is instant.
  const conversationCacheRef = useRef(new Map<string, Conversation>());
  // Whether History shows the archived chats under the main list.
  const [archivedOpen, setArchivedOpen] = useState(false);
  // History row whose "more" menu is open.
  const [rowMenuId, setRowMenuId] = useState<string | null>(null);
  // The chat on screen right now, for replies that land after the user has moved on.
  const openConversationIdRef = useRef<string | null>(null);
  openConversationIdRef.current = conversation?.id ?? null;
  // Messages from this index on arrived while the chat was open, so they fade in; history does not.
  const newFromIndexRef = useRef(0);
  const [error, setError] = useState("");
  const [composerLimit, setComposerLimit] = useState<{ until?: number; message: string; kind: "burst" | "monthly" } | null>(null);
  const [pauseNow, setPauseNow] = useState(() => Date.now());
  // Right-side drawer: earlier chats, or usage (dev only). The chat stays open beside it.
  const [drawer, setDrawer] = useState<"earlier" | "usage" | null>(null);
  const [chatMenuOpen, setChatMenuOpen] = useState(false);
  // The temporary chat on screen, deleted once the user leaves it.
  const temporaryIdRef = useRef<string | null>(null);
  const chatMenuRef = useRef<HTMLDivElement | null>(null);
  // Vibe lines, to show "Noted: ..." under the reply where Omi learned each one.
  const [vibeAreas, setVibeAreas] = useState<VibeArea[]>([]);
  const [rejectingArea, setRejectingArea] = useState<string | null>(null);
  const [runtime, setRuntime] = useState<{ provider?: string; model?: string; available_models?: string[] }>({});
  const [contextSources, setContextSources] = useState<ContextSource[]>([]);
  const [contextMenuOpen, setContextMenuOpen] = useState(false);
  const [usage, setUsage] = useState<ConversationUsage | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageError, setUsageError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<ConversationSummary | null>(null);
  // What deleting the pending chat also removes; null while loading or unknown.
  const [deleteImpact, setDeleteImpact] = useState<DeletionImpact | null>(null);
  const [deleting, setDeleting] = useState(false);
  // Select mode: pick messages to delete, see what goes with them, then confirm.
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [messageImpact, setMessageImpact] = useState<MessageDeletionImpact | null>(null);
  const [confirmingMessages, setConfirmingMessages] = useState(false);
  const [deletingMessages, setDeletingMessages] = useState(false);
  const [clearEverything, setClearEverything] = useState(false);
  const [clearWord, setClearWord] = useState("");
  const longPressRef = useRef<number | null>(null);
  // The ⋯ menu open on one message, and the message the next send replies to.
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [menuUp, setMenuUp] = useState(false);
  const [replyTo, setReplyTo] = useState<ReplyQuote | null>(null);
  useEffect(() => {
    // A selection, an open menu and a reply belong to one chat.
    setSelecting(false);
    setSelected([]);
    setConfirmingMessages(false);
    setMenuFor(null);
    setReplyTo(null);
  }, [conversation?.id]);

  useEffect(() => {
    if (menuFor === null) return;
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent && event.key !== "Escape") return;
      if (event instanceof MouseEvent && (event.target as HTMLElement | null)?.closest(".message-menu")) return;
      setMenuFor(null);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [menuFor]);
  const [emojiPickerOpen, setEmojiPickerOpen] = useState(false);
  const [emojiQuery, setEmojiQuery] = useState<EmojiQuery | null>(null);
  const [emojiSuggestions, setEmojiSuggestions] = useState<EmojiSuggestion[]>([]);
  const [selectedEmojiSuggestion, setSelectedEmojiSuggestion] = useState(0);
  const [limitNoticeVersion, setLimitNoticeVersion] = useState(0);
  const cancelDeleteRef = useRef<HTMLButtonElement | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const emojiPickerRef = useRef<HTMLDivElement | null>(null);
  const composerPauseTimerRef = useRef<number | null>(null);
  const initializedRef = useRef(false);
  const shouldStickToBottomRef = useRef(true);
  const handledEvidenceTargetRef = useRef("");
  const realtimeClientRef = useRef<RealtimeClient | null>(null);
  const emojiRecordsRef = useRef<EmojiRecord[] | null>(null);
  const emojiSearchVersionRef = useRef(0);

  useEffect(() => {
    const realtime = new RealtimeClient(
      (event) => {
        setTypingConversationId((current) => typingAfterEvent(event, current));
        const milestone = milestoneFromEvent(event, event.scope_id ?? null);
        if (milestone && event.scope_id) setVibeNote({ conversationId: event.scope_id, milestone });
        applyRealtimeEvent(event, setConversation);
      },
      (conversationId, afterSequence) => recoverConversation(conversationId, afterSequence),
    );
    realtimeClientRef.current = realtime;
    realtime.start();
    return () => {
      realtime.stop();
      if (realtimeClientRef.current === realtime) realtimeClientRef.current = null;
    };
  }, []);

  useEffect(() => {
    realtimeClientRef.current?.setConversation(
      conversation?.id || null,
      conversation ? conversation.messages.length - 1 : undefined,
    );
  }, [conversation?.id]);

  async function fetchSummaries() {
    const response = await apiFetch("/api/agent/conversations");
    if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not load chat history."));
    const data = await response.json();
    const rows = sortConversationSummaries((data.conversations || []) as ConversationSummary[]);
    setSummaries(rows);
    setSeen((current) => withNewChatsSeen(current, rows));
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
    // Only the latest click wins; a slow earlier load never replaces a later choice.
    const request = ++openRequestRef.current;
    const isLatest = () => openRequestRef.current === request;
    setSelectedId(id);
    setError("");
    setDrawer(null);
    const targetHash = window.location.hash.startsWith("#message-") ? window.location.hash : "";
    shouldStickToBottomRef.current = !targetHash;
    setUsage(null);
    setUsageError("");
    // A chat opened before shows at once from memory, then refreshes quietly.
    const cached = conversationCacheRef.current.get(id);
    if (cached) {
      setConversation(cached);
      setLoading(false);
      if (!targetHash) syncChatToBottomAfterRender();
    } else {
      setLoading(true);
    }
    window.localStorage.setItem("omiryn.activeConversationId", id);
    const url = new URL("/", window.location.origin);
    url.searchParams.set("conversation_id", id);
    url.hash = targetHash;
    window.history.replaceState({}, "", url);
    try {
      const response = await apiFetch(`/api/agent/conversations/${id}`);
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not load that conversation."));
      const data = (await response.json()) as Conversation;
      if (!isLatest()) return;
      setConversation(data);
      trackAppEvent("chat_opened", { conversation_id: data.id }, { page: "chat", target_type: "conversation", target_id: data.id });
      if (!cached && !targetHash) syncChatToBottomAfterRender();
      void loadConversationUsage(data.id);
      void loadContextSources(data.id, isLatest);
    } catch (caught) {
      if (isLatest()) setError(caught instanceof Error ? caught.message : "Could not load conversation.");
    } finally {
      if (isLatest()) setLoading(false);
    }
  }

  // Context sources load after the chat is on screen; they never hold it back.
  async function loadContextSources(id: string, isLatest: () => boolean) {
    try {
      const response = await apiFetch(`/api/agent/conversations/${id}/context-sources`);
      if (!response.ok || !isLatest()) return;
      const data = await response.json();
      setContextSources(data.available_sources || []);
    } catch {
      // Optional panel data; the chat works without it.
    }
  }

  async function recoverConversation(id: string, afterSequence: number | null) {
    const query = new URLSearchParams({ after_sequence: String(afterSequence ?? -1) });
    const response = await apiFetch(`/api/agent/conversations/${id}/messages?${query}`);
    if (!response.ok) return null;
    const recovered = (await response.json()) as MessageRecovery;
    setConversation((current) => {
      if (!current || current.id !== id) return current;
      const messages = [...current.messages];
      for (const item of recovered.messages) {
        if (!Number.isInteger(item.message_index) || item.message_index < 0) continue;
        if (item.message_index < messages.length) messages[item.message_index] = item.message;
        else if (item.message_index === messages.length) messages.push(item.message);
      }
      return { ...current, messages };
    });
    return recovered.latest_sequence;
  }

  // Temporary Chat: not in History and not learned from. It is deleted as soon as the user
  // leaves it (End, another chat, another page); the server sweeps any left open after a day.
  async function startTemporaryChat() {
    setError("");
    try {
      const response = await apiFetch("/api/agent/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_mode: "know_me", agent_tone: "warm", agent_model: runtime.model || null, temporary: true })
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not start a temporary chat."));
      const created = (await response.json()) as Conversation;
      ++openRequestRef.current;
      setSelectedId(created.id);
      setDrawer(null);
      shouldStickToBottomRef.current = true;
      setConversation(created);
      syncChatToBottomAfterRender();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not start a temporary chat.");
    }
  }

  function endTemporaryChat() {
    const mainId = omiThreadId(summaries);
    if (mainId) void openConversation(mainId);
    else void createConversation();
  }

  useEffect(() => {
    const previous = temporaryIdRef.current;
    if (previous && previous !== conversation?.id) {
      conversationCacheRef.current.delete(previous);
      void apiFetch(`/api/agent/conversations/${previous}`, { method: "DELETE" });
    }
    temporaryIdRef.current = conversation?.temporary ? conversation.id : null;
  }, [conversation?.id]);

  useEffect(() => () => {
    if (temporaryIdRef.current) void apiFetch(`/api/agent/conversations/${temporaryIdRef.current}`, { method: "DELETE" });
  }, []);

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
      const urlConversationId = new URLSearchParams(window.location.search).get("conversation_id");
      const availableIds = new Set(rows.map((row) => row.id));
      // A link to a message (Vibe proof) may open an earlier chat; otherwise it is always Omi's thread.
      const linked = [urlConversationId, initialConversationId].find((id) => id && availableIds.has(id));
      const preferred = linked || omiThreadId(rows);
      if (preferred) return openConversation(preferred);
      window.localStorage.removeItem("omiryn.activeConversationId");
      return createConversation();
    }).catch((caught) => {
      setError(caught instanceof Error ? caught.message : "Could not open chat.");
      setLoading(false);
    });
  }, []);

  useLayoutEffect(() => {
    if (loading || !conversation || !window.location.hash.startsWith("#message-")) return;
    const targetId = window.location.hash.slice(1);
    const targetKey = `${conversation.id}:${targetId}`;
    if (handledEvidenceTargetRef.current === targetKey) return;
    handledEvidenceTargetRef.current = targetKey;
    window.requestAnimationFrame(() => {
      const target = document.getElementById(targetId);
      if (!target) return;
      target.scrollIntoView({ block: "center" });
      target.classList.add("evidence-highlight");
      window.setTimeout(() => target.classList.remove("evidence-highlight"), 2400);
    });
  }, [conversation?.id, conversation?.messages.length, loading]);

  function isLogNearBottom() {
    const log = logRef.current;
    if (!log) return true;
    return log.scrollHeight - log.scrollTop - log.clientHeight < 120;
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
    const messages = conversation?.messages ?? [];
    // A newly opened conversation, or a rolled-back one, shows everything at once.
    if (shownConversationIdRef.current !== (conversation?.id ?? null) || messages.length < shownCount) {
      if (shownConversationIdRef.current !== (conversation?.id ?? null)) newFromIndexRef.current = messages.length;
      shownConversationIdRef.current = conversation?.id ?? null;
      setShownCount(messages.length);
      return;
    }
    if (messages.length <= shownCount) return;
    const delay = nextBubbleDelay(messages, shownCount);
    if (delay === 0) {
      setShownCount(shownCount + 1);
      return;
    }
    const timer = window.setTimeout(() => setShownCount((count) => count + 1), delay);
    return () => window.clearTimeout(timer);
  }, [conversation, shownCount]);

  useEffect(() => {
    if (!typingConversationId) return;
    const timer = window.setTimeout(() => setTypingConversationId(null), AGENT_TYPING_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [typingConversationId]);

  useEffect(() => {
    setSlowReply(false);
    if (!sending) return;
    const timer = window.setTimeout(() => setSlowReply(true), SLOW_REPLY_MS);
    return () => window.clearTimeout(timer);
  }, [sending]);

  useEffect(() => {
    if (conversation) setSeen((current) => markSeen(current, conversation.id, conversation.messages.length));
  }, [conversation?.id, conversation?.messages.length]);

  useEffect(() => saveSeen(seen), [seen]);

  // Omi's own messages can land in other chats while the user is elsewhere; refresh History on return.
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") void fetchSummaries().catch(() => undefined);
    };
    document.addEventListener("visibilitychange", refresh);
    return () => document.removeEventListener("visibilitychange", refresh);
  }, []);

  useEffect(() => {
    if (!rowMenuId) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !(event.target instanceof Element && event.target.closest(".history-row-menu"))) setRowMenuId(null);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [rowMenuId]);

  useEffect(() => {
    if (conversation) conversationCacheRef.current.set(conversation.id, conversation);
  }, [conversation]);

  useEffect(() => {
    if (!chatMenuOpen) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !(event.target instanceof Node && chatMenuRef.current?.contains(event.target))) setChatMenuOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [chatMenuOpen]);

  useEffect(() => {
    if (!drawer) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setDrawer(null); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [drawer]);

  // Vibe lines are written in the background a little after a reply, so refresh a few seconds
  // after the chat changes, and when the user comes back to the tab.
  const messageCount = conversation?.messages.length ?? 0;
  useEffect(() => {
    if (!conversation) return;
    const timer = window.setTimeout(() => void loadVibeAreas(), messageCount ? 4000 : 0);
    return () => window.clearTimeout(timer);
  }, [conversation?.id, messageCount]);

  useEffect(() => {
    const refresh = () => { if (document.visibilityState === "visible") void loadVibeAreas(); };
    document.addEventListener("visibilitychange", refresh);
    return () => document.removeEventListener("visibilitychange", refresh);
  }, []);

  async function loadVibeAreas() {
    try {
      const response = await apiFetch("/api/me/vibe");
      if (response.ok) setVibeAreas(((await response.json()) as Vibe).areas || []);
    } catch {
      // Optional: the chat works without the notes.
    }
  }

  async function rejectNoted(areaId: string) {
    setRejectingArea(areaId);
    try {
      const response = await apiFetch(`/api/me/vibe/${areaId}`, { method: "DELETE" });
      if (response.ok) setVibeAreas(((await response.json()) as Vibe).areas || []);
    } finally {
      setRejectingArea(null);
    }
  }

  const openId = selectedId ?? conversation?.id ?? null;
  const omiId = omiThreadId(summaries);
  const temporary = Boolean(conversation?.temporary);
  const viewingEarlier = Boolean(conversation && omiId && conversation.id !== omiId && !temporary);
  const earlierUnread = summaries.some((item) => item.id !== omiId && !item.archived_at && isUnread(item, seen, openId));
  const visibleMessages = conversation ? conversation.messages.slice(0, shownCount) : [];
  const revealingBubbles = Boolean(conversation && shownCount < conversation.messages.length);
  const typingVisible = sending || revealingBubbles || Boolean(conversation && typingConversationId === conversation.id);
  const lastVisibleIsAgent = visibleMessages.length > 0 && visibleMessages[visibleMessages.length - 1].role === "assistant";
  // Tell the contacts rail what Omi is doing: typing, its last line, or that an earlier chat is open.
  const omiTyping = Boolean(omiId && (sendingIds.has(omiId) || typingConversationId === omiId || (conversation?.id === omiId && typingVisible)));
  const lastShown = conversation?.id === omiId ? [...visibleMessages].reverse().find((message) => message.content)?.content || "" : "";
  useEffect(() => {
    onOmiStatus?.({ typing: omiTyping, preview: lastShown, viewingEarlier });
  }, [omiTyping, lastShown, viewingEarlier]);

  useLayoutEffect(() => {
    if (!shouldStickToBottomRef.current) return;
    syncChatToBottomAfterRender();
  }, [conversation?.id, shownCount, loading, sending]);

  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    const maxHeight = 126;
    input.style.height = "0px";
    input.style.height = `${Math.min(input.scrollHeight, maxHeight)}px`;
    input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [draft]);

  useEffect(() => {
    if (!limitNoticeVersion) return;
    const timeout = window.setTimeout(() => setLimitNoticeVersion(0), 2200);
    return () => window.clearTimeout(timeout);
  }, [limitNoticeVersion]);

  useEffect(() => {
    return () => {
      if (composerPauseTimerRef.current !== null) window.clearInterval(composerPauseTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!emojiPickerOpen) return;
    const closePicker = (event: MouseEvent) => {
      const target = event.target;
      if (target instanceof Node && emojiPickerRef.current?.contains(target)) return;
      setEmojiPickerOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setEmojiPickerOpen(false);
    };
    window.addEventListener("mousedown", closePicker);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("mousedown", closePicker);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [emojiPickerOpen]);


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

  function insertEmoji(emojiData: EmojiClickData) {
    closeEmojiShortcodeSuggestions();
    const emoji = emojiData.emoji;
    const input = inputRef.current;
    const start = input?.selectionStart ?? draft.length;
    const end = input?.selectionEnd ?? draft.length;
    const proposedDraft = `${draft.slice(0, start)}${emoji}${draft.slice(end)}`;
    if (characterCount(proposedDraft) > CHAT_INPUT_MAX_LENGTH) setLimitNoticeVersion((version) => version + 1);
    const nextDraft = limitCharacters(proposedDraft, CHAT_INPUT_MAX_LENGTH);
    setDraft(nextDraft);
    window.requestAnimationFrame(() => {
      input?.focus();
      const nextCursor = Math.min(start + emoji.length, nextDraft.length);
      input?.setSelectionRange(nextCursor, nextCursor);
    });
  }

  function updateDraft(value: string, cursor: number) {
    if (characterCount(value) > CHAT_INPUT_MAX_LENGTH) setLimitNoticeVersion((version) => version + 1);
    const nextDraft = limitCharacters(value, CHAT_INPUT_MAX_LENGTH);
    setDraft(nextDraft);
    void refreshEmojiShortcodeSuggestions(nextDraft, Math.min(cursor, nextDraft.length));
  }

  function closeEmojiShortcodeSuggestions() {
    emojiSearchVersionRef.current += 1;
    setEmojiQuery(null);
    setEmojiSuggestions([]);
    setSelectedEmojiSuggestion(0);
  }

  async function refreshEmojiShortcodeSuggestions(value: string, cursor: number) {
    const query = findEmojiQuery(value, cursor);
    if (!query) {
      closeEmojiShortcodeSuggestions();
      return;
    }

    const searchVersion = emojiSearchVersionRef.current + 1;
    emojiSearchVersionRef.current = searchVersion;
    setEmojiQuery(query);
    setEmojiPickerOpen(false);

    try {
      const records = emojiRecordsRef.current || await loadEmojiRecords();
      if (emojiSearchVersionRef.current !== searchVersion) return;
      emojiRecordsRef.current = records;
      setEmojiSuggestions(searchEmojiSuggestions(query.query, records));
      setSelectedEmojiSuggestion(0);
    } catch {
      if (emojiSearchVersionRef.current === searchVersion) closeEmojiShortcodeSuggestions();
    }
  }

  function chooseEmojiSuggestion(index: number) {
    const suggestion = emojiSuggestions[index];
    if (!suggestion || !emojiQuery) return;
    const replacement = replaceEmojiQuery(draft, emojiQuery, suggestion.unicode);
    const nextDraft = limitCharacters(replacement.value, CHAT_INPUT_MAX_LENGTH);
    setDraft(nextDraft);
    closeEmojiShortcodeSuggestions();
    window.requestAnimationFrame(() => {
      inputRef.current?.focus({ preventScroll: true });
      const cursor = Math.min(replacement.cursor, nextDraft.length);
      inputRef.current?.setSelectionRange(cursor, cursor);
    });
  }

  function handleComposerKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (emojiSuggestions.length) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const direction = event.key === "ArrowDown" ? 1 : -1;
        setSelectedEmojiSuggestion((current) => (current + direction + emojiSuggestions.length) % emojiSuggestions.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        chooseEmojiSuggestion(selectedEmojiSuggestion);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeEmojiShortcodeSuggestions();
        return;
      }
    }

    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!composerBlocked) event.currentTarget.form?.requestSubmit();
    }
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || !conversation || sending || composerLimit) return;
    closeEmojiShortcodeSuggestions();
    setDraft("");
    await sendText(message);
  }

  async function sendText(message: string, target: Conversation | null = conversation) {
    if (!target) return;
    shouldStickToBottomRef.current = true;
    setSendingFor(target.id, true);
    setError("");
    setComposerLimit(null);
    // A new message also answers for an earlier failed one; the server clears it the same way.
    const earlier = target.messages.map((item) => (isFailedMessage(item) ? { ...item, delivery_status: "read" } : item));
    const quote = target.id === conversation?.id ? replyTo : null;
    setReplyTo(null);
    updateIfOpen(target.id, () => ({ ...target, messages: [...earlier, { role: "user", content: message, created_at: new Date().toISOString(), delivery_status: "sending", ...(quote ? { reply_to: quote } : {}) }] }));
    await postReply(`/api/agent/conversations/${target.id}/messages`, { message, ...(quote ? { reply_to_index: quote.index } : {}) }, target, message);
  }

  function setSendingFor(id: string, value: boolean) {
    setSendingIds((current) => {
      if (current.has(id) === value) return current;
      const next = new Set(current);
      if (value) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  // Applies a change only while that chat is still on screen; a reply never pulls the user back.
  function updateIfOpen(id: string, change: (current: Conversation) => Conversation) {
    setConversation((current) => (current && current.id === id ? change(current) : current));
  }

  async function retryMessage(index: number) {
    if (!conversation || sending) return;
    const target = conversation;
    const text = target.messages[index]?.content || "";
    shouldStickToBottomRef.current = true;
    setSendingFor(target.id, true);
    setError("");
    updateIfOpen(target.id, (current) => ({ ...current, messages: current.messages.map((item, position) => (position === index ? { ...item, delivery_status: "sending" } : item)) }));
    const outcome = await postReply(`/api/agent/conversations/${target.id}/messages/${index}/retry`, null, target, text);
    if (outcome === "not_retryable") {
      // The server never saved it (the connection dropped first): send it as a new message.
      const withoutFailed = { ...target, messages: target.messages.filter((_, position) => position !== index) };
      updateIfOpen(target.id, () => withoutFailed);
      await sendText(text, withoutFailed);
    }
  }

  // Sends the request and settles the pending bubble: replied, failed (with Retry), or rolled back.
  async function postReply(path: string, body: unknown, previousConversation: Conversation, text: string): Promise<"ok" | "failed" | "not_retryable"> {
    const id = previousConversation.id;
    const stillOpen = () => openConversationIdRef.current === id;
    try {
      const response = await apiFetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body === null ? undefined : JSON.stringify(body)
      });
      if (!response.ok) {
        const detail = await apiErrorDetail(response, "Omiryn could not reply.");
        if (response.status === 429) {
          updateIfOpen(id, () => previousConversation);
          if (stillOpen()) setDraft((currentDraft) => (currentDraft.trim() ? currentDraft : text));
          const friendly = friendlyQuotaMessage(detail.message);
          const retryAfterSeconds = retryAfterFromResponse(response);
          const pausedAt = Date.now();
          setPauseNow(pausedAt);
          if (detail.message.toLowerCase().includes("short time")) {
            setComposerLimit({ until: pausedAt + (retryAfterSeconds || 60) * 1000, message: friendly, kind: "burst" });
          } else {
            setComposerLimit({ until: retryAfterSeconds ? pausedAt + retryAfterSeconds * 1000 : undefined, message: friendly, kind: "monthly" });
          }
          return "failed";
        }
        if (response.status === 409 && body === null) return "not_retryable";
        if (detail.code === "reply_failed" || response.status >= 500) {
          markLastUserMessageFailed(id);
          return "failed";
        }
        // Rejected before it was saved (for example a finished conversation): nothing to retry.
        updateIfOpen(id, () => previousConversation);
        if (stillOpen()) {
          setDraft((currentDraft) => (currentDraft.trim() ? currentDraft : text));
          setError(detail.message);
        }
        return "failed";
      }
      const nextConversation = (await response.json()) as Conversation;
      // Shown only if the user is still in that chat; otherwise it waits there, marked unread.
      updateIfOpen(id, () => nextConversation);
      // Drop the typing row in the same render the reply lands, not after the history refresh.
      setSendingFor(id, false);
      await fetchSummaries();
      if (stillOpen()) void loadConversationUsage(id);
      return "ok";
    } catch {
      // No answer at all (offline, server down): keep the bubble with a Retry.
      markLastUserMessageFailed(id);
      return "failed";
    } finally {
      setSendingFor(id, false);
    }
  }

  function markLastUserMessageFailed(id: string) {
    setConversation((current) => {
      if (!current || current.id !== id) return current;
      const index = current.messages.map((item) => item.role).lastIndexOf("user");
      return { ...current, messages: current.messages.map((item, position) => (position === index ? { ...item, delivery_status: "failed" } : item)) };
    });
  }

  async function updateModel(model: string) {
    await updateSettings({ agent_model: model });
  }

  async function updateSettings(settings: Record<string, string>) {
    if (!conversation) return;
    const response = await apiFetch(`/api/agent/conversations/${conversation.id}/settings`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings)
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
    setDeleteImpact(null);
    if (!pendingDelete) return;
    let cancelled = false;
    apiFetch(`/api/agent/conversations/${pendingDelete.id}/deletion-impact`)
      .then((response) => (response.ok ? response.json() : null))
      .then((impact: DeletionImpact | null) => { if (!cancelled) setDeleteImpact(impact); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [pendingDelete?.id]);

  useEffect(() => {
    if (!pendingDelete) return;
    cancelDeleteRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !deleting) setPendingDelete(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [pendingDelete, deleting]);

  // Archiving keeps the chat (and keeps it open if it is on screen); it just moves under Archived.
  async function setArchived(id: string, archived: boolean) {
    const response = await apiFetch(`/api/agent/conversations/${id}/archive`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archived })
    });
    if (!response.ok) {
      setError(await apiErrorMessage(response, archived ? "Could not archive this chat." : "Could not unarchive this chat."));
      return;
    }
    const { archived_at: archivedAt } = (await response.json()) as { archived_at: string | null };
    setSummaries((rows) => rows.map((row) => (row.id === id ? { ...row, archived_at: archivedAt } : row)));
  }

  function stopSelecting() {
    setSelecting(false);
    setSelected([]);
    setConfirmingMessages(false);
    setMessageImpact(null);
    setClearEverything(false);
    setClearWord("");
  }

  // Unticking the last message ends select mode, like in WhatsApp.
  function toggleMessage(index: number) {
    const next = toggleSelected(selected, index);
    if (next.length) setSelected(next);
    else stopSelecting();
  }

  function startSelecting(index: number) {
    setSelecting(true);
    setSelected([index]);
  }

  // The menu opens upward when there is no room for it below the message.
  function openMenu(index: number, anchor: Element) {
    const bottom = logRef.current?.getBoundingClientRect().bottom ?? window.innerHeight;
    setMenuUp(bottom - anchor.getBoundingClientRect().bottom < MESSAGE_MENU_HEIGHT);
    setMenuFor(index);
  }

  // Phones: hold a message to open its menu.
  function holdForMenu(index: number, row: Element) {
    cancelHold();
    longPressRef.current = window.setTimeout(() => {
      longPressRef.current = null;
      openMenu(index, row.querySelector(".message") ?? row);
    }, 500);
  }

  function replyToMessage(index: number) {
    const message = conversation?.messages[index];
    if (!message) return;
    setReplyTo(replyQuoteFor(message, index));
    setMenuFor(null);
    inputRef.current?.focus();
  }

  function copyMessage(index: number) {
    const text = String(conversation?.messages[index]?.content || "").replace(/<next_message>/g, "\n");
    void navigator.clipboard?.writeText(text).catch(() => undefined);
    setMenuFor(null);
  }

  function deleteOneMessage(index: number) {
    setMenuFor(null);
    setSelected([index]);
    void reviewMessageDeletion([index]);
  }

  function jumpToMessage(index: number) {
    const target = document.getElementById(`message-${index}`);
    if (!target) return;
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.classList.add("evidence-highlight");
    window.setTimeout(() => target.classList.remove("evidence-highlight"), 1600);
  }

  function cancelHold() {
    if (longPressRef.current !== null) {
      window.clearTimeout(longPressRef.current);
      longPressRef.current = null;
    }
  }

  async function clearAllOfOmi() {
    setDeletingMessages(true);
    try {
      const response = await apiFetch("/api/me/omi/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: clearWord }),
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Couldn't clear Omi's chats and memories."));
      // Every chat and memory is gone; start fresh.
      window.location.reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Couldn't clear Omi's chats and memories.");
      setDeletingMessages(false);
    }
  }

  async function reviewMessageDeletion(indexes: number[] = selected) {
    if (!conversation || !indexes.length) return;
    setConfirmingMessages(true);
    setMessageImpact(null);
    const response = await apiFetch(`/api/agent/conversations/${conversation.id}/messages/deletion-impact`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_indexes: indexes }),
    }).catch(() => null);
    if (response?.ok) setMessageImpact(await response.json() as MessageDeletionImpact);
  }

  async function deleteSelectedMessages() {
    if (!conversation || !selected.length) return;
    const target = conversation.id;
    setDeletingMessages(true);
    try {
      const response = await apiFetch(`/api/agent/conversations/${target}/messages/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_indexes: selected }),
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Couldn't delete those messages."));
      const indexes = selected;
      updateIfOpen(target, (current) => ({ ...current, messages: markDeleted(current.messages, indexes) }));
      stopSelecting();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Couldn't delete those messages.");
      setConfirmingMessages(false);
    } finally {
      setDeletingMessages(false);
    }
  }

  async function deleteConversation(id: string) {
    setDeleting(true);
    const response = await apiFetch(`/api/agent/conversations/${id}`, { method: "DELETE" });
    if (!response.ok) {
      setError(await apiErrorMessage(response, "Could not delete this conversation."));
      setDeleting(false);
      return;
    }
    conversationCacheRef.current.delete(id);
    const rows = await fetchSummaries();
    if (conversation?.id === id) {
      const nextConversation = rows[0];
      if (nextConversation) {
        await openConversation(nextConversation.id);
      } else {
        window.localStorage.removeItem("omiryn.activeConversationId");
        window.history.replaceState({}, "", "/");
        setSelectedId(null);
        setConversation(null);
        setContextSources([]);
        setUsage(null);
        setUsageError("");
        await createConversation();
      }
    }
    setPendingDelete(null);
    setDeleting(false);
  }

  const agentName = conversation?.agent_name || "Omiryn";
  const usageSummary = usage?.summary || {};
  const usageEvents = usage?.events || [];
  const averageUsage = averageChatUsage(usageEvents, usageSummary);
  const usageCost = usageSummary.estimated_cost_usd ? ` · $${usageSummary.estimated_cost_usd.toFixed(6)}` : "";
  const usageInrCost = usageSummary.estimated_cost_inr ? ` / Rs ${usageSummary.estimated_cost_inr.toFixed(4)}` : "";
  const pauseRemainingSeconds = composerLimit?.until ? Math.max(0, Math.ceil((composerLimit.until - pauseNow) / 1000)) : 0;
  const composerBlocked = Boolean(composerLimit && (!composerLimit.until || pauseRemainingSeconds > 0));

  useEffect(() => {
    if (!conversation || composerBlocked) return;
    const focusComposerOnType = (event: KeyboardEvent) => {
      // A plain, unmodified printable character typed anywhere on the page
      // should land in the composer instead of doing nothing.
      if (event.key.length !== 1 || event.metaKey || event.ctrlKey || event.altKey) return;
      const active = document.activeElement;
      const alreadyTyping = active instanceof HTMLElement
        && (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.tagName === "SELECT" || active.isContentEditable);
      if (alreadyTyping) return;
      inputRef.current?.focus({ preventScroll: true });
    };
    window.addEventListener("keydown", focusComposerOnType);
    return () => window.removeEventListener("keydown", focusComposerOnType);
  }, [conversation, composerBlocked]);

  // Typing in the composer re-renders this page on every key; the message list and History only
  // rebuild when what they show changes, so long chats stay smooth to type in.
  const historyRows = useMemo(() => {
    const renderRow = (item: ConversationSummary) => (
      <div className={`history-item ${item.id === openId ? "active" : ""} ${isUnread(item, seen, openId) ? "is-unread" : ""} ${rowMenuId === item.id ? "menu-open" : ""} ${item.archived_at ? "is-archived" : ""}`} role="button" tabIndex={0} key={item.id} onClick={() => void openConversation(item.id)} onKeyDown={(event) => event.key === "Enter" && void openConversation(item.id)}>
        <div className="history-item-copy"><div className="history-item-line"><strong>{item.agent_name || "Omiryn"}</strong><small>{historyTimeLabel(item.updated_at)}</small></div><div className="history-item-line">{sendingIds.has(item.id) || typingConversationId === item.id ? <span className="history-typing" aria-label="Omi is typing"><span className="typing-dots"><span /><span /><span /></span>typing</span> : <span>{item.message_count || 0} messages</span>}{isUnread(item, seen, openId) ? <span className="history-new-pill">New</span> : null}</div></div>
        <div className="history-row-menu" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
          <button className="history-menu-button" type="button" aria-haspopup="menu" aria-expanded={rowMenuId === item.id} aria-label={`More options for ${item.agent_name || "Omiryn"}`} onClick={() => setRowMenuId(rowMenuId === item.id ? null : item.id)}><MoreHorizontal aria-hidden="true" /></button>
          {rowMenuId === item.id ? (
            <div className="history-menu" role="menu">
              <button type="button" role="menuitem" onClick={() => { setRowMenuId(null); void setArchived(item.id, !item.archived_at); }}>{item.archived_at ? <ArchiveRestore aria-hidden="true" /> : <Archive aria-hidden="true" />}{item.archived_at ? "Unarchive" : "Archive"}</button>
              <button type="button" role="menuitem" className="is-danger" onClick={() => { setRowMenuId(null); setPendingDelete(item); }}><Trash2 aria-hidden="true" />Delete</button>
            </div>
          ) : null}
        </div>
      </div>
    );
    const earlier = summaries.filter((item) => item.id !== omiId);
    const archived = earlier.filter((item) => item.archived_at);
    if (!earlier.length) return <p className="omi-drawer-empty">No earlier chats. Everything with Omi stays in one chat.</p>;
    return (
      <>
        {earlier.filter((item) => !item.archived_at).map(renderRow)}
        {archived.length ? (
          <>
            <button type="button" className="history-archived-toggle" aria-expanded={archivedOpen} onClick={() => setArchivedOpen(!archivedOpen)}>
              <ChevronRight aria-hidden="true" />Archived ({archived.length})
            </button>
            {archivedOpen ? archived.map(renderRow) : null}
          </>
        ) : null}
      </>
    );
  }, [summaries, seen, openId, sendingIds, typingConversationId, rowMenuId, archivedOpen, omiId]);
  const noted = useMemo(
    () => (conversation ? notedLinesByMessage(vibeAreas, conversation.id, visibleMessages) : new Map<number, NotedLine[]>()),
    [vibeAreas, conversation, shownCount],
  );
  const selectableIndexes = useMemo(
    () => (conversation ? conversation.messages.flatMap((message, index) => (isDeletedMessage(message) ? [] : [index])) : []),
    [conversation],
  );
  const allSelected = selectableIndexes.length > 0 && selected.length === selectableIndexes.length;
  const messageRows = useMemo(() => (loading ? null : visibleMessages.map((message, index) => {
              if (isDeletedMessage(message)) return null;
              const agent = message.role === "assistant";
              const isSelected = selected.includes(index);
              const currentDate = messageDateKey(message, index);
              const previous = index > 0 ? visibleMessages[index - 1] : null;
              const next = index < visibleMessages.length - 1 ? visibleMessages[index + 1] : null;
              const previousDate = previous ? messageDateKey(previous, index - 1) : "";
              const nextDate = next ? messageDateKey(next, index + 1) : "";
              const sameAsPrevious = Boolean(previous && previous.role === message.role && currentDate === previousDate && minutesBetweenMessages(previous, index - 1, message, index) < 20);
              // The typing row continues Omiryn's last bubble, so that bubble gives up its avatar.
              const typingContinues = typingVisible && agent && !next;
              const sameAsNext = typingContinues || Boolean(next && next.role === message.role && currentDate === nextDate && minutesBetweenMessages(message, index, next, index + 1) < 20);
              const clusterClass = !sameAsPrevious && !sameAsNext ? "cluster-single" : !sameAsPrevious ? "cluster-start" : !sameAsNext ? "cluster-end" : "cluster-middle";
              const showTimeSeparator = !previous || currentDate !== previousDate || minutesBetweenMessages(previous, index - 1, message, index) >= 20;
              const showAvatar = !sameAsNext;
              return (
                <Fragment key={index}>
                  {showTimeSeparator ? <div className="chat-day-separator chat-time-separator" role="separator" aria-label={messageSessionLabel(message, index)} data-day-separator={currentDate}><span>{messageSessionLabel(message, index)}</span></div> : null}
                  <div
                    className={`message-row ${agent ? "agent" : "user"} ${clusterClass} ${sameAsPrevious ? "same-cluster" : ""} ${index >= newFromIndexRef.current ? "is-new" : ""} ${selecting ? "is-selectable" : ""} ${isSelected ? "is-selected" : ""}`}
                    id={`message-${index}`}
                    data-message-index={index}
                    {...(selecting
                      ? { role: "checkbox", "aria-checked": isSelected, tabIndex: 0, onClick: () => toggleMessage(index), onKeyDown: (event: ReactKeyboardEvent) => { if (event.key === " " || event.key === "Enter") { event.preventDefault(); toggleMessage(index); } } }
                      : { onTouchStart: (event: ReactTouchEvent) => holdForMenu(index, event.currentTarget), onTouchEnd: cancelHold, onTouchMove: cancelHold })}
                  >
                    {selecting ? <span className="message-select-mark" aria-hidden="true">{isSelected ? <Check /> : null}</span> : null}
                    {agent ? showAvatar ? <span className="chat-avatar agent"><AgentOrb /></span> : <span className="chat-avatar-spacer" aria-hidden="true" /> : null}
                    <div className={`message ${agent ? "agent" : "user"}`}>
                      {message.reply_to ? (
                        <button type="button" className="message-quote" onClick={(event) => { event.stopPropagation(); if (!message.reply_to?.deleted) jumpToMessage(message.reply_to!.index); }} disabled={selecting || message.reply_to.deleted}>
                          <strong>{replyQuoteLabel(message.reply_to)}</strong>
                          {message.reply_to.text ? <span>{message.reply_to.text}</span> : null}
                        </button>
                      ) : null}
                      <div className={`message-content ${agent ? "agent" : "user"}`}>{message.content}</div>
                    </div>
                    {!selecting && !isFailedMessage(message) && message.delivery_status !== "sending" ? (
                      <div className="message-menu">
                        <button type="button" className={`message-menu-trigger ${menuFor === index ? "is-open" : ""}`} aria-label="Message options" aria-haspopup="menu" aria-expanded={menuFor === index} onClick={(event) => { if (menuFor === index) setMenuFor(null); else openMenu(index, event.currentTarget); }}><MoreHorizontal aria-hidden="true" /></button>
                        {menuFor === index ? (
                          <div className={`message-menu-list ${menuUp ? "opens-up" : ""}`} role="menu">
                            <button type="button" role="menuitem" onClick={() => replyToMessage(index)}><Reply aria-hidden="true" />Reply</button>
                            <button type="button" role="menuitem" onClick={() => copyMessage(index)}><Copy aria-hidden="true" />Copy</button>
                            <button type="button" role="menuitem" onClick={() => { setMenuFor(null); startSelecting(index); }}><ListChecks aria-hidden="true" />Select</button>
                            <button type="button" role="menuitem" className="is-danger" onClick={() => deleteOneMessage(index)}><Trash2 aria-hidden="true" />Delete</button>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    {!agent ? showAvatar ? <span className="chat-avatar user"><AvatarImage src={userAvatar} fallback="You" /></span> : <span className="chat-avatar-spacer" aria-hidden="true" /> : null}
                  </div>
                  {noted.get(index)?.map((line) => (
                    <p className={`noted-line ${agent ? "is-agent" : "is-user"}`} key={line.areaId}>
                      <Check aria-hidden="true" />
                      <span>Noted: {lowerFirst(line.text)}{line.private ? <Lock aria-label="Private" /> : null}</span>
                      <button type="button" onClick={() => void rejectNoted(line.areaId)} disabled={rejectingArea === line.areaId}>{rejectingArea === line.areaId ? "Removing…" : "Not right?"}</button>
                    </p>
                  ))}
                  {!agent && isFailedMessage(message) && !sending ? <div className="message-status-row" role="status"><span className="message-status-text">Not sent</span><button type="button" className="message-retry-button" onClick={() => void retryMessage(index)} aria-label="Retry" title="Retry"><RotateCw aria-hidden="true" /></button></div> : null}
                </Fragment>
              );
            })), [loading, conversation, shownCount, typingVisible, sending, userAvatar, noted, rejectingArea, selecting, selected, menuFor, menuUp]);

  return (
    <section className="screen interview-screen legacy-chat-screen">
      <div className="chat-workspace">
        <section className={`chat-card agentic-chat ${loading || !conversation ? "conversation-empty" : ""}`}>
          {selecting ? (
            <div className="card-heading message-select-toolbar" role="toolbar" aria-label="Selected messages">
              <button type="button" className="select-toolbar-icon" onClick={stopSelecting} aria-label="Stop selecting"><X aria-hidden="true" /></button>
              <span className="select-toolbar-count">{selected.length ? `${selected.length} selected` : "Tap messages"}</span>
              <button type="button" className="select-toolbar-text" onClick={() => setSelected(allSelected ? [] : selectableIndexes)}>{allSelected ? "Clear" : "Select all"}</button>
              <button type="button" className="select-toolbar-icon is-danger" disabled={!selected.length} onClick={() => void reviewMessageDeletion()} aria-label="Delete selected"><Trash2 aria-hidden="true" /></button>
            </div>
          ) : (
          <div className="card-heading">
            {onOpenNavigation ? <button type="button" className="omi-back" onClick={onOpenNavigation} aria-label="Open navigation"><Menu aria-hidden="true" /></button> : null}
            <div className="chat-title-lockup"><span className="terminal-mark"><AgentOrb state={typingVisible ? "thinking" : draft.trim() ? "listening" : "idle"} /></span><div><h2>{agentName}</h2></div>{temporary ? <span className="temporary-pill"><MessageCircleDashed aria-hidden="true" />Temporary</span> : null}</div>
            <div className="chat-controls omi-chat-menu" ref={chatMenuRef}>
              <button type="button" className="omi-menu-button" aria-label="Chat options" aria-haspopup="menu" aria-expanded={chatMenuOpen} onClick={() => setChatMenuOpen((value) => !value)}>
                <MoreHorizontal aria-hidden="true" />{earlierUnread ? <span className="history-unread-dot" role="img" aria-label="New messages in an earlier chat" /> : null}
              </button>
              {chatMenuOpen ? (
                <div className="history-menu omi-chat-menu-list" role="menu">
                  <button type="button" role="menuitem" onClick={() => { setChatMenuOpen(false); setDrawer("earlier"); }}><History aria-hidden="true" />Earlier chats{earlierUnread ? <span className="history-new-pill">New</span> : null}</button>
                  {conversation && !viewingEarlier ? <button type="button" role="menuitem" onClick={() => { setChatMenuOpen(false); setSelecting(true); setSelected([]); }}><ListChecks aria-hidden="true" />Select messages</button> : null}
                  {temporary ? null : <button type="button" role="menuitem" onClick={() => { setChatMenuOpen(false); void startTemporaryChat(); }}><MessageCircleDashed aria-hidden="true" />Temporary chat</button>}
                  {canShowUsage ? <button type="button" role="menuitem" onClick={() => { setChatMenuOpen(false); setDrawer("usage"); if (conversation) void loadConversationUsage(conversation.id); }}><BarChart3 aria-hidden="true" />Usage (dev)</button> : null}
                </div>
              ) : null}
            </div>
          </div>
          )}
          <div className="chat-log" ref={logRef} onScroll={handleChatScroll} aria-live="polite">
            {loading ? <StateView kind="loading" title="Opening your chat…" /> : null}
            {!loading && !conversation ? <StateView kind="empty" title="Say hi to Omi" detail="Your chat with Omi will appear here."><button type="button" onClick={() => void createConversation()}>Start chatting</button></StateView> : null}
            {!loading && conversation ? <p className="omi-chat-notice"><Lock aria-hidden="true" />Omi learns from your chats to find you friends. Don't share passwords or IDs.</p> : null}
            {messageRows}
            {typingVisible ? <div className={`message-row agent is-new ${lastVisibleIsAgent ? "cluster-end same-cluster" : "cluster-single"}`}><span className="chat-avatar agent"><AgentOrb active /></span><div className="message agent typing-message"><div className="message-content typing-content"><span className="typing-dots"><span /><span /><span /></span></div></div></div> : null}
            {sending && slowReply ? <p className="typing-slow-note" role="status">Taking longer than usual…</p> : null}
          </div>
          {error ? <div className="chat-error-notice"><Notice tone="error">{error}</Notice></div> : null}
          {composerBlocked ? <p className={`composer-pause-note ${composerLimit?.kind === "monthly" ? "is-monthly" : ""}`} id="composer-pause-note" role="status">{composerLimit?.message}<span>{composerLimit?.kind === "monthly" ? `Resets in ${formatLimitCountdown(pauseRemainingSeconds)}` : `Try again in ${formatLimitCountdown(pauseRemainingSeconds)}`}</span></p> : null}
          {vibeNote && vibeNote.conversationId === conversation?.id && vibeStepNote(vibeNote.milestone) ? (
            <div className="vibe-milestone-note" role="status">
              <Sparkles className="vibe-milestone-icon" aria-hidden="true" />
              <span><strong>Your vibe is taking shape</strong>{vibeStepNote(vibeNote.milestone)}</span>
              <a href={pathForPage.vibe} onClick={(event) => { event.preventDefault(); setVibeNote(null); window.history.pushState({}, "", pathForPage.vibe); window.dispatchEvent(new PopStateEvent("popstate")); }}>View vibe</a>
              <button type="button" onClick={() => setVibeNote(null)} aria-label="Dismiss vibe update"><X aria-hidden="true" /></button>
            </div>
          ) : null}
          {viewingEarlier ? (
            <div className="omi-readonly-bar" role="status">
              <span>This is an earlier chat. New messages go to Omi's main chat.</span>
              <button type="button" onClick={() => omiId && void openConversation(omiId)}>Back to Omi</button>
            </div>
          ) : (
            <>
            {temporary ? (
              <div className="omi-readonly-bar temporary-bar" role="status">
                <span>Omi won't remember this chat.</span>
                <button type="button" onClick={endTemporaryChat}>End chat</button>
              </div>
            ) : null}
            {replyTo ? (
              <div className="reply-preview" role="status">
                <Reply aria-hidden="true" />
                <div><strong>Replying to {replyQuoteLabel(replyTo) === "Omi" ? "Omi" : "yourself"}</strong><span>{replyTo.text}</span></div>
                <button type="button" onClick={() => setReplyTo(null)} aria-label="Cancel reply"><X aria-hidden="true" /></button>
              </div>
            ) : null}
            <form className={`composer ${composerBlocked ? "is-paused" : ""} ${characterCount(draft) >= 80 ? "is-near-limit" : ""}`} onSubmit={sendMessage}>
              {limitNoticeVersion ? <div className="chat-limit-notice" role="status">Your message is too long</div> : null}
              {emojiSuggestions.length ? (
                <div className="emoji-shortcode-menu" id="emoji-shortcode-menu" role="listbox" aria-label="Emoji suggestions">
                  {emojiSuggestions.map((suggestion, index) => (
                    <button
                      className="emoji-shortcode-option"
                      id={`emoji-shortcode-option-${index}`}
                      type="button"
                      role="option"
                      aria-selected={index === selectedEmojiSuggestion}
                      key={`${suggestion.unicode}-${suggestion.shortcode}`}
                      onPointerDown={(event) => event.preventDefault()}
                      onClick={() => chooseEmojiSuggestion(index)}
                    >
                      <span className="emoji-shortcode-glyph" aria-hidden="true">{suggestion.unicode}</span>
                      <span className="emoji-shortcode-copy"><strong>:{suggestion.shortcode}</strong><small>{suggestion.label}</small></span>
                    </button>
                  ))}
                </div>
              ) : null}
              <div className="emoji-picker-anchor" ref={emojiPickerRef}>
                <button className="emoji-trigger-button" type="button" disabled={!conversation || composerBlocked} aria-label="Add emoji" aria-expanded={emojiPickerOpen} onClick={() => { closeEmojiShortcodeSuggestions(); setEmojiPickerOpen((value) => !value); }}><Smile className="emoji-trigger-icon" aria-hidden="true" /></button>
                {emojiPickerOpen ? (
                  <div className="emoji-picker-popover">
                    <Suspense fallback={<div className="emoji-picker-loading">Loading emoji...</div>}>
                      <EmojiPicker
                        height={360}
                        emojiStyle={"native" as EmojiStyle}
                        lazyLoadEmojis
                        previewConfig={{ showPreview: false }}
                        searchPlaceHolder="Search emoji"
                        skinTonesDisabled
                        theme={"light" as Theme}
                        width="100%"
                        onEmojiClick={insertEmoji}
                      />
                    </Suspense>
                  </div>
                ) : null}
              </div>
              <textarea ref={inputRef} value={draft} onChange={(event) => updateDraft(event.target.value, event.target.selectionStart)} onSelect={(event) => void refreshEmojiShortcodeSuggestions(draft, event.currentTarget.selectionStart)} onKeyDown={handleComposerKeyDown} onBlur={closeEmojiShortcodeSuggestions} placeholder={composerBlocked ? "Hold that thought..." : "Say what matters..."} rows={1} disabled={!conversation} role="combobox" aria-autocomplete="list" aria-expanded={Boolean(emojiSuggestions.length)} aria-controls={emojiSuggestions.length ? "emoji-shortcode-menu" : undefined} aria-activedescendant={emojiSuggestions.length ? `emoji-shortcode-option-${selectedEmojiSuggestion}` : undefined} aria-describedby={composerBlocked ? "composer-pause-note" : characterCount(draft) >= 80 ? "chat-character-count" : undefined} />
              {characterCount(draft) >= 80 ? <span className="chat-character-count" id="chat-character-count" aria-live="polite">{characterCount(draft)}/{CHAT_INPUT_MAX_LENGTH}</span> : null}
              <button type="submit" disabled={!draft.trim() || sending || composerBlocked} aria-label="Send message" onPointerDown={(event) => { if (!event.currentTarget.disabled) event.preventDefault(); }}><svg className="send-message-icon" viewBox="0 0 24 24"><path d="M4 20 21 12 4 4l3.3 7.2L15 12l-7.7.8L4 20Z" /></svg></button>
            </form>
            </>
          )}
        </section>
        {drawer ? (
          <>
            <button className="omi-drawer-backdrop" type="button" onClick={() => setDrawer(null)} aria-label="Close panel" />
            <aside className="omi-drawer" aria-label={drawer === "earlier" ? "Earlier chats" : "Usage"}>
              <div className="omi-drawer-head">
                <strong>{drawer === "earlier" ? "Earlier chats" : "Usage"}</strong>
                <button type="button" className="omi-drawer-close" onClick={() => setDrawer(null)} aria-label="Close"><X aria-hidden="true" /></button>
              </div>
              {drawer === "earlier" ? (
                <>
                  <p className="omi-drawer-note">Read-only. Everything new happens in Omi's main chat.</p>
                  <div className="history-list">{historyRows}</div>
                </>
              ) : (
                <div className="omi-drawer-usage">
                  {(/(localhost|127.0.0.1)/i).test(window.origin) && <label className="model-picker"><span>Model</span><select value={conversation?.agent_model || runtime.model || ""} onChange={(event) => void updateModel(event.target.value)}>{(runtime.available_models || [runtime.model]).filter(Boolean).map((model) => <option value={model} key={model}>{model}</option>)}</select></label>}
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
                  const resultLabel = cognitionResultLabel(event);
                  return <div className={`sidebar-usage-item ${event.success ? "ok" : "failed"}`} key={`${event.created_at || "event"}-${index}`}><div><strong>#{usageEvents.length - index} {usageRequestKindLabel(event.request_kind)}</strong><span>{createdAt} · {event.model || event.provider || "-"}</span>{resultLabel ? <span>{resultLabel}</span> : null}</div><div className="sidebar-usage-tokens"><strong>{totalText}</strong><span>{tokenText}</span></div></div>;
                })}
              </div>
                </div>
              )}
            </aside>
          </>
        ) : null}
      </div>
      {confirmingMessages ? (
        <div className="confirm-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !deletingMessages) setConfirmingMessages(false); }}>
          <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-messages-title">
            <div className="confirm-icon" aria-hidden="true"><Trash2 /></div>
            <div className="confirm-copy">
              <p className="eyebrow">{clearEverything ? "Clear Omi" : "Delete messages"}</p>
              <h2 id="delete-messages-title">{clearEverything ? "Clear everything Omi knows about you?" : `Delete ${selected.length} ${selected.length === 1 ? "message" : "messages"}?`}</h2>
              <p>{clearEverything ? "Every chat with Omi and everything it learned will be deleted. Omi starts fresh with you." : "They're gone for good, for you and for Omi."}</p>
              {messageImpact && !clearEverything ? <ul className="delete-impact">{messageDeletionImpactLines(messageImpact).map((line) => <li key={line}>{line}</li>)}</ul> : null}
              {!messageImpact && !clearEverything ? <p className="confirm-session">Checking what goes with them…</p> : null}
              {allSelected ? (
                <label className="clear-everything-option">
                  <input type="checkbox" checked={clearEverything} onChange={(event) => { setClearEverything(event.target.checked); setClearWord(""); }} />
                  <span>Also clear everything Omi knows about me: all memories, your vibe, earlier chats and uploads. Your account and profile stay.</span>
                </label>
              ) : null}
              {clearEverything ? (
                <label className="clear-everything-confirm">
                  This can't be undone. Type <strong>clear</strong> to confirm.
                  <input type="text" value={clearWord} onChange={(event) => setClearWord(event.target.value)} autoComplete="off" autoFocus aria-label='Type "clear" to confirm' />
                </label>
              ) : null}
            </div>
            <div className="confirm-actions">
              <button className="secondary-button" type="button" onClick={() => setConfirmingMessages(false)} disabled={deletingMessages}>Cancel</button>
              {clearEverything ? (
                <button className="danger-button" type="button" onClick={() => void clearAllOfOmi()} disabled={deletingMessages || clearWord.trim().toLowerCase() !== "clear"}>{deletingMessages ? "Clearing…" : "Clear everything"}</button>
              ) : (
                <button className="danger-button" type="button" onClick={() => void deleteSelectedMessages()} disabled={deletingMessages || !messageImpact}>{deletingMessages ? "Deleting…" : "Delete"}</button>
              )}
            </div>
          </section>
        </div>
      ) : null}
      {pendingDelete ? <div className="confirm-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !deleting) setPendingDelete(null); }}><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-conversation-title" aria-describedby="delete-conversation-copy"><div className="confirm-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M9 3h6l1 2h4v2H4V5h4l1-2Z" /><path d="M6 9h12l-.8 11H6.8L6 9Zm4 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z" /></svg></div><div className="confirm-copy"><p className="eyebrow">Delete Conversation</p><h2 id="delete-conversation-title">Delete this chat?</h2><p id="delete-conversation-copy">It's gone for good, along with what Omi learned only from it.</p>{deleteImpact && deletionImpactLines(deleteImpact).length ? <ul className="delete-impact">{deletionImpactLines(deleteImpact).map((line) => <li key={line}>{line}</li>)}</ul> : null}<p className="confirm-session">{pendingDelete.agent_name || "Omiryn"} · {pendingDelete.message_count || 0} {pendingDelete.message_count === 1 ? "message" : "messages"}</p></div><div className="confirm-actions"><button ref={cancelDeleteRef} className="secondary-button" type="button" onClick={() => setPendingDelete(null)} disabled={deleting}>Cancel</button><button className="danger-button" type="button" onClick={() => void deleteConversation(pendingDelete.id)} disabled={deleting}>{deleting ? "Deleting…" : "Delete chat"}</button></div></section></div> : null}
    </section>
  );
}

function applyRealtimeEvent(
  event: RealtimeEvent,
  setConversation: Dispatch<SetStateAction<Conversation | null>>,
) {
  if (event.type !== "message.created" || event.scope !== "conversation" || !event.scope_id) return;
  const messageIndex = event.sequence;
  const rawMessage = event.payload.message;
  if (typeof messageIndex !== "number" || !Number.isInteger(messageIndex) || messageIndex < 0) return;
  if (!rawMessage || typeof rawMessage !== "object" || Array.isArray(rawMessage)) return;

  const record = rawMessage as Record<string, unknown>;
  const message: Message = {
    role: typeof record.role === "string" ? record.role : undefined,
    content: typeof record.content === "string" ? record.content : undefined,
    created_at: typeof record.created_at === "string" ? record.created_at : undefined,
    delivery_status: typeof record.delivery_status === "string" ? record.delivery_status : undefined,
  };
  if (!message.role || typeof message.content !== "string") return;

  setConversation((current) => {
    if (!current || current.id !== event.scope_id) return current;
    if (messageIndex > current.messages.length) return current;
    const messages = [...current.messages];
    if (messageIndex === messages.length) messages.push(message);
    else messages[messageIndex] = { ...messages[messageIndex], ...message };
    return { ...current, messages };
  });
}

function characterCount(value: string) {
  return Array.from(value).length;
}

function limitCharacters(value: string, maximum: number) {
  return Array.from(value).slice(0, maximum).join("");
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-IN").format(value);
}

function sortConversationSummaries(rows: ConversationSummary[]) {
  return [...rows].sort((left, right) => conversationSortTime(right) - conversationSortTime(left));
}

function conversationSortTime(row: ConversationSummary) {
  const parsed = row.updated_at ? new Date(row.updated_at).getTime() : 0;
  return Number.isFinite(parsed) ? parsed : 0;
}

// Short and neutral; the countdown under it says when sending opens again.
function friendlyQuotaMessage(detail: string) {
  if (detail.toLowerCase().includes("short time")) {
    return "You're quick. Give Omi a moment to catch up.";
  }
  if (detail.toLowerCase().includes("monthly limit")) {
    return "You've used this month's chats. Your draft is saved.";
  }
  return detail;
}

const SLOW_REPLY_MS = 20000;

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

// History row time: "7:30 pm" today, "Yesterday", then "2 Oct" (with the year when it differs).
// "Wants friends who show up." -> "wants friends who show up." (reads as part of "Noted: ...").
function lowerFirst(text: string) {
  return text && /^[A-Z][a-z]/.test(text) ? text[0].toLowerCase() + text.slice(1) : text;
}

// Omi's ongoing chat: the newest chat the user has not archived (older ones are "Earlier chats").
function omiThreadId(rows: ConversationSummary[]): string | null {
  const open = rows.filter((row) => !row.archived_at);
  const newest = [...(open.length ? open : rows)].sort((left, right) => String(right.created_at || right.updated_at || "").localeCompare(String(left.created_at || left.updated_at || "")))[0];
  return newest?.id ?? null;
}

function historyTimeLabel(value?: string | null) {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "New";
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return date.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true }).toLowerCase();
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: date.getFullYear() === today.getFullYear() ? undefined : "numeric" });
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
