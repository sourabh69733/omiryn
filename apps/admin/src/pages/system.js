import { empty, esc, facts, num, panel, pill, shortId, skeleton, stat, table, timeTag, titleize } from "../ui.js";

export async function render({ root, api, isCurrent }) {
  root.innerHTML = skeleton(6);
  const data = await api("/api/admin/system");
  if (!isCurrent()) return;
  root.innerHTML = view(data);
}

function onOff(value) {
  return value ? pill("ok", "On") : pill("off", "Off");
}

function userLink(userId) {
  return userId ? `<a class="mono" href="/users/${encodeURIComponent(userId)}" data-link>${esc(shortId(userId))}</a>` : "-";
}

export function view(data) {
  const config = data.config || {};
  const jobs = data.jobs || {};
  const memory = data.memory || {};
  const channels = data.channels || {};
  const totals = (jobs.by_kind || []).reduce(
    (sum, row) => ({ pending: sum.pending + row.pending, running: sum.running + row.running, failed: sum.failed + row.failed, done: sum.done + row.done }),
    { pending: 0, running: 0, failed: 0, done: 0 },
  );
  const oldest = Math.max(0, ...(jobs.by_kind || []).map((row) => row.oldest_pending_minutes || 0));

  return `
    <div class="stats">
      ${stat({ label: "Jobs waiting", value: num(totals.pending), sub: oldest ? `oldest ${num(oldest)} min` : "queue is empty", tone: oldest >= 30 ? "warn" : "" })}
      ${stat({ label: "Jobs running", value: num(totals.running), sub: `${num(totals.done)} done in total` })}
      ${stat({ label: "Jobs failed", value: num(totals.failed), sub: "gave up after retries", tone: totals.failed ? "bad" : "" })}
      ${stat({ label: "Memory batches failing", value: num(memory.batch_failures?.length), tone: memory.batch_failures?.length ? "bad" : "" })}
      ${stat({ label: "Online now", value: num(channels.online_now), sub: "seen in the last 5 min" })}
    </div>
    <div class="grid two">
      ${panel({
        title: "Runtime",
        kicker: "This server",
        body: facts([
          ["Environment", `<code>${esc(config.environment || "-")}</code>`],
          ["Prompt version", `<code>${esc(config.prompt_version || "-")}</code>`],
          ["Omi messages first", onOff(config.proactive_messaging)],
          ["Identity check", onOff(config.identity_check)],
          ["Telegram", config.telegram_configured ? pill("ok", "Configured") : pill("off", "Not set")],
          ["WhatsApp", config.whatsapp_configured ? pill("ok", "Configured") : pill("off", "Not set")],
        ]),
      })}
      ${panel({
        title: "Memory pipeline",
        kicker: "Saving what people share",
        body: facts([
          ["Memories kept", num(memory.active)],
          ["Added last 24 h", num(memory.added_24h)],
          ["Added this week", num(memory.added_7d)],
          ["Batches in progress", num(memory.leases_held)],
          ["Chat uploads", `${num(memory.uploads)} total · ${num(memory.uploads_7d)} this week`],
          ["Upload digests", num(memory.upload_digests)],
        ]),
      })}
    </div>
    <div class="grid two">
      ${panel({
        title: "Job queue",
        kicker: "By kind",
        body: table(
          [
            { label: "Kind", cell: (r) => esc(titleize(r.kind)) },
            { label: "Waiting", align: "right", cell: (r) => `${num(r.pending)}${r.oldest_pending_minutes ? `<small>${num(r.oldest_pending_minutes)} min</small>` : ""}` },
            { label: "Running", align: "right", cell: (r) => num(r.running) },
            { label: "Done", align: "right", cell: (r) => num(r.done) },
            { label: "Failed", align: "right", cell: (r) => (r.failed ? `<span class="tone-bad">${num(r.failed)}</span>` : "0") },
          ],
          jobs.by_kind,
          { emptyText: "No jobs yet." },
        ),
      })}
      ${panel({
        title: "Channels",
        kicker: "Telegram and WhatsApp",
        body: `${table(
          [
            { label: "Channel", cell: (r) => pill(r.channel) },
            { label: "Linked users", align: "right", cell: (r) => num(r.count) },
            { label: "Last link", cell: (r) => timeTag(r.last_linked_at) },
          ],
          channels.links,
          { emptyText: "Nobody has linked Telegram or WhatsApp yet." },
        )}
        ${facts([
          ["Link codes waiting", num(channels.pending_link_codes)],
          ["Chats this week", (channels.chats_7d || []).map((row) => `${esc(titleize(row.channel))} ${num(row.count)}`).join(" · ") || "0"],
        ])}`,
      })}
    </div>
    ${problemPanel("Jobs with errors", jobs.problems, (row) => `${esc(titleize(row.kind))} · ${num(row.attempts)} tries`)}
    ${problemPanel("Memory batches failing", memory.batch_failures, (row) => `${num(row.attempts)} tries · <span class="mono">${esc(shortId(row.batch_key))}</span>`)}
    <div class="grid two">
      ${panel({
        title: "Eval runs",
        kicker: "Latest",
        body: table(
          [
            { label: "Suite", cell: (r) => `${esc(r.suite)}<small>${esc(r.model || "")}</small>` },
            { label: "Result", cell: (r) => (r.failed ? pill("failed", `${r.failed} failed`) : pill("passed", `${r.passed}/${r.total} passed`)) },
            { label: "When", cell: (r) => timeTag(r.created_at) },
          ],
          data.eval_runs,
          { emptyText: "No eval runs recorded on this database." },
        ),
      })}
      ${panel({
        title: "Admin access log",
        kicker: "Who looked at what",
        body: table(
          [
            { label: "Action", cell: (r) => esc(titleize(String(r.action || "").replace(/^admin\./, ""))) },
            { label: "By", cell: (r) => `<span class="mono">${esc(shortId(r.actor_id))}</span>` },
            { label: "User", cell: (r) => userLink(r.target_user_id) },
            { label: "When", cell: (r) => timeTag(r.created_at) },
          ],
          data.audit,
          { emptyText: "Nothing recorded." },
        ),
      })}
    </div>`;
}

function problemPanel(title, rows, head) {
  return panel({
    title,
    kicker: "Errors",
    body: rows?.length
      ? `<ul class="error-list">${rows
          .map((row) => `<li><div><strong>${head(row)}</strong> ${userLink(row.user_id)}</div><code class="error-text">${esc(row.last_error || "No error text")}</code>${timeTag(row.updated_at)}</li>`)
          .join("")}</ul>`
      : empty("None. All clear."),
  });
}
