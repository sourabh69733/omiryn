import { type FormEvent, useEffect, useRef, useState } from "react";
import { Camera, ChevronRight, MapPin, Plus, X } from "lucide-react";
import { apiErrorMessage, apiFetch, signOut } from "../../../lib/api";
import { trackAppEvent } from "../../../lib/appLogger";
import { Notice, StateView } from "../StateView";
import type { DataRequest, Profile, ProfileResponse } from "../types";
import { blobPath } from "../vibeRing";

type Intro = { intro: string | null; chips: string[]; ready: boolean };

// Your profile: photos, basics and what Omi has picked up about you, with account actions below.
export function ProfilePage({ onVibe }: { onVibe?: () => void }) {
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [form, setForm] = useState<Profile>({});
  const [status, setStatus] = useState("");
  const [loadError, setLoadError] = useState("");
  const [dataRequests, setDataRequests] = useState<DataRequest[]>([]);
  const [requestStatus, setRequestStatus] = useState("");
  const [photoStatus, setPhotoStatus] = useState("");
  const [sendingRequest, setSendingRequest] = useState(false);
  const [pendingDataRequest, setPendingDataRequest] = useState<"export" | "deletion" | null>(null);
  const photoInput = useRef<HTMLInputElement | null>(null);
  const [photoSlot, setPhotoSlot] = useState(0);
  const [uploadingPhotoSlot, setUploadingPhotoSlot] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  // undefined while loading; the page never waits on it.
  const [intro, setIntro] = useState<Intro | undefined>(undefined);
  async function load() { const response = await apiFetch("/api/me/profile"); if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not load profile.")); const next = await response.json() as ProfileResponse; setData(next); setForm(next.profile || {}); setStatus(""); const requestResponse = await apiFetch("/api/me/data-requests"); if (requestResponse.ok) setDataRequests(((await requestResponse.json()).requests || []) as DataRequest[]); }
  function firstLoad() { setLoadError(""); load().catch((caught) => setLoadError(caught.message)); }
  useEffect(firstLoad, []);
  useEffect(() => {
    apiFetch("/api/me/intro")
      .then((response) => (response.ok ? response.json() : { intro: null, chips: [], ready: false }))
      .then((value: Intro) => setIntro(value))
      .catch(() => setIntro({ intro: null, chips: [], ready: false }));
  }, []);
  async function save(event: FormEvent) { event.preventDefault(); setStatus("Saving profile…"); const response = await apiFetch("/api/me/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name: form.display_name || null, age: Number(form.age), gender: form.gender, city: form.city || null, phone: form.phone || null }) }); if (!response.ok) { setStatus(await apiErrorMessage(response, "Could not save profile.")); return; } trackAppEvent("profile_saved", {}, { page: "profile" }); setStatus("Profile saved."); setEditing(false); await load(); }
  async function submitDataRequest(requestType: "export" | "deletion") {
    setSendingRequest(true);
    setRequestStatus("");
    if (requestType === "deletion") {
      const response = await apiFetch("/api/me/account-data?confirm=true", { method: "DELETE" });
      if (!response.ok) {
        setRequestStatus(await apiErrorMessage(response, "Could not delete account data."));
        setSendingRequest(false);
        return;
      }
      trackAppEvent("data_deletion_requested", { request_type: requestType }, { page: "profile" });
      setPendingDataRequest(null);
      setRequestStatus("Account data deleted.");
      setSendingRequest(false);
      await signOut();
      return;
    }
    const response = await apiFetch("/api/me/data-requests", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request_type: requestType, message: "Please export my account and personal data." }) });
    if (!response.ok) {
      setRequestStatus(await apiErrorMessage(response, "Could not send request."));
      setSendingRequest(false);
      return;
    }
    trackAppEvent("data_export_requested", { request_type: requestType }, { page: "profile" });
    setPendingDataRequest(null);
    setRequestStatus("Request sent.");
    setSendingRequest(false);
    await load();
  }
  async function upload(file?: File) {
    if (!file) return;
    const slot = photoSlot;
    setUploadingPhotoSlot(slot);
    setPhotoStatus("Uploading photo...");
    try {
      const response = await apiFetch(`/api/me/profile-photo?slot=${slot}`, { method: "PUT", headers: { "Content-Type": file.type }, body: await file.arrayBuffer() });
      if (!response.ok) {
        setPhotoStatus(await apiErrorMessage(response, "Could not upload photo."));
        return;
      }
      await load();
      setPhotoStatus("Photo uploaded.");
    } finally {
      setUploadingPhotoSlot(null);
      if (photoInput.current) photoInput.current.value = "";
    }
  }
  async function removePhoto(slot: number) {
    setUploadingPhotoSlot(slot);
    setPhotoStatus("Removing photo...");
    try {
      const response = await apiFetch(`/api/me/profile-photo?slot=${slot}`, { method: "DELETE" });
      if (!response.ok) {
        setPhotoStatus(await apiErrorMessage(response, "Could not remove photo."));
        return;
      }
      await load();
      setPhotoStatus("Photo removed.");
    } finally {
      setUploadingPhotoSlot(null);
    }
  }
  const photos = form.profile_photo_urls?.length ? form.profile_photo_urls : form.profile_photo_url ? [form.profile_photo_url] : [];
  const maxPhotoCount = Math.max(1, Math.min(4, data?.profile_photo_max_count || 4));
  const photoSlots = Array.from({ length: maxPhotoCount }, (_, index) => index);
  const isPhotoStatusError = /could not|limit|quota|up to|try again/i.test(photoStatus);
  if (!data) return <section className="screen profile-screen">{loadError ? <StateView kind="error" title="Couldn't load your profile" detail={loadError} onRetry={firstLoad} /> : <StateView kind="loading" title="Loading your profile…" />}</section>;
  const seed = data.user?.email || form.display_name || "omiryn";
  const firstName = (form.display_name || "").split(" ")[0] || "You";
  const genderLabel = { woman: "Woman", man: "Man", non_binary: "Non-binary" }[form.gender || ""] || "Prefer not to say";
  const pickPhoto = (slot: number) => { setPhotoSlot(slot); setPhotoStatus(""); photoInput.current?.click(); };
  return (
    <section className="screen profile-screen pf">
      <input ref={photoInput} className="profile-photo-input" type="file" accept="image/*" onChange={(event) => void upload(event.target.files?.[0])} />
      <article className="pf-card">
        <button type="button" className="pf-portrait" onClick={() => pickPhoto(0)} disabled={uploadingPhotoSlot !== null} aria-label={photos[0] ? "Change main photo" : "Add main photo"}>
          <svg className="pf-ring" viewBox="0 0 160 160" aria-hidden="true">
            <path d={blobPath(`${seed}:outer`, 80, 74, 0.1)} className="pf-ring-outer" />
            <path d={blobPath(`${seed}:inner`, 80, 66, 0.12, 6)} className="pf-ring-inner" />
          </svg>
          {photos[0] ? <img src={photos[0]} alt="" /> : <span className="pf-initial">{firstName.slice(0, 1)}</span>}
          {uploadingPhotoSlot === 0 ? <span className="pf-busy"><span className="state-view-spinner" /></span> : <span className="pf-portrait-edit"><Camera aria-hidden="true" /></span>}
        </button>
        <h1>{firstName}{form.age ? `, ${form.age}` : ""}</h1>
        {form.city ? <p className="pf-place"><MapPin aria-hidden="true" />{form.city}</p> : null}
        {intro === undefined ? (
          <p className="pf-intro is-loading" aria-live="polite">Omi is writing your intro…</p>
        ) : intro.ready ? (
          <>
            <blockquote className="pf-intro">“{intro.intro}”</blockquote>
            <p className="pf-intro-note">Written by Omi from your chats</p>
          </>
        ) : (
          <p className="pf-intro is-empty">Omi is still getting to know you. Keep chatting, and your intro writes itself.</p>
        )}
        {intro?.chips.length ? <ul className="pf-chips">{intro.chips.map((chip) => <li key={chip}>{chip}</li>)}</ul> : null}
        <div className="pf-photos">
          {photoSlots.map((slot) => (
            <div className={`pf-photo ${photos[slot] ? "has-photo" : ""}`} key={slot}>
              <button type="button" onClick={() => pickPhoto(slot)} disabled={uploadingPhotoSlot !== null} aria-label={photos[slot] ? `Replace photo ${slot + 1}` : `Add photo ${slot + 1}`}>
                {photos[slot] ? <img src={photos[slot]} alt="" /> : <Plus aria-hidden="true" />}
                {uploadingPhotoSlot === slot ? <span className="pf-busy"><span className="state-view-spinner" /></span> : null}
              </button>
              {photos[slot] ? <button type="button" className="pf-photo-remove" onClick={() => void removePhoto(slot)} disabled={uploadingPhotoSlot !== null} aria-label={`Remove photo ${slot + 1}`}><X aria-hidden="true" /></button> : null}
            </div>
          ))}
        </div>
        {photoStatus ? <Notice tone={isPhotoStatusError ? "error" : "success"}>{photoStatus}</Notice> : null}
        <div className="pf-card-actions">
          {onVibe && intro?.ready ? <button type="button" className="secondary-button" onClick={onVibe}>Not quite me</button> : null}
          <button type="button" className="secondary-button" onClick={() => { setEditing(!editing); setStatus(""); }}>{editing ? "Close" : "Edit details"}</button>
        </div>
      </article>

      {editing ? (
        <form className="pf-panel pf-edit" onSubmit={save}>
          <label>Name<input value={form.display_name || ""} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></label>
          <label>Age<input type="number" min="18" max="100" value={form.age || ""} onChange={(e) => setForm({ ...form, age: Number(e.target.value) })} /></label>
          <label>Location<input value={form.city || ""} onChange={(e) => setForm({ ...form, city: e.target.value })} /></label>
          <label title="Optional. Helps Omi address you correctly in Hindi.">Gender (optional)<select value={form.gender || "prefer_not_to_say"} onChange={(e) => setForm({ ...form, gender: e.target.value })}><option value="prefer_not_to_say">Prefer not to say</option><option value="woman">Woman</option><option value="man">Man</option><option value="non_binary">Non-binary</option></select></label>
          <label>Mobile (optional)<input type="tel" value={form.phone || ""} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
          <button type="submit">Save</button>
        </form>
      ) : null}
      {status ? <Notice tone={status === "Profile saved." ? "success" : status === "Saving profile…" ? "info" : "error"}>{status}</Notice> : null}

      <p className="pf-kicker pf-private">Account</p>
      <div className="pf-panel pf-rows">
        <div className="pf-row"><span>Email</span><span className="pf-muted">{data.user?.email || "Signed in"}</span></div>
        <div className="pf-row"><span>Gender</span><span className="pf-muted">{genderLabel}</span></div>
        {form.phone ? <div className="pf-row"><span>Mobile</span><span className="pf-muted">{form.phone}</span></div> : null}
        <button type="button" className="pf-row is-action" onClick={() => setPendingDataRequest("export")} disabled={sendingRequest}><span>Export my data</span><ChevronRight aria-hidden="true" /></button>
        <button type="button" className="pf-row is-action" onClick={() => void signOut()}><span>Sign out</span><ChevronRight aria-hidden="true" /></button>
        <button type="button" className="pf-row is-action is-danger" onClick={() => setPendingDataRequest("deletion")} disabled={sendingRequest}><span>Delete account and data</span><ChevronRight aria-hidden="true" /></button>
      </div>
      {requestStatus ? <Notice tone={requestStatus === "Request sent." || requestStatus === "Account data deleted." ? "success" : "error"}>{requestStatus}</Notice> : null}
      {dataRequests.length ? <p className="pf-requests">Recent requests: {dataRequests.slice(0, 3).map((request) => `${humanizeLabel(request.request_type || "request")} (${request.status || "open"})`).join(", ")}</p> : null}
      {pendingDataRequest ? <div className="confirm-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !sendingRequest) setPendingDataRequest(null); }}><section className="confirm-dialog data-request-dialog" role="dialog" aria-modal="true" aria-labelledby="data-request-title" aria-describedby="data-request-copy"><div className="confirm-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d={pendingDataRequest === "deletion" ? "M9 3h6l1 2h4v2H4V5h4l1-2Z M6 9h12l-.8 11H6.8L6 9Zm4 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z" : "M12 3v10m0 0 4-4m-4 4-4-4M5 17h14v3H5v-3Z"} /></svg></div><div className="confirm-copy"><p className="eyebrow">{pendingDataRequest === "deletion" ? "Delete Data" : "Export Data"}</p><h2 id="data-request-title">{pendingDataRequest === "deletion" ? "Permanently delete account data?" : "Request a copy of your data?"}</h2><p id="data-request-copy">{pendingDataRequest === "deletion" ? "This will delete your profile, chats, memories, learned signals, usage logs, feedback, requests, and photos now. This cannot be undone." : "We will record this request and prepare an export path for your account and personal data."}</p><p className="confirm-session">{data?.user?.email || "Signed-in account"}</p></div><div className="confirm-actions"><button className="secondary-button" type="button" onClick={() => setPendingDataRequest(null)} disabled={sendingRequest}>Cancel</button><button className={pendingDataRequest === "deletion" ? "danger-button" : "secondary-button"} type="button" onClick={() => void submitDataRequest(pendingDataRequest)} disabled={sendingRequest}>{sendingRequest ? (pendingDataRequest === "deletion" ? "Deleting..." : "Sending...") : pendingDataRequest === "deletion" ? "Delete account data" : "Send export request"}</button></div></section></div> : null}
    </section>
  );
}

function humanizeLabel(value?: string) {
  return (value || "").replaceAll("_", " ");
}
