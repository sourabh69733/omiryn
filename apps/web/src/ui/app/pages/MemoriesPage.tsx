import { type FormEvent, type MouseEvent, useEffect, useState } from "react";
import { CheckCircle2, MoreHorizontal, Quote, SlidersHorizontal } from "lucide-react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import { Notice, StateView } from "../StateView";
import { trackAppEvent } from "../../../lib/appLogger";
import type { CanonicalMemory, ContextSource, MemoryResponse, ProfileFact, ProfileResponse } from "../types";
import { canonicalMemoryCardTone, canonicalMemoryControls, canonicalMemoryEvidenceHref, canonicalMemoryReviewPayload, canonicalMemoryValueText, groupCanonicalMemories, oldMemoryNote, partitionCanonicalMemories, toggleCanonicalMemoryReviewReason } from "../memoryPresentation";

const memoryReviewReasons = [
  { value: "incorrect", label: "Incorrect" },
  { value: "outdated", label: "Outdated" },
  { value: "missing_context", label: "Missing context" },
  { value: "not_about_me", label: "Not about me" }
];

type OpenQuestion = { id: string; text: string; about_memory_ids?: string[]; created_at?: string };

export function MemoriesPage() {
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [canonicalMemories, setCanonicalMemories] = useState<CanonicalMemory[]>([]);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [showImport, setShowImport] = useState(false);
  const [importMode, setImportMode] = useState<"memory" | "whatsapp">("memory");
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("Imported context");
  const [userSender, setUserSender] = useState("");
  const [saving, setSaving] = useState(false);
  const [savingFactId, setSavingFactId] = useState<string | null>(null);
  const [reviewItem, setReviewItem] = useState<ProfileFact | CanonicalMemory | null>(null);
  const [reviewMode, setReviewMode] = useState<"feedback" | "privacy" | null>(null);
  const [feedbackRating, setFeedbackRating] = useState<"agree" | "disagree">("agree");
  const [feedbackReasons, setFeedbackReasons] = useState<string[]>([]);
  const [reviewReason, setReviewReason] = useState("");
  const [privacyForChat, setPrivacyForChat] = useState(false);
  const [privacyForMatching, setPrivacyForMatching] = useState(false);
  const [visibleSectionCounts, setVisibleSectionCounts] = useState<Record<string, number>>({});
  const [evidenceItem, setEvidenceItem] = useState<ProfileFact | CanonicalMemory | null>(null);
  const [openQuestions, setOpenQuestions] = useState<OpenQuestion[]>([]);
  // Memory row whose "more" menu is open.
  const [rowMenuId, setRowMenuId] = useState<string | null>(null);

  async function load() {
    const [profileResponse, memoryResponse] = await Promise.all([
      apiFetch("/api/me/profile"),
      apiFetch("/api/me/memories")
    ]);
    if (!profileResponse.ok) throw new Error(await apiErrorMessage(profileResponse, "Could not load saved memories."));
    if (!memoryResponse.ok) throw new Error(await apiErrorMessage(memoryResponse, "Could not load your memories."));
    const memoryData = await memoryResponse.json() as MemoryResponse;
    setData(await profileResponse.json());
    setCanonicalMemories(memoryData.memories || []);
    setLoaded(true);
    // Optional: the page works without it.
    apiFetch("/api/me/open-questions")
      .then((response) => (response.ok ? response.json() : { questions: [] }))
      .then((body: { questions?: OpenQuestion[] }) => setOpenQuestions(body.questions || []))
      .catch(() => setOpenQuestions([]));
  }
  async function dismissQuestion(id: string) {
    const response = await apiFetch(`/api/me/open-questions/${id}/dismiss`, { method: "POST" });
    if (response.ok) setOpenQuestions((current) => current.filter((question) => question.id !== id));
  }
  useEffect(() => {
    if (!rowMenuId) return;
    const close = (event: globalThis.MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !(event.target instanceof Element && event.target.closest(".mem-row-menu"))) setRowMenuId(null);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [rowMenuId]);
  function firstLoad() { setLoadError(""); load().catch((caught) => setLoadError(caught.message)); }
  useEffect(firstLoad, []);

  const sources = [...(data?.memory_sources || []), ...(data?.style_sources || [])];
  const canonicalMemoryGroups = partitionCanonicalMemories(canonicalMemories);
  const canonicalSections = groupCanonicalMemories(canonicalMemoryGroups.active);
  const showRejectedCanonical = visibleSectionCounts["rejected-canonical"] !== undefined;
  const showOldCanonical = visibleSectionCounts["old-canonical"] !== undefined;
  const oldIds = new Set(canonicalMemoryGroups.old.map((memory) => memory.id));
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
      trackAppEvent("memory_import_completed", { source_type: importMode === "whatsapp" ? "whatsapp_chat" : "manual_notes" }, { page: "memories" });
      setContent(""); setShowImport(false); await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not save memory."); }
    finally { setSaving(false); }
  }

  async function removeSource(id: string) {
    const response = await apiFetch(`/api/me/context-sources/${id}`, { method: "DELETE" });
    if (response.ok) await load();
  }

  async function patchFact(fact: ProfileFact, payload: Record<string, unknown>, eventName: Parameters<typeof trackAppEvent>[0]) {
    setSavingFactId(fact.id);
    setError("");
    try {
      const response = await apiFetch(`/api/me/profile-facts/${fact.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not update that signal."));
      trackAppEvent(eventName, { fact_category: fact.category || "unknown" }, { page: "memories", target_type: "profile_fact", target_id: fact.id });
      setReviewItem(null);
      setReviewMode(null);
      setFeedbackReasons([]);
      setReviewReason("");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update that signal.");
    } finally {
      setSavingFactId(null);
    }
  }

  function openFeedbackFlow(item: ProfileFact | CanonicalMemory, initialRating?: "agree" | "disagree") {
    setReviewItem(item);
    setReviewMode("feedback");
    const savedRating = item.feedback?.rating;
    setFeedbackRating(initialRating || (savedRating === "disagree" ? "disagree" : "agree"));
    setFeedbackReasons(isCanonicalMemory(item) ? (item.feedback?.reasons || []) : (item.feedback?.reason ? [item.feedback.reason] : []));
    setReviewReason(item.feedback?.comment || "");
    setError("");
  }

  function openPrivacyFlow(item: ProfileFact | CanonicalMemory) {
    setReviewItem(item);
    setReviewMode("privacy");
    setPrivacyForChat(isCanonicalMemory(item) ? (item.allowed_uses || []).includes("reply_context") : Boolean(item.used_for_chat_context));
    setPrivacyForMatching(isCanonicalMemory(item) ? (item.allowed_uses || []).includes("matching") : Boolean(item.used_for_matching));
    setReviewReason("");
    setError("");
  }

  async function saveSignalFeedback(item: ProfileFact | CanonicalMemory, rating: "agree" | "disagree", comment = "", reasons: string[] = []) {
    setSavingFactId(item.id);
    setError("");
    try {
      const canonical = isCanonicalMemory(item);
      const endpoint = canonical
        ? "/api/me/memories/" + item.id + "/review"
        : "/api/me/profile-facts/" + item.id + "/feedback";
      const response = await apiFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(canonical ? canonicalMemoryReviewPayload(rating, reasons, comment) : {
          rating,
          reason: reasons[0] || (rating === "disagree" ? "wrong" : "feels_right"),
          comment: comment.trim() || null
        })
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not save feedback."));
      const factCategory = isCanonicalMemory(item) ? item.kind : item.category || "unknown";
      trackAppEvent("learned_signal_feedback_sent", { fact_category: factCategory, rating }, { page: "memories", target_type: canonical ? "agent_memory" : "profile_fact", target_id: item.id });
      setReviewItem(null);
      setReviewMode(null);
      setFeedbackReasons([]);
      setReviewReason("");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save feedback.");
    } finally {
      setSavingFactId(null);
    }
  }

  async function submitFeedbackFlow(event: FormEvent) {
    event.preventDefault();
    if (!reviewItem) return;
    await saveSignalFeedback(reviewItem, feedbackRating, reviewReason, feedbackReasons);
  }

  async function submitPrivacyFlow(event: FormEvent) {
    event.preventDefault();
    if (!reviewItem) return;
    if (isCanonicalMemory(reviewItem)) {
      setSavingFactId(reviewItem.id);
      setError("");
      try {
        const allowedUses = [
          ...(privacyForChat ? ["reply_context"] : []),
          ...(privacyForMatching ? ["matching"] : [])
        ];
        const response = await apiFetch("/api/me/memories/" + reviewItem.id + "/permissions", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ allowed_uses: allowedUses })
        });
        if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not update memory usage."));
        trackAppEvent("learned_signal_privacy_updated", { fact_category: reviewItem.kind }, { page: "memories", target_type: "agent_memory", target_id: reviewItem.id });
        setReviewItem(null);
        setReviewMode(null);
        await load();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not update memory usage.");
      } finally {
        setSavingFactId(null);
      }
      return;
    }
    await patchFact(
      reviewItem,
      {
        status: "active",
        used_for_chat_context: privacyForChat,
        used_for_matching: privacyForMatching
      },
      "learned_signal_privacy_updated"
    );
  }

  // One memory as a quiet row: what it's about, what Omi remembers, and a menu for the rest.
  function renderCanonicalMemory(memory: CanonicalMemory) {
    const value = canonicalMemoryValueText(memory.value);
    const controls = canonicalMemoryControls(memory.evidence?.length || 0);
    const evidenceControl = controls.find((control) => control.id === "evidence");
    const isOld = oldIds.has(memory.id);
    const active = !isOld && (!memory.status || memory.status === "active");
    const isSaving = savingFactId === memory.id;
    const label = sentenceCase(humanizeLabel(memory.key));
    return (
      <article className={`mem-row ${isOld ? "is-old" : ""} ${rowMenuId === memory.id ? "menu-open" : ""}`} key={memory.id}>
        <div className="mem-row-copy">
          {value ? <><small>{label}</small><p>{value}</p></> : <p>{label}</p>}
          {isOld ? <span className="mem-row-note">{oldMemoryNote(memory, canonicalMemories)}</span> : null}
          {memory.status && memory.status !== "active" && !isOld ? <span className="mem-flag">Not in use</span> : null}
          {memory.sensitivity && memory.sensitivity !== "standard" ? <span className="mem-flag">{sentenceCase(humanizeLabel(memory.sensitivity))}</span> : null}
        </div>
        <div className="history-row-menu mem-row-menu">
          <button className="history-menu-button" type="button" aria-haspopup="menu" aria-expanded={rowMenuId === memory.id} aria-label={`Options for ${label}`} disabled={isSaving} onClick={() => setRowMenuId(rowMenuId === memory.id ? null : memory.id)}><MoreHorizontal aria-hidden="true" /></button>
          {rowMenuId === memory.id ? (
            <div className="history-menu" role="menu">
              <button type="button" role="menuitem" onClick={() => { setRowMenuId(null); openFeedbackFlow(memory); }}><CheckCircle2 aria-hidden="true" />Is this right?</button>
              {active ? <button type="button" role="menuitem" onClick={() => { setRowMenuId(null); openPrivacyFlow(memory); }}><SlidersHorizontal aria-hidden="true" />Where Omi can use this</button> : null}
              {evidenceControl ? <button type="button" role="menuitem" onClick={() => { setRowMenuId(null); setEvidenceItem(memory); }}><Quote aria-hidden="true" />See where Omi learned this</button> : null}
            </div>
          ) : null}
        </div>
      </article>
    );
  }

  function renderCanonicalSection(section: ReturnType<typeof groupCanonicalMemories>[number]) {
    const sectionKey = `memory-${section.id}`;
    const visibleCount = visibleSectionCounts[sectionKey] || 5;
    const hasMore = visibleCount < section.memories.length;
    return (
      <section className="mem-group" key={section.id}>
        <h2>{sentenceCase(section.title)} <span>{section.memories.length}</span></h2>
        <div className="mem-list">{section.memories.slice(0, visibleCount).map(renderCanonicalMemory)}</div>
        {section.memories.length > 5 ? <button className="mem-link" type="button" onClick={() => setVisibleSectionCounts((current) => ({ ...current, [sectionKey]: hasMore ? visibleCount + 5 : 5 }))}>{hasMore ? `Show ${Math.min(5, section.memories.length - visibleCount)} more` : "Show less"}</button> : null}
      </section>
    );
  }

  if (!loaded) return <section className="screen style-screen">{loadError ? <StateView kind="error" title="Couldn't load your memories" detail={loadError} onRetry={firstLoad} /> : <StateView kind="loading" title="Loading your memories…" />}</section>;
  const toggleSection = (key: string, shown: boolean) => setVisibleSectionCounts((current) => {
    const next = { ...current };
    if (shown) delete next[key];
    else next[key] = 1;
    return next;
  });
  return (
    <section className="screen style-screen mem">
      <header className="mem-head">
        <h1>Memories</h1>
        <p>What Omi remembers from your chats. If something's wrong, fix it here.</p>
      </header>
      {error && !reviewItem ? <Notice tone="error">{error}</Notice> : null}
      {openQuestions.length ? (
        <section className="mem-group">
          <h2>Omi isn't sure about <span>{openQuestions.length}</span></h2>
          <p className="mem-group-note">Omi will ask when it fits. Answer in chat any time, or dismiss it.</p>
          <div className="mem-list">
            {openQuestions.map((question) => (
              <article className="mem-row" key={question.id}>
                <div className="mem-row-copy"><p>{question.text}</p></div>
                <div className="mem-row-actions">
                  <a className="mem-link" href="/">Answer in chat</a>
                  <button className="mem-link is-muted" type="button" onClick={() => void dismissQuestion(question.id)}>Not relevant</button>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}
      {canonicalSections.length ? canonicalSections.map(renderCanonicalSection) : <StateView kind="empty" title="No memories yet" detail="Omi remembers things as you chat. Check back after a few conversations." />}
      {canonicalMemoryGroups.old.length || canonicalMemoryGroups.rejected.length ? (
        <div className="mem-footer-links">
          {canonicalMemoryGroups.old.length ? <button className="mem-link is-muted" type="button" onClick={() => toggleSection("old-canonical", showOldCanonical)}>{showOldCanonical ? "Hide old memories" : `Old memories (${canonicalMemoryGroups.old.length})`}</button> : null}
          {canonicalMemoryGroups.rejected.length ? <button className="mem-link is-muted" type="button" onClick={() => toggleSection("rejected-canonical", showRejectedCanonical)}>{showRejectedCanonical ? "Hide memories you rejected" : `Memories you rejected (${canonicalMemoryGroups.rejected.length})`}</button> : null}
        </div>
      ) : null}
      {showOldCanonical ? (
        <section className="mem-group">
          <h2>Old memories <span>{canonicalMemoryGroups.old.length}</span></h2>
          <p className="mem-group-note">Replaced by something newer, or past their end date. Omi keeps them as history and doesn't use them.</p>
          <div className="mem-list">{canonicalMemoryGroups.old.map(renderCanonicalMemory)}</div>
        </section>
      ) : null}
      {showRejectedCanonical ? (
        <section className="mem-group">
          <h2>Memories you rejected <span>{canonicalMemoryGroups.rejected.length}</span></h2>
          <p className="mem-group-note">You marked these as not true. Open one and choose "Feels right" to bring it back.</p>
          <div className="mem-list">{canonicalMemoryGroups.rejected.map(renderCanonicalMemory)}</div>
        </section>
      ) : null}
      {reviewItem && reviewMode ? (
        <div className="confirm-overlay signal-review-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && savingFactId !== reviewItem.id) { setReviewItem(null); setReviewMode(null); setError(""); } }}>
          <section className="confirm-dialog signal-review-dialog" role="dialog" aria-modal="true" aria-labelledby="signal-review-title">
            <div className="confirm-copy">
              <p className="eyebrow">{reviewMode === "feedback" ? "Review signal" : "Usage control"}</p>
              <h2 id="signal-review-title">{reviewMode === "feedback" ? "Is this true about you?" : "Where can Omi use this?"}</h2>
              <p>{reviewItemTitle(reviewItem)}</p>
            </div>
            {reviewMode === "feedback" ? (
              <form className="signal-review-form" onSubmit={(event) => void submitFeedbackFlow(event)}>
                <div className="signal-feedback-options" role="radiogroup" aria-label="Signal feedback">
                  <label className={feedbackRating === "agree" ? "selected" : ""}>
                    <input type="radio" name="signal-feedback" value="agree" checked={feedbackRating === "agree"} onChange={() => { setFeedbackRating("agree"); setFeedbackReasons([]); }} />
                    <span><strong>Feels right</strong><small>Omi will trust this more.</small></span>
                  </label>
                  <label className={feedbackRating === "disagree" ? "selected" : ""}>
                    <input type="radio" name="signal-feedback" value="disagree" checked={feedbackRating === "disagree"} onChange={() => setFeedbackRating("disagree")} />
                    <span><strong>Not true</strong><small>Omi will stop using this.</small></span>
                  </label>
                </div>
                {feedbackRating === "disagree" ? (
                  <div>
                    <p className="privacy-note">What's off? Pick one if it helps.</p>
                    <div className="signal-review-reasons" aria-label="Correction reason">
                      {memoryReviewReasons.map((reason) => (
                        <button
                          className={feedbackReasons.includes(reason.value) ? "selected" : ""}
                          key={reason.value}
                          type="button"
                          onClick={() => setFeedbackReasons((current) => toggleCanonicalMemoryReviewReason(current, reason.value))}
                        >
                          {reason.label}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
                <textarea value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} rows={4} placeholder="Add context or a correction (optional)" />
                {isCanonicalMemory(reviewItem) && feedbackRating === "disagree" ? <p className="privacy-note">It moves to "Memories you rejected". You can bring it back later.</p> : null}
                {error ? <Notice tone="error">{error}</Notice> : null}
                <div className="confirm-actions">
                  <button className="secondary-button" type="button" onClick={() => { setReviewItem(null); setReviewMode(null); setError(""); }} disabled={savingFactId === reviewItem.id}>Cancel</button>
                  <button className={feedbackRating === "disagree" ? "danger-button" : ""} type="submit" disabled={savingFactId === reviewItem.id}>{savingFactId === reviewItem.id ? "Saving…" : "Save"}</button>
                </div>
              </form>
            ) : (
              <form className="signal-review-form" onSubmit={(event) => void submitPrivacyFlow(event)}>
                <p className="privacy-note">Turning both off keeps the memory but stops Omi from using it.</p>
                <label className="signal-toggle-row">
                  <input type="checkbox" checked={privacyForChat} onChange={(event) => setPrivacyForChat(event.target.checked)} />
                  <span><strong>In chats</strong><small>Omi can use this to make replies more personal.</small></span>
                </label>
                <label className="signal-toggle-row">
                  <input type="checkbox" checked={privacyForMatching} onChange={(event) => setPrivacyForMatching(event.target.checked)} />
                  <span><strong>For matching</strong><small>This can help find people you'd get along with.</small></span>
                </label>
                {error ? <Notice tone="error">{error}</Notice> : null}
                <div className="confirm-actions">
                  <button className="secondary-button" type="button" onClick={() => { setReviewItem(null); setReviewMode(null); setError(""); }} disabled={savingFactId === reviewItem.id}>Cancel</button>
                  <button type="submit" disabled={savingFactId === reviewItem.id}>{savingFactId === reviewItem.id ? "Saving…" : "Save"}</button>
                </div>
              </form>
            )}
          </section>
        </div>
      ) : null}
      {evidenceItem ? (
        <div className="confirm-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setEvidenceItem(null); }}>
          <section className="evidence-dialog" role="dialog" aria-modal="true" aria-labelledby="evidence-title">
            <div className="evidence-dialog-header">
              <div>
                <p className="eyebrow">Evidence</p>
                <h2 id="evidence-title">{reviewItemTitle(evidenceItem)}</h2>
                <p>What you said that Omi learned this from.</p>
              </div>
              <button className="evidence-close" type="button" onClick={() => setEvidenceItem(null)} aria-label="Close evidence"><span /></button>
            </div>
            <div className="evidence-summary">
              <span>{confidenceLabel(evidenceItem.confidence)} · {Math.round((evidenceItem.confidence || 0) * 100)}%</span>
              <span>{evidenceItem.evidence?.length || 0} evidence</span>
            </div>
            <div className="evidence-list">
              {evidenceItem.evidence?.length ? evidenceItem.evidence.map((item, index) => {
                const href = evidenceHref(evidenceItem, item);
                return (
                  <article className="evidence-item" key={index}>
                    <div className="evidence-item-body">
                      <span className="evidence-item-index">{index + 1}</span>
                      <blockquote>{evidenceText(item)}</blockquote>
                      <p>
                        {evidenceSourceLabel(evidenceItem, item)}
                        {href ? <> · <a className="evidence-chat-link" href={href} onClick={(event) => openEvidenceSource(event, href)}>Open in chat</a></> : null}
                      </p>
                    </div>
                  </article>
                );
              }) : <div className="evidence-empty">No evidence snippets are stored for this signal yet.</div>}
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function confidenceLevel(confidence?: number) {
  const value = confidence || 0;
  if (value >= 0.75) return "high";
  if (value >= 0.45) return "medium";
  return "low";
}

function confidenceLabel(confidence?: number) {
  const value = confidence || 0;
  if (value >= 0.9) return "Strong";
  if (value >= 0.75) return "Good";
  if (value >= 0.45) return "Learning";
  return "Weak";
}

function signalValues(fact: ProfileFact) {
  const values: string[] = [];
  const fallbackValues: string[] = [];
  collectSignalValues(fact.value, values, fallbackValues);
  const selectedValues = (values.length ? values : fallbackValues.slice(0, 1))
    .flatMap(expandSerializedSignalList);
  const label = String(fact.label || fact.key || "").trim().toLocaleLowerCase();
  const seen = new Set<string>();
  return selectedValues.filter((value) => {
    const identity = value.trim().toLocaleLowerCase();
    if (!identity || identity === label || seen.has(identity)) return false;
    seen.add(identity);
    return true;
  }).slice(0, 8);
}

function expandSerializedSignalList(value: string) {
  const text = value.trim();
  if (!text.startsWith("[") || !text.endsWith("]")) return [text];
  const quotedItems = [...text.matchAll(/["']([^"']+)["']/g)]
    .map((match) => match[1].trim())
    .filter(Boolean);
  return quotedItems.length ? quotedItems : [text];
}

const internalSignalValueKeys = new Set([
  "category", "confidence", "confidence_state", "context_source_id", "evidence",
  "extractor", "fact_type", "import_id", "key", "kind", "llm_review",
  "privacy_level", "rule_candidate", "source_id", "source_kind", "status", "title",
  "usage", "used_for_style", "visibility"
]);

const fallbackSignalValueKeys = new Set([
  "description", "detail", "explanation", "meaning", "reason", "summary",
  "what_we_learned", "why_it_matters"
]);

function collectSignalValues(
  value: unknown,
  output: string[],
  fallbackOutput: string[],
  key = ""
) {
  if (
    key.startsWith("_")
    || internalSignalValueKeys.has(key)
    || value === null
    || value === undefined
    || typeof value === "boolean"
  ) return;
  if (Array.isArray(value)) {
    value.forEach((item) => collectSignalValues(item, output, fallbackOutput));
    return;
  }
  if (typeof value === "object") {
    Object.entries(value as Record<string, unknown>).forEach(([childKey, item]) => {
      collectSignalValues(item, output, fallbackOutput, childKey);
    });
    return;
  }
  const text = String(value).trim();
  if (!text) return;
  if (fallbackSignalValueKeys.has(key)) fallbackOutput.push(text);
  else output.push(text);
}

function isCanonicalMemory(item: ProfileFact | CanonicalMemory): item is CanonicalMemory {
  return "kind" in item;
}

function reviewItemTitle(item: ProfileFact | CanonicalMemory) {
  return sentenceCase(isCanonicalMemory(item) ? humanizeLabel(item.key) : item.label || item.key || "");
}

function evidenceText(item: unknown) {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return "Evidence saved without preview text.";
  const row = item as Record<string, unknown>;
  return String(row.exact_quote || row.text || row.quote || row.message || row.preview || "Evidence saved without preview text.");
}

function evidenceSourceLabel(fact: ProfileFact | CanonicalMemory, item: unknown) {
  const sourceKind = isCanonicalMemory(fact) ? "" : fact.source_kind || "";
  if (!item || typeof item !== "object") return isCanonicalMemory(fact) ? "Source" : humanizeLabel(sourceKind || "source");
  const row = item as Record<string, unknown>;
  if (row.conversation_id || sourceKind === "agent_chat") return "You said";
  if (sourceKind === "whatsapp_import") return "WhatsApp import";
  if (row.context_source_id) return "Saved memory";
  if (sourceKind === "agent_deep_memory") return "Conversation memory";
  return humanizeLabel(String(row.source_kind || sourceKind || "source"));
}

function evidenceHref(fact: ProfileFact | CanonicalMemory, item: unknown) {
  const row = item && typeof item === "object" ? item as Record<string, unknown> : {};
  if (isCanonicalMemory(fact)) {
    return canonicalMemoryEvidenceHref(
      {
        conversation_id: typeof row.conversation_id === "string" ? row.conversation_id : undefined,
        message_index: typeof row.message_index === "number" ? row.message_index : null
      },
      window.location.origin
    );
  }
  const conversationId = String(row.conversation_id || (["agent_chat", "agent_deep_memory", "agent_conversation"].includes(String(fact.source_kind)) ? fact.source_id || "" : ""));
  if (!conversationId) return "";
  const url = new URL("/", window.location.origin);
  url.searchParams.set("conversation_id", conversationId);
  const messageIndex = row.message_index;
  if (typeof messageIndex === "number" || typeof messageIndex === "string") {
    url.hash = "message-" + messageIndex;
  }
  return url.toString();
}

function openEvidenceSource(event: MouseEvent<HTMLAnchorElement>, href: string) {
  const target = new URL(href);
  if (target.origin !== window.location.origin) return;
  event.preventDefault();
  window.history.pushState({}, "", `${target.pathname}${target.search}${target.hash}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function dataPointType(fact: ProfileFact) {
  const savedType = typeof fact.value?._data_point_type === "string" ? fact.value._data_point_type : "";
  if (savedType) return savedType;
  if (fact.confidence_state === "candidate" && !fact.used_for_matching && !fact.used_for_chat_context) return "needs_confirmation";
  if (fact.fact_type === "profile_fact") return "profile_fact";
  if (fact.fact_type === "chat_context_fact" || fact.fact_type === "style_fact" || fact.used_for_chat_context) return "chat_learning";
  if (fact.fact_type === "matching_fact" || fact.used_for_matching) return "matching_fact";
  return "other";
}

function humanizeDataPointType(value: string) {
  if (value === "profile_fact") return "Profile fact";
  if (value === "matching_fact") return "Matching fact";
  if (value === "chat_learning") return "Chat learning";
  if (value === "temporary_context") return "Temporary context";
  if (value === "needs_confirmation") return "Needs confirmation";
  if (value === "do_not_store") return "Do not store";
  return humanizeLabel(value || "Other");
}

function sentenceCase(value: string) {
  const text = value.trim();
  return text ? text[0].toUpperCase() + text.slice(1).toLowerCase() : text;
}

function humanizeLabel(value?: string) {
  return (value || "").replaceAll("_", " ");
}
