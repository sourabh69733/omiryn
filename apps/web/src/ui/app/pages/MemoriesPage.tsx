import { type FormEvent, type MouseEvent, useEffect, useState } from "react";
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
  }
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

  function renderCanonicalMemory(memory: CanonicalMemory) {
    const confidence = Math.round((memory.confidence || 0) * 100);
    const value = canonicalMemoryValueText(memory.value);
    const controls = canonicalMemoryControls(memory.evidence?.length || 0);
    const evidenceControl = controls.find((control) => control.id === "evidence");
    const reviewControl = controls.find((control) => control.id === "review");
    const usageControl = controls.find((control) => control.id === "usage");
    const isOld = oldIds.has(memory.id);
    const active = !isOld && (!memory.status || memory.status === "active");
    const isSaving = savingFactId === memory.id;
    const cardTone = isOld ? "is-old" : canonicalMemoryCardTone(memory);
    return (
      <article className={`profile-fact-card signal-review-card ${cardTone}`} key={memory.id}>
        <div className="profile-fact-card-top">
          <div>
            <strong>{humanizeLabel(memory.key)}</strong>
            {value ? <p className="profile-fact-values">{value}</p> : null}
            {isOld ? <p className="memory-old-note">{oldMemoryNote(memory, canonicalMemories)}</p> : null}
            <div className="profile-fact-meta">
              {isOld ? null : <span className={"confidence-pill " + confidenceLevel(memory.confidence)}>{confidenceLabel(memory.confidence)} · {confidence}%</span>}
              <span className="fact-tag fact-tag-type">{humanizeLabel(memory.kind)}</span>
              {(memory.purposes || []).map((purpose) => <span className="fact-tag fact-tag-key" key={purpose}>{humanizeLabel(purpose)}</span>)}
              {memory.status && memory.status !== "active" && !isOld ? <span className="fact-tag fact-tag-status">{humanizeLabel(memory.status)}</span> : null}
              {memory.sensitivity && memory.sensitivity !== "standard" ? <span className="fact-tag fact-tag-status">{humanizeLabel(memory.sensitivity)}</span> : null}
              {evidenceControl ? (
                <button className="fact-tag fact-evidence-trigger" type="button" onClick={() => setEvidenceItem(memory)}>
                  {evidenceControl.label}
                </button>
              ) : null}
            </div>
          </div>
        </div>
        <div className="signal-card-actions">
          <button className="secondary-button feedback-signal-button" type="button" disabled={isSaving} onClick={() => openFeedbackFlow(memory)}>{reviewControl?.label}</button>
          {active ? <button className="secondary-button" type="button" disabled={isSaving} onClick={() => openPrivacyFlow(memory)}>{usageControl?.label}</button> : null}
        </div>
      </article>
    );
  }

  function renderCanonicalSection(section: ReturnType<typeof groupCanonicalMemories>[number]) {
    const sectionKey = `memory-${section.id}`;
    const visibleCount = visibleSectionCounts[sectionKey] || 5;
    const hasMore = visibleCount < section.memories.length;
    return (
      <section className={`profile-fact-group signal-section signal-section-${section.id}`} key={section.id}>
        <div className="profile-fact-group-heading"><div><h3>{section.title}</h3><p>{section.summary}</p></div><span>{section.memories.length}</span></div>
        <div className="profile-fact-list">{section.memories.slice(0, visibleCount).map(renderCanonicalMemory)}</div>
        {section.memories.length > 5 ? <button className="secondary-button signal-show-more" type="button" onClick={() => setVisibleSectionCounts((current) => ({ ...current, [sectionKey]: hasMore ? visibleCount + 5 : 5 }))}>{hasMore ? `Show ${Math.min(5, section.memories.length - visibleCount)} more` : "Show less"}</button> : null}
      </section>
    );
  }

  if (!loaded) return <section className="screen style-screen">{loadError ? <StateView kind="error" title="Couldn't load your memories" detail={loadError} onRetry={firstLoad} /> : <StateView kind="loading" title="Loading your memories…" />}</section>;
  return (
    <section className="screen style-screen">
      <div className="style-hero">
        <div className="screen-copy compact">
          <p className="eyebrow">Memories</p>
          <h1>What Omiryn remembers.</h1>
          <p>Review what Omiryn has learned, confirm what feels right, and control what it can use.</p>
        </div>
      </div>
      <div className="style-snapshot-grid" aria-label="Memory summary">
        <div className="style-snapshot-card">
          <span>Memories</span>
          <strong>{canonicalMemories.length}</strong>
          <small>Things Omi remembers about you</small>
        </div>
        <div className="style-snapshot-card">
          <span>Current</span>
          <strong>{canonicalMemoryGroups.active.length}</strong>
          <small>What Omi uses now</small>
        </div>
        <div className="style-snapshot-card">
          <span>Matching use</span>
          <strong>{canonicalMemories.filter((memory) => memory.allowed_uses?.includes("matching")).length}</strong>
          <small>Allowed to support future matching</small>
        </div>
      </div>
      <div className="style-layout">
        <section className="profile-panel profile-panel-wide style-learning-panel">
          <div className="panel-heading profile-facts-heading">
            <div>
              <p className="eyebrow">Memories</p>
              <h2>What Omiryn remembers</h2>
              <p>Things Omi picked up from your chats, grouped by type.</p>
              <p className="privacy-note">Purpose describes why a memory matters. Allowed use controls where Omiryn may use it.</p>
            </div>
            <span className="profile-fact-total">{canonicalMemories.length} memories</span>
          </div>
          <div className="profile-fact-groups">
            {canonicalSections.length ? canonicalSections.map(renderCanonicalSection) : <StateView kind="empty" title="No memories yet" detail="Omi remembers things as you chat. Check back after a few conversations." />}
            {canonicalMemoryGroups.old.length ? (
              <div className="signal-archive-toggle-row">
                <button
                  className="secondary-button signal-show-more"
                  type="button"
                  onClick={() => setVisibleSectionCounts((current) => {
                    const next = { ...current };
                    if (showOldCanonical) delete next["old-canonical"];
                    else next["old-canonical"] = 1;
                    return next;
                  })}
                >
                  {showOldCanonical ? "Hide old memories" : `Show old memories (${canonicalMemoryGroups.old.length})`}
                </button>
              </div>
            ) : null}
            {showOldCanonical ? (
              <section className="profile-fact-group signal-section signal-section-old">
                <div className="profile-fact-group-heading"><div><h3>Old memories</h3><p>Replaced by something newer, or past their end date. Omi keeps them as history and doesn't use them.</p></div><span>{canonicalMemoryGroups.old.length}</span></div>
                <div className="profile-fact-list">{canonicalMemoryGroups.old.map(renderCanonicalMemory)}</div>
              </section>
            ) : null}
            {canonicalMemoryGroups.rejected.length ? (
              <div className="signal-archive-toggle-row">
                <button
                  className="secondary-button signal-show-more"
                  type="button"
                  onClick={() => setVisibleSectionCounts((current) => {
                    const next = { ...current };
                    if (showRejectedCanonical) delete next["rejected-canonical"];
                    else next["rejected-canonical"] = 1;
                    return next;
                  })}
                >
                  {showRejectedCanonical ? "Hide rejected memories" : `Show rejected memories (${canonicalMemoryGroups.rejected.length})`}
                </button>
              </div>
            ) : null}
            {showRejectedCanonical ? (
              <section className="profile-fact-group signal-section signal-section-not-used">
                <div className="profile-fact-group-heading"><div><h3>Rejected memories</h3><p>Memories you marked as not true. Review one again to restore it.</p></div><span>{canonicalMemoryGroups.rejected.length}</span></div>
                <div className="profile-fact-list">{canonicalMemoryGroups.rejected.map(renderCanonicalMemory)}</div>
              </section>
            ) : null}
          </div>
        </section>

        {/* <section className="profile-panel profile-panel-wide style-context-panel">
          <div className="style-section-heading">
            <div>
              <p className="eyebrow">Memories</p>
              <h2>Saved context about you</h2>
              <p>Add WhatsApp exports, profile notes, or any bigger context that should stay available across conversations.</p>
              <p className="privacy-note">Only add content you have the right to share. Do not upload passwords, IDs, private third-party secrets, or sensitive details you want kept out of personalization.</p>
            </div>
            <span className="profile-fact-total">{sources.length} memories</span>
          </div>
          <div className="context-action-grid">
            <button className="context-action-button" type="button" onClick={() => { setImportMode("whatsapp"); setTitle("My WhatsApp style"); setShowImport(true); }}>
              <span className="context-card-icon">Aa</span>
              <strong>Import WhatsApp</strong>
              <small>Use a chat export to learn your natural tone.</small>
            </button>
            <button className="context-action-button" type="button" onClick={() => { setImportMode("memory"); setTitle("Imported context"); setShowImport(true); }}>
              <span className="context-card-icon">+</span>
              <strong>Add memory</strong>
              <small>Paste a profile summary, notes, or important details.</small>
            </button>
          </div>
          {showImport ? <form className="react-memory-form" onSubmit={importContext}><p className="privacy-note">{importMode === "whatsapp" ? "By importing a WhatsApp export, you confirm you have the right to upload it. Omiryn will not message people from the export." : "Saved memories can be used as long-term context in chat and future matching features."}</p><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Memory title" />{importMode === "whatsapp" ? <><input type="file" accept=".txt,text/plain" onChange={(event) => { const file = event.target.files?.[0]; if (file) void file.text().then(setContent); }} /><input value={userSender} onChange={(event) => setUserSender(event.target.value)} placeholder="Your sender name (optional)" /></> : null}<textarea value={content} onChange={(event) => setContent(event.target.value)} rows={7} placeholder={importMode === "whatsapp" ? "Choose a WhatsApp .txt export or paste it here..." : "Paste at least 20 characters..."} /><div><button className="secondary-button" type="button" onClick={() => setShowImport(false)}>Cancel</button><button type="submit" disabled={saving || content.trim().length < (importMode === "whatsapp" ? 50 : 20)}>{saving ? "Saving..." : importMode === "whatsapp" ? "Import chat" : "Save memory"}</button></div></form> : null}
          <div className="context-source-list">
            {sources.length ? sources.map((source) => (
              <article className="profile-source-item" key={source.id}>
                <div className="profile-source-body">
                  <strong>{source.title || "Saved memory"}</strong>
                  <span>{humanizeLabel(source.source_type || "memory")} · {(source.content_length || 0).toLocaleString()} chars</span>
                  <p>{source.preview}</p>
                </div>
                <button className="secondary-button" type="button" onClick={() => void removeSource(source.id)}>Remove</button>
              </article>
            )) : <div className="table-empty">No saved memories yet.</div>}
          </div>
          {error ? <Notice tone="error">{error}</Notice> : null}
        </section> */}
      </div>
      {reviewItem && reviewMode ? (
        <div className="confirm-overlay signal-review-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && savingFactId !== reviewItem.id) { setReviewItem(null); setReviewMode(null); setError(""); } }}>
          <section className="confirm-dialog signal-review-dialog" role="dialog" aria-modal="true" aria-labelledby="signal-review-title">
            <div className="confirm-copy">
              <p className="eyebrow">{reviewMode === "feedback" ? "Review signal" : "Usage control"}</p>
              <h2 id="signal-review-title">{reviewMode === "feedback" ? "Is this true about you?" : "Where can Omiryn use this?"}</h2>
              <p>{reviewItemTitle(reviewItem)}</p>
            </div>
            {reviewMode === "feedback" ? (
              <form className="signal-review-form" onSubmit={(event) => void submitFeedbackFlow(event)}>
                <div className="signal-feedback-options" role="radiogroup" aria-label="Signal feedback">
                  <label className={feedbackRating === "agree" ? "selected" : ""}>
                    <input type="radio" name="signal-feedback" value="agree" checked={feedbackRating === "agree"} onChange={() => { setFeedbackRating("agree"); setFeedbackReasons([]); }} />
                    <span><strong>Feels right</strong><small>Omiryn can trust this more.</small></span>
                  </label>
                  <label className={feedbackRating === "disagree" ? "selected" : ""}>
                    <input type="radio" name="signal-feedback" value="disagree" checked={feedbackRating === "disagree"} onChange={() => setFeedbackRating("disagree")} />
                    <span><strong>Not true</strong><small>Omiryn should stop using this.</small></span>
                  </label>
                </div>
                {feedbackRating === "disagree" ? (
                  <div>
                    <p className="privacy-note">What needs correcting? Choose a tag if helpful.</p>
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
                {isCanonicalMemory(reviewItem) && feedbackRating === "disagree" ? <p className="privacy-note">This moves the memory to the hidden rejected section without deleting its evidence.</p> : null}
                {error ? <Notice tone="error">{error}</Notice> : null}
                <div className="confirm-actions">
                  <button className="secondary-button" type="button" onClick={() => { setReviewItem(null); setReviewMode(null); setError(""); }} disabled={savingFactId === reviewItem.id}>Cancel</button>
                  <button className={feedbackRating === "disagree" ? "danger-button" : ""} type="submit" disabled={savingFactId === reviewItem.id}>{savingFactId === reviewItem.id ? "Saving..." : "Save feedback"}</button>
                </div>
              </form>
            ) : (
              <form className="signal-review-form" onSubmit={(event) => void submitPrivacyFlow(event)}>
                <p className="privacy-note">This controls where the saved signal may be used. Turning both off keeps it stored but prevents Omiryn from using it.</p>
                <label className="signal-toggle-row">
                  <input type="checkbox" checked={privacyForChat} onChange={(event) => setPrivacyForChat(event.target.checked)} />
                  <span><strong>Use for personalization</strong><small>Lets Omiryn use this signal to make replies more relevant.</small></span>
                </label>
                <label className="signal-toggle-row">
                  <input type="checkbox" checked={privacyForMatching} onChange={(event) => setPrivacyForMatching(event.target.checked)} />
                  <span><strong>Use for matching</strong><small>Lets this signal affect compatible people later.</small></span>
                </label>
                {error ? <Notice tone="error">{error}</Notice> : null}
                <div className="confirm-actions">
                  <button className="secondary-button" type="button" onClick={() => { setReviewItem(null); setReviewMode(null); setError(""); }} disabled={savingFactId === reviewItem.id}>Cancel</button>
                  <button type="submit" disabled={savingFactId === reviewItem.id}>{savingFactId === reviewItem.id ? "Saving..." : "Save privacy"}</button>
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
                <p>These are the messages or source snippets Omiryn used for this signal.</p>
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
                        {href ? <> · <a className="evidence-chat-link" href={href} onClick={(event) => openEvidenceSource(event, href)}>Open source</a></> : null}
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
  return isCanonicalMemory(item) ? humanizeLabel(item.key) : item.label || item.key;
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
  if (row.conversation_id || sourceKind === "agent_chat") return "User message";
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

function humanizeLabel(value?: string) {
  return (value || "").replaceAll("_", " ");
}
