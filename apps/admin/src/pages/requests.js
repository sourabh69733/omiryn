import { empty, esc, num, panel, pill, shortId, skeleton, stat, table, timeTag, titleize } from "../ui.js";

export async function render({ root, api, isCurrent }) {
  root.innerHTML = skeleton(6);
  const data = await api("/api/admin/requests?limit=100");
  if (!isCurrent()) return;
  root.innerHTML = view(data);
}

function userLink(userId) {
  return userId ? `<a class="mono" href="/users/${encodeURIComponent(userId)}" data-link>${esc(shortId(userId))}</a>` : "";
}

export function metadataSummary(metadata) {
  if (!metadata || typeof metadata !== "object" || !Object.keys(metadata).length) return "-";
  return Object.entries(metadata)
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${value !== null && typeof value === "object" ? JSON.stringify(value).slice(0, 80) : String(value ?? "-").slice(0, 80)}`)
    .join(" · ");
}

function requestCard(item) {
  const metadata = item.metadata || {};
  const isInvite = metadata.request_type === "community_invite";
  const type = isInvite ? `${titleize(metadata.channel || "community")} invite` : titleize(item.category || "feedback");
  return `<article class="card">
    <header>${pill(isInvite ? "invite" : "feedback", type)} ${item.status ? pill(item.status) : ""}${timeTag(item.created_at)}</header>
    <p>${esc(item.message_preview || item.message || "No message.")}</p>
    <footer>${esc(item.email || "No email")} ${userLink(item.user_id)} · ${item.allow_contact ? "may contact" : "no contact"}</footer>
  </article>`;
}

export function view(data) {
  const s = data.summary || {};
  const feedback = [...(data.feedback_messages || []), ...(data.community_invites || [])].sort(
    (a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0),
  );
  return `
    <div class="stats">
      ${stat({ label: "Feedback", value: num(s.feedback_message_count) })}
      ${stat({ label: "Invite requests", value: num(s.community_invite_count) })}
      ${stat({ label: "Data requests", value: num(s.data_request_count), sub: `${num(s.open_data_request_count)} open`, tone: s.open_data_request_count ? "warn" : "" })}
      ${stat({ label: "App errors", value: num(s.client_error_count), tone: s.client_error_count ? "warn" : "" })}
      ${stat({ label: "Public contacts", value: num(s.public_lead_count) })}
    </div>
    <div class="grid two">
      ${panel({ title: "Feedback and invites", kicker: "From signed-in users", body: feedback.length ? `<div class="cards">${feedback.map(requestCard).join("")}</div>` : empty("No feedback or invite requests yet.") })}
      ${panel({
        title: "Export and deletion",
        kicker: "Data requests",
        body: table(
          [
            { label: "Type", cell: (r) => pill(r.request_type) },
            { label: "Who", cell: (r) => `${esc(r.email || "-")} ${userLink(r.user_id)}` },
            { label: "Status", cell: (r) => pill(r.status) },
            { label: "When", cell: (r) => timeTag(r.created_at) },
          ],
          data.data_requests,
          { emptyText: "No export or deletion requests." },
        ),
      })}
    </div>
    ${panel({
      title: "App errors",
      kicker: "Reported by the web app",
      body: table(
        [
          { label: "When", cell: (r) => timeTag(r.created_at) },
          { label: "User", cell: (r) => userLink(r.user_id) || "-" },
          { label: "Page", cell: (r) => esc(r.page || "-") },
          { label: "Details", cell: (r) => `<span class="meta-line">${esc(metadataSummary(r.metadata))}</span>` },
        ],
        data.client_errors,
        { emptyText: "No app errors. 🎉" },
      ),
    })}
    <div class="grid two">
      ${panel({
        title: "Public contacts",
        kicker: "Landing page form",
        body: data.public_leads?.length
          ? `<div class="cards">${data.public_leads
              .slice(0, 20)
              .map(
                (row) => `<article class="card"><header>${pill(row.intent || "lead")}<strong>${esc(row.name || row.contact || "Anonymous")}</strong>${timeTag(row.created_at)}</header>
                <p>${esc(row.message_preview || row.message || "No message.")}</p><footer>${esc(row.contact || "-")} · ${esc(titleize(row.channel || "email"))}</footer></article>`,
              )
              .join("")}</div>`
          : empty("No public contact submissions yet."),
      })}
      ${panel({
        title: "Landing page visits",
        kicker: "Public events",
        body: table(
          [
            { label: "Event", cell: (r) => esc(titleize(r.event_name)) },
            { label: "Page", cell: (r) => `${esc(r.path || "/")}${r.referrer ? `<small>${esc(r.referrer)}</small>` : ""}` },
            { label: "When", cell: (r) => timeTag(r.created_at) },
          ],
          (data.public_events || []).slice(0, 30),
          { emptyText: "No visits recorded." },
        ),
      })}
    </div>
    ${panel({
      title: "App activity",
      kicker: "Latest signed-in events",
      body: table(
        [
          { label: "Event", cell: (r) => esc(titleize(r.event_name)) },
          { label: "User", cell: (r) => userLink(r.user_id) || "-" },
          { label: "Page", cell: (r) => esc(r.page || "-") },
          { label: "Details", cell: (r) => `<span class="meta-line">${esc(metadataSummary(r.metadata))}</span>`, className: "hide-narrow" },
          { label: "When", cell: (r) => timeTag(r.created_at) },
        ],
        (data.app_events || []).slice(0, 40),
        { emptyText: "No app events yet." },
      ),
    })}`;
}
