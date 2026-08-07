import { type FormEvent, useEffect, useState } from "react";
import { apiErrorMessage, apiFetch } from "../../../lib/api";
import { trackAppEvent } from "../../../lib/appLogger";
import type { ContextSource, ProfileFact, ProfileResponse } from "../types";

export function StylePage() {
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [error, setError] = useState("");
  const [showImport, setShowImport] = useState(false);
  const [importMode, setImportMode] = useState<"memory" | "whatsapp">("memory");
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("Imported context");
  const [userSender, setUserSender] = useState("");
  const [saving, setSaving] = useState(false);
  const [savingFactId, setSavingFactId] = useState<string | null>(null);
  const [reviewFact, setReviewFact] = useState<ProfileFact | null>(null);
  const [reviewMode, setReviewMode] = useState<"feedback" | "privacy" | null>(null);
  const [feedbackRating, setFeedbackRating] = useState<"agree" | "disagree">("agree");
  const [reviewReason, setReviewReason] = useState("");
  const [privacyForChat, setPrivacyForChat] = useState(false);
  const [privacyForMatching, setPrivacyForMatching] = useState(false);
  const [visibleSectionCounts, setVisibleSectionCounts] = useState<Record<string, number>>({});
  const [evidenceFact, setEvidenceFact] = useState<ProfileFact | null>(null);

  async function load() {
    const response = await apiFetch("/api/me/profile");
    if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not load saved memories."));
    setData(await response.json());
  }
  useEffect(() => { load().catch((caught) => setError(caught.message)); }, []);

  const sources = [...(data?.memory_sources || []), ...(data?.style_sources || [])];
  const facts = data?.learned_facts || [];
  const activeFacts = facts.filter((fact) => fact.status !== "rejected");
  const rejectedFacts = facts.filter((fact) => fact.status === "rejected");
  const needsReviewFacts = activeFacts.filter((fact) => !fact.feedback && (fact.confidence || 0) < 0.75);
  const needsReviewIds = new Set(needsReviewFacts.map((fact) => fact.id));
  const reviewRemainingFacts = activeFacts.filter((fact) => !needsReviewIds.has(fact.id));
  const confirmationFacts = reviewRemainingFacts.filter((fact) => dataPointType(fact) === "needs_confirmation");
  const confirmationIds = new Set(confirmationFacts.map((fact) => fact.id));
  const typedFacts = reviewRemainingFacts.filter((fact) => !confirmationIds.has(fact.id));
  const profileFacts = typedFacts.filter((fact) => dataPointType(fact) === "profile_fact");
  const profileIds = new Set(profileFacts.map((fact) => fact.id));
  const matchingFacts = typedFacts.filter((fact) => !profileIds.has(fact.id) && dataPointType(fact) === "matching_fact");
  const matchingIds = new Set(matchingFacts.map((fact) => fact.id));
  const temporaryFacts = typedFacts.filter((fact) => !profileIds.has(fact.id) && !matchingIds.has(fact.id) && dataPointType(fact) === "temporary_context");
  const temporaryIds = new Set(temporaryFacts.map((fact) => fact.id));
  const chatFacts = typedFacts.filter((fact) => !profileIds.has(fact.id) && !matchingIds.has(fact.id) && !temporaryIds.has(fact.id) && dataPointType(fact) === "chat_learning");
  const typedIds = new Set([...profileIds, ...matchingIds, ...temporaryIds, ...chatFacts.map((fact) => fact.id)]);
  const otherFacts = typedFacts.filter((fact) => !typedIds.has(fact.id));
  const notUsedFacts = rejectedFacts;
  const factSections: Array<{ id: string; title: string; summary: string; rows: ProfileFact[] }> = [
    { id: "review", title: "Review these signals", summary: "Tell Omiryn if these are right or wrong. This improves what it remembers about you.", rows: needsReviewFacts },
    { id: "profile", title: "Profile facts", summary: "Stable basics about you, like location, language, identity, or life background.", rows: profileFacts },
    { id: "matching", title: "Matching facts", summary: "Preferences, values, boundaries, relationship intent, lifestyle, and compatibility signals.", rows: matchingFacts },
    { id: "chat", title: "Chat learning", summary: "How Omiryn should talk with you: tone, pacing, question style, humor, and sensitivities.", rows: chatFacts },
    { id: "temporary", title: "Temporary context", summary: "Short-lived context from the current phase of life or current conversation.", rows: temporaryFacts },
    { id: "confirmation", title: "Needs confirmation", summary: "Possible signals Omiryn should ask about before trusting or using strongly.", rows: confirmationFacts },
    { id: "other", title: "Other saved signals", summary: "Older or imported signals that do not yet map cleanly to the V2 types.", rows: otherFacts }
  ].filter((section) => section.rows.length);
  const showNotUsed = visibleSectionCounts["not-used"] !== undefined;

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
      trackAppEvent("memory_import_completed", { source_type: importMode === "whatsapp" ? "whatsapp_chat" : "manual_notes" }, { page: "style" });
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
      trackAppEvent(eventName, { fact_category: fact.category || "unknown" }, { page: "style", target_type: "profile_fact", target_id: fact.id });
      setReviewFact(null);
      setReviewMode(null);
      setReviewReason("");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not update that signal.");
    } finally {
      setSavingFactId(null);
    }
  }

  function openFeedbackFlow(fact: ProfileFact, initialRating?: "agree" | "disagree") {
    setReviewFact(fact);
    setReviewMode("feedback");
    setFeedbackRating(initialRating || (fact.feedback?.rating === "disagree" ? "disagree" : "agree"));
    setReviewReason("");
    setError("");
  }

  function openPrivacyFlow(fact: ProfileFact) {
    setReviewFact(fact);
    setReviewMode("privacy");
    setPrivacyForChat(Boolean(fact.used_for_chat_context));
    setPrivacyForMatching(Boolean(fact.used_for_matching));
    setReviewReason("");
    setError("");
  }

  async function saveSignalFeedback(fact: ProfileFact, rating: "agree" | "disagree", comment = "") {
    setSavingFactId(fact.id);
    setError("");
    try {
      const response = await apiFetch(`/api/me/profile-facts/${fact.id}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rating,
          reason: rating === "disagree" ? "wrong" : "feels_right",
          comment: comment.trim() || null
        })
      });
      if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not save feedback."));
      trackAppEvent("learned_signal_feedback_sent", { fact_category: fact.category || "unknown", rating }, { page: "style", target_type: "profile_fact", target_id: fact.id });
      setReviewFact(null);
      setReviewMode(null);
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
    if (!reviewFact) return;
    if (feedbackRating === "disagree" && (reviewFact.confidence || 0) >= 0.9 && reviewReason.trim().length < 8) {
      setError("Add a short reason so Omiryn can correct a high-confidence signal.");
      return;
    }
    await saveSignalFeedback(reviewFact, feedbackRating, reviewReason);
  }

  async function submitPrivacyFlow(event: FormEvent) {
    event.preventDefault();
    if (!reviewFact) return;
    await patchFact(
      reviewFact,
      {
        status: "active",
        used_for_chat_context: privacyForChat,
        used_for_matching: privacyForMatching
      },
      "learned_signal_privacy_updated"
    );
  }

  function renderSignalCard(fact: ProfileFact, sectionId = "") {
    const confidence = Math.round((fact.confidence || 0) * 100);
    const hasEvidence = Boolean(fact.evidence?.length);
    const isSaving = savingFactId === fact.id;
    const wasRejected = fact.status === "rejected";
    return (
      <article className={`profile-fact-card signal-review-card ${wasRejected ? "is-rejected" : ""}`} key={fact.id}>
        <div className="profile-fact-card-top">
          <div>
            <strong>{fact.label || fact.key}</strong>
            <div className="profile-fact-meta">
              <span className={`confidence-pill ${confidenceLevel(fact.confidence)}`}>{confidenceLabel(fact.confidence)} · {confidence}%</span>
              <span className="fact-tag fact-tag-type">{humanizeDataPointType(dataPointType(fact))}</span>
              {fact.category ? <span className="fact-tag fact-tag-key">{humanizeLabel(fact.category)}</span> : null}
              {fact.confidence_state && fact.confidence_state !== "active" ? <span className="fact-tag fact-tag-status">{humanizeLabel(fact.confidence_state)}</span> : null}
              {hasEvidence ? (
                <button className="fact-tag fact-evidence-trigger" type="button" onClick={() => setEvidenceFact(fact)}>
                  {fact.evidence?.length} evidence
                </button>
              ) : null}
            </div>
          </div>
        </div>
        {fact.feedback?.rating ? <p>{fact.feedback.rating === "agree" ? "Feedback saved: feels right." : "Feedback saved: not true."}</p> : null}
        <div className="signal-card-actions">
          {!wasRejected ? (
            <>
              {sectionId === "review" ? (
                <>
                  <button className="secondary-button feedback-signal-button" type="button" disabled={isSaving} onClick={() => void saveSignalFeedback(fact, "agree")}>Looks right</button>
                  <button className="secondary-button" type="button" disabled={isSaving} onClick={() => openFeedbackFlow(fact, "disagree")}>Correct / mark wrong</button>
                </>
              ) : (
                <button className="secondary-button feedback-signal-button" type="button" disabled={isSaving} onClick={() => openFeedbackFlow(fact)}>Review accuracy</button>
              )}
              <button className="secondary-button" type="button" disabled={isSaving} onClick={() => openPrivacyFlow(fact)}>Usage</button>
            </>
          ) : (
            <button className="secondary-button" type="button" disabled={isSaving} onClick={() => void patchFact(fact, { status: "active", confirmed: false }, "learned_signal_restored")}>Restore</button>
          )}
        </div>
      </article>
    );
  }

  function renderFactSection(section: { id: string; title: string; summary: string; rows: ProfileFact[] }) {
    const visibleCount = visibleSectionCounts[section.id] || 5;
    const visibleRows = section.rows.slice(0, visibleCount);
    const hasMore = visibleCount < section.rows.length;
    return (
      <section className={`profile-fact-group signal-section signal-section-${section.id}`} key={section.id}>
        <div className="profile-fact-group-heading">
          <div>
            <h3>{section.title}</h3>
            <p>{section.summary}</p>
          </div>
          <span>{section.rows.length}</span>
        </div>
        <div className="profile-fact-list">
          {visibleRows.map((fact) => renderSignalCard(fact, section.id))}
        </div>
        {section.rows.length > 5 ? (
          <button
            className="secondary-button signal-show-more"
            type="button"
            onClick={() => setVisibleSectionCounts((current) => ({
              ...current,
              [section.id]: hasMore ? visibleCount + 5 : 5
            }))}
          >
            {hasMore ? `Show ${Math.min(5, section.rows.length - visibleCount)} more` : "Show less"}
          </button>
        ) : null}
      </section>
    );
  }

  return (
    <section className="screen style-screen">
      <div className="style-hero">
        <div className="screen-copy compact">
          <p className="eyebrow">Style</p>
          <h1>Omiryn's understanding.</h1>
          <p>Review AI-inferred signals, confirm what feels right, and control what Omiryn can use.</p>
        </div>
      </div>
      <div className="style-snapshot-grid" aria-label="Signal summary">
        <div className="style-snapshot-card">
          <span>Active signals</span>
          <strong>{activeFacts.length}</strong>
          <small>Available for personalization</small>
        </div>
        <div className="style-snapshot-card">
          <span>To review</span>
          <strong>{needsReviewFacts.length}</strong>
          <small>Low-confidence or unconfirmed</small>
        </div>
        <div className="style-snapshot-card">
          <span>Used for matching</span>
          <strong>{matchingFacts.length}</strong>
          <small>Can affect future suggestions</small>
        </div>
        <div className="style-snapshot-card">
          <span>Chat learning</span>
          <strong>{chatFacts.length}</strong>
          <small>Can shape Omiryn's replies</small>
        </div>
      </div>
      <div className="style-layout">
        <section className="profile-panel profile-panel-wide style-learning-panel">
          <div className="panel-heading profile-facts-heading">
            <div>
              <p className="eyebrow">AI signals</p>
              <h2>Review what Omiryn thinks</h2>
              <p>Each point is an AI inference, not a permanent label. Sections show the saved data-point type Omiryn is using internally.</p>
              <p className="privacy-note">Marked-wrong signals are not used for personalization or matching. High-confidence rejections ask for a correction to help the AI improve.</p>
              <p className="privacy-note">“Do not store” points are intentionally skipped, so they do not appear here.</p>
            </div>
            <span className="profile-fact-total">{facts.length} signals</span>
          </div>
          <div className="profile-fact-groups">
            {facts.length ? factSections.map(renderFactSection) : <div className="profile-facts-empty"><strong>No learned signals yet.</strong><span>Chat naturally with Omiryn and this section will fill up.</span></div>}
            {notUsedFacts.length ? (
              <div className="signal-archive-toggle-row">
                <button
                  className="secondary-button signal-show-more"
                  type="button"
                  onClick={() => setVisibleSectionCounts((current) => {
                    const next = { ...current };
                    if (showNotUsed) delete next["not-used"];
                    else next["not-used"] = 5;
                    return next;
                  })}
                >
                  {showNotUsed ? "Hide not used signals" : `Show not used signals (${notUsedFacts.length})`}
                </button>
              </div>
            ) : null}
            {showNotUsed ? renderFactSection({
              id: "not-used",
              title: "Not used by Omiryn",
              summary: "Signals you turned off or marked wrong. Omiryn will not use them for personalization or matching.",
              rows: notUsedFacts
            }) : null}
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
          {error ? <p className="legacy-inline-error">{error}</p> : null}
        </section> */}
      </div>
      {reviewFact && reviewMode ? (
        <div className="confirm-overlay signal-review-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && savingFactId !== reviewFact.id) { setReviewFact(null); setReviewMode(null); setError(""); } }}>
          <section className="confirm-dialog signal-review-dialog" role="dialog" aria-modal="true" aria-labelledby="signal-review-title">
            <div className="confirm-copy">
              <p className="eyebrow">{reviewMode === "feedback" ? "Review signal" : "Usage control"}</p>
              <h2 id="signal-review-title">{reviewMode === "feedback" ? "Is this true about you?" : "Where can Omiryn use this?"}</h2>
              <p>{reviewFact.label || reviewFact.key}</p>
            </div>
            {reviewMode === "feedback" ? (
              <form className="signal-review-form" onSubmit={(event) => void submitFeedbackFlow(event)}>
                <div className="signal-feedback-options" role="radiogroup" aria-label="Signal feedback">
                  <label className={feedbackRating === "agree" ? "selected" : ""}>
                    <input type="radio" name="signal-feedback" value="agree" checked={feedbackRating === "agree"} onChange={() => setFeedbackRating("agree")} />
                    <span><strong>Feels right</strong><small>Omiryn can trust this more.</small></span>
                  </label>
                  <label className={feedbackRating === "disagree" ? "selected" : ""}>
                    <input type="radio" name="signal-feedback" value="disagree" checked={feedbackRating === "disagree"} onChange={() => setFeedbackRating("disagree")} />
                    <span><strong>Not true</strong><small>Omiryn should stop using this.</small></span>
                  </label>
                </div>
                <p className="privacy-note">{feedbackRating === "disagree" && (reviewFact.confidence || 0) >= 0.9 ? "This is a high-confidence signal, so a short correction is required." : "Optional: add a correction or context, especially if the signal is only partly right."}</p>
                <textarea value={reviewReason} onChange={(event) => setReviewReason(event.target.value)} rows={4} placeholder={feedbackRating === "disagree" && (reviewFact.confidence || 0) >= 0.9 ? "Required: what did Omiryn get wrong?" : "Optional note"} />
                {error ? <p className="legacy-inline-error">{error}</p> : null}
                <div className="confirm-actions">
                  <button className="secondary-button" type="button" onClick={() => { setReviewFact(null); setReviewMode(null); setError(""); }} disabled={savingFactId === reviewFact.id}>Cancel</button>
                  <button className={feedbackRating === "disagree" ? "danger-button" : ""} type="submit" disabled={savingFactId === reviewFact.id || (feedbackRating === "disagree" && (reviewFact.confidence || 0) >= 0.9 && reviewReason.trim().length < 8)}>{savingFactId === reviewFact.id ? "Saving..." : "Save feedback"}</button>
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
                {error ? <p className="legacy-inline-error">{error}</p> : null}
                <div className="confirm-actions">
                  <button className="secondary-button" type="button" onClick={() => { setReviewFact(null); setReviewMode(null); setError(""); }} disabled={savingFactId === reviewFact.id}>Cancel</button>
                  <button type="submit" disabled={savingFactId === reviewFact.id}>{savingFactId === reviewFact.id ? "Saving..." : "Save privacy"}</button>
                </div>
              </form>
            )}
          </section>
        </div>
      ) : null}
      {evidenceFact ? (
        <div className="confirm-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setEvidenceFact(null); }}>
          <section className="evidence-dialog" role="dialog" aria-modal="true" aria-labelledby="evidence-title">
            <div className="evidence-dialog-header">
              <div>
                <p className="eyebrow">Evidence</p>
                <h2 id="evidence-title">{evidenceFact.label || evidenceFact.key}</h2>
                <p>These are the messages or source snippets Omiryn used for this signal.</p>
              </div>
              <button className="evidence-close" type="button" onClick={() => setEvidenceFact(null)} aria-label="Close evidence"><span /></button>
            </div>
            <div className="evidence-summary">
              <span>{confidenceLabel(evidenceFact.confidence)} · {Math.round((evidenceFact.confidence || 0) * 100)}%</span>
              <span>{evidenceFact.evidence?.length || 0} evidence</span>
            </div>
            <div className="evidence-list">
              {evidenceFact.evidence?.length ? evidenceFact.evidence.map((item, index) => {
                const href = evidenceHref(evidenceFact, item);
                return (
                  <article className="evidence-item" key={index}>
                    <div className="evidence-item-body">
                      <span className="evidence-item-index">{index + 1}</span>
                      <blockquote>{evidenceText(item)}</blockquote>
                      <p>
                        {evidenceSourceLabel(evidenceFact, item)}
                        {href ? <> · <a className="evidence-chat-link" href={href}>Open source</a></> : null}
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

function evidenceText(item: unknown) {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return "Evidence saved without preview text.";
  const row = item as Record<string, unknown>;
  return String(row.text || row.quote || row.message || row.preview || "Evidence saved without preview text.");
}

function evidenceSourceLabel(fact: ProfileFact, item: unknown) {
  if (!item || typeof item !== "object") return humanizeLabel(fact.source_kind || "source");
  const row = item as Record<string, unknown>;
  if (row.conversation_id || fact.source_kind === "agent_chat") return "User message";
  if (fact.source_kind === "whatsapp_import") return "WhatsApp import";
  if (row.context_source_id) return "Saved memory";
  if (fact.source_kind === "agent_deep_memory") return "Conversation memory";
  return humanizeLabel(String(row.source_kind || fact.source_kind || "source"));
}

function evidenceHref(fact: ProfileFact, item: unknown) {
  const row = item && typeof item === "object" ? item as Record<string, unknown> : {};
  const conversationId = String(row.conversation_id || (["agent_chat", "agent_deep_memory", "agent_conversation"].includes(String(fact.source_kind)) ? fact.source_id || "" : ""));
  if (!conversationId) return "";
  const url = new URL("/", window.location.origin);
  url.searchParams.set("conversation_id", conversationId);
  const messageIndex = row.message_index;
  if (typeof messageIndex === "number" || typeof messageIndex === "string") {
    url.hash = `message-${messageIndex}`;
  }
  return url.toString();
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
