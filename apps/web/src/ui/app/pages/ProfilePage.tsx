import { type FormEvent, useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { apiErrorMessage, apiFetch, signOut } from "../../../lib/api";
import { trackAppEvent } from "../../../lib/appLogger";
import type { DataRequest, Profile, ProfileResponse } from "../types";

export function ProfilePage() {
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [form, setForm] = useState<Profile>({});
  const [status, setStatus] = useState("Loading profile…");
  const [dataRequests, setDataRequests] = useState<DataRequest[]>([]);
  const [requestStatus, setRequestStatus] = useState("");
  const [photoStatus, setPhotoStatus] = useState("");
  const [sendingRequest, setSendingRequest] = useState(false);
  const [pendingDataRequest, setPendingDataRequest] = useState<"export" | "deletion" | null>(null);
  const photoInput = useRef<HTMLInputElement | null>(null);
  const [photoSlot, setPhotoSlot] = useState(0);
  const [uploadingPhotoSlot, setUploadingPhotoSlot] = useState<number | null>(null);
  async function load() { const response = await apiFetch("/api/me/profile"); if (!response.ok) throw new Error(await apiErrorMessage(response, "Could not load profile.")); const next = await response.json() as ProfileResponse; setData(next); setForm(next.profile || {}); setStatus(""); const requestResponse = await apiFetch("/api/me/data-requests"); if (requestResponse.ok) setDataRequests(((await requestResponse.json()).requests || []) as DataRequest[]); }
  useEffect(() => { load().catch((caught) => setStatus(caught.message)); }, []);
  async function save(event: FormEvent) { event.preventDefault(); setStatus("Saving profile…"); const response = await apiFetch("/api/me/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name: form.display_name || null, age: Number(form.age), gender: form.gender, interested_in: form.interested_in, city: form.city || null, phone: form.phone || null }) }); if (!response.ok) { setStatus(await apiErrorMessage(response, "Could not save profile.")); return; } trackAppEvent("profile_saved", {}, { page: "profile" }); setStatus("Profile saved."); await load(); }
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
  const extraPhotoSlots = Array.from({ length: Math.max(0, maxPhotoCount - 1) }, (_, index) => index + 1);
  const isPhotoStatusError = /could not|limit|quota|up to|try again/i.test(photoStatus);
  const renderPhotoSlot = (slot: number, isMain = false) => <div className={`profile-photo-slot ${isMain ? "is-main" : ""}`} key={slot}><button className={`${isMain ? "profile-main-photo" : "profile-thumb"} ${photos[slot] ? "has-photo" : ""} ${uploadingPhotoSlot === slot ? "is-uploading" : ""}`} type="button" disabled={uploadingPhotoSlot !== null} onClick={() => { setPhotoSlot(slot); setPhotoStatus(""); photoInput.current?.click(); }} aria-label={photos[slot] ? `Replace profile photo ${slot + 1}` : `Upload profile photo ${slot + 1}`}>{photos[slot] ? <img className="profile-gallery-img" src={photos[slot]} alt={isMain ? "Profile" : `Profile ${slot + 1}`} /> : <span className="profile-photo-empty">{isMain ? form.display_name?.slice(0, 1) || "O" : "+"}</span>}{uploadingPhotoSlot === slot ? <span className="profile-upload-overlay"><span className="profile-upload-spinner" />Working...</span> : null}{isMain ? <span className="profile-main-badge">Main photo</span> : null}</button>{photos[slot] ? <button className="profile-remove-photo" type="button" disabled={uploadingPhotoSlot !== null} onClick={() => void removePhoto(slot)} aria-label={`Remove profile photo ${slot + 1}`} title="Remove photo"><Trash2 aria-hidden="true" size={16} strokeWidth={2.4} /></button> : null}</div>;
  return <section className="screen profile-screen"><div className="usage-hero"><div className="screen-copy compact"><p className="eyebrow">Profile</p><h1>Your profile.</h1><p>Keep photos, basics, and match direction clean before conversation takes over.</p></div></div><div className="profile-layout">
    <section className="profile-panel profile-photo-panel"><div className="panel-heading"><div><p className="eyebrow">Photos</p><h2>Profile gallery</h2></div><input ref={photoInput} className="profile-photo-input" type="file" accept="image/*" onChange={(event) => void upload(event.target.files?.[0])} /></div>{photoStatus ? <p className={`profile-photo-status ${isPhotoStatusError ? "is-error" : ""}`} role="status">{photoStatus}</p> : null}<div className={`profile-photo-gallery ${maxPhotoCount === 1 ? "single-photo" : ""}`}>{renderPhotoSlot(0, true)}{extraPhotoSlots.length ? <div className="profile-thumb-stack">{extraPhotoSlots.map((slot) => renderPhotoSlot(slot))}</div> : null}</div><div className="profile-photo-copy"><strong>Show the real you.</strong><span>{maxPhotoCount === 1 ? "Upload 1 clear profile photo. Use Remove first if you want a fresh upload and your quota is over." : `Upload up to ${maxPhotoCount} clear photos. You can remove any photo and add another later.`}</span></div></section>
    <section className="profile-panel profile-info-panel"><div className="panel-heading"><div><p className="eyebrow">Account</p><h2>Basic info</h2></div></div><form className="profile-form" onSubmit={save}><p className="privacy-note">Profile details help personalize chat and future matching. Keep them accurate, and only add optional contact details you are comfortable storing.</p><label>Name<input value={form.display_name || ""} onChange={(e) => setForm({...form, display_name:e.target.value})} /></label><label>Age<input type="number" min="18" max="100" value={form.age || ""} onChange={(e) => setForm({...form, age:Number(e.target.value)})} /></label><label>Email<input value={data?.user?.email || ""} readOnly /></label><label>Gender<select value={form.gender || "prefer_not_to_say"} onChange={(e) => setForm({...form, gender:e.target.value})}><option value="man">Man</option><option value="woman">Woman</option><option value="non_binary">Non-binary</option><option value="prefer_not_to_say">Prefer not to say</option></select></label><label>Interested in<select value={form.interested_in || "everyone"} onChange={(e) => setForm({...form, interested_in:e.target.value})}><option value="women">Women</option><option value="men">Men</option><option value="everyone">Everyone</option></select></label><label className="wide-field">Location<input value={form.city || ""} onChange={(e) => setForm({...form, city:e.target.value})} /></label><label className="wide-field">Mobile (optional)<input type="tel" value={form.phone || ""} onChange={(e) => setForm({...form, phone:e.target.value})} /></label><button type="submit">Save profile</button><p className="quiet-note">{status}</p></form><section className="data-request-form"><div><strong>Account data</strong><span>Export your data or permanently delete account data. Privacy, safety, and support questions are handled from Contact.</span></div><div className="data-request-actions"><button type="button" className="secondary-button" onClick={() => setPendingDataRequest("export")} disabled={sendingRequest}>Export data</button><button type="button" className="danger-light-button" onClick={() => setPendingDataRequest("deletion")} disabled={sendingRequest}>Delete data</button></div>{requestStatus ? <p className="quiet-note">{requestStatus}</p> : null}{dataRequests.length ? <div className="data-request-list">{dataRequests.slice(0, 3).map((request) => <article key={request.id}><strong>{humanizeLabel(request.request_type || "request")}</strong><span>{request.status || "open"} · {request.created_at ? new Date(request.created_at).toLocaleDateString() : "sent"}</span></article>)}</div> : null}</section></section>
  </div>{pendingDataRequest ? <div className="confirm-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !sendingRequest) setPendingDataRequest(null); }}><section className="confirm-dialog data-request-dialog" role="dialog" aria-modal="true" aria-labelledby="data-request-title" aria-describedby="data-request-copy"><div className="confirm-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d={pendingDataRequest === "deletion" ? "M9 3h6l1 2h4v2H4V5h4l1-2Z M6 9h12l-.8 11H6.8L6 9Zm4 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z" : "M12 3v10m0 0 4-4m-4 4-4-4M5 17h14v3H5v-3Z"} /></svg></div><div className="confirm-copy"><p className="eyebrow">{pendingDataRequest === "deletion" ? "Delete Data" : "Export Data"}</p><h2 id="data-request-title">{pendingDataRequest === "deletion" ? "Permanently delete account data?" : "Request a copy of your data?"}</h2><p id="data-request-copy">{pendingDataRequest === "deletion" ? "This will delete your profile, chats, memories, learned signals, usage logs, feedback, requests, and photos now. This cannot be undone." : "We will record this request and prepare an export path for your account and personal data."}</p><p className="confirm-session">{data?.user?.email || "Signed-in account"}</p></div><div className="confirm-actions"><button className="secondary-button" type="button" onClick={() => setPendingDataRequest(null)} disabled={sendingRequest}>Cancel</button><button className={pendingDataRequest === "deletion" ? "danger-button" : "secondary-button"} type="button" onClick={() => void submitDataRequest(pendingDataRequest)} disabled={sendingRequest}>{sendingRequest ? (pendingDataRequest === "deletion" ? "Deleting..." : "Sending...") : pendingDataRequest === "deletion" ? "Delete account data" : "Send export request"}</button></div></section></div> : null}</section>;
}


function humanizeLabel(value?: string) {
  return (value || "").replaceAll("_", " ");
}
