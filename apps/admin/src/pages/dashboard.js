import { barChart, delta, empty, esc, facts, initials, ms, num, panel, pct, personName, skeleton, stat, timeTag, titleize, usd } from "../ui.js";

export async function render({ root, api, isCurrent }) {
  root.innerHTML = skeleton(6);
  const data = await api("/api/admin/dashboard?days=14");
  if (!isCurrent()) return;
  root.innerHTML = view(data);
}

export function view(data) {
  const k = data.kpis || {};
  const omi = data.omi || {};
  const health = data.health || {};
  const replies7 = k.replies_7d || 0;
  const failed7 = k.failed_7d || 0;

  const stats = [
    stat({ label: "Active today", value: num(k.active_today), sub: `${num(k.messages_7d)} messages sent this week`, href: "/users" }),
    stat({ label: "Active this week", value: num(k.active_7d), sub: delta(k.active_7d, k.active_prev_7d), href: "/users" }),
    stat({ label: "Returning", value: num(k.returning_7d), sub: `of ${num(k.active_7d)} active came back from before` }),
    stat({ label: "New users", value: num(k.new_users_7d), sub: `${num(k.new_users_today)} today · ${num(k.users_total)} total` }),
    stat({ label: "Omi replies", value: num(replies7), sub: delta(replies7, k.replies_prev_7d), href: "/usage" }),
    stat({
      label: "Failed replies",
      value: num(failed7),
      sub: `${pct(failed7, replies7 + failed7)} of this week · ${num(k.failed_today)} today`,
      tone: k.failed_today ? "bad" : failed7 ? "warn" : "",
      href: "/usage",
    }),
    stat({ label: "Spend this week", value: usd(k.cost_7d), sub: `${usd(k.cost_today)} today · ${usd(k.cost_30d)} in 30 days`, href: "/usage" }),
  ].join("");

  return `
    <div class="stats">${stats}</div>
    <div class="grid two-one">
      ${panel({
        title: "Needs attention",
        kicker: "Right now",
        body: attentionList(data.attention || []),
      })}
      ${panel({
        title: "Omi",
        kicker: "Reply health",
        body: facts([
          ["Prompt", `<code>${esc(omi.prompt_version || "-")}</code>`],
          ["Reply model", `<span class="wrap">${esc(omi.reply_model || "-")}</span>`],
          ["Speed (7 days)", omi.latency_samples ? `${ms(omi.latency_p50_ms)} typical · ${ms(omi.latency_p95_ms)} slowest 5%` : '<span class="muted">no replies</span>'],
          ["Last reply", timeTag(omi.last_reply_at)],
          ["Ratings (30 days)", omi.feedback_30d?.total ? `${num(omi.feedback_30d.good)} good · ${num(omi.feedback_30d.bad)} poor` : '<span class="muted">none yet</span>'],
          ["Last failure", omi.last_error_at ? timeTag(omi.last_error_at) : '<span class="muted">none</span>'],
        ]),
      })}
    </div>
    <div class="grid three">
      ${panel({ title: "Active users", kicker: "Per day", body: barChart(data.daily, [{ key: "active_users", label: "Active" }]) })}
      ${panel({
        title: "Omi replies",
        kicker: "Per day",
        body: barChart(data.daily, [
          { key: "replies", label: "Replies" },
          { key: "failed_replies", label: "Failed", tone: "bad" },
        ]),
      })}
      ${panel({ title: "Spend", kicker: "Per day", body: barChart(data.daily, [{ key: "cost_usd", label: "Cost", tone: "alt" }], { format: usd }) })}
    </div>
    <div class="grid three">
      ${panel({
        title: "Memory & background",
        kicker: "Pipeline",
        actions: '<a class="text-link" href="/system" data-link>System →</a>',
        body: facts([
          ["Memories kept", num(health.memories_active)],
          ["Added this week", num(health.memories_added_7d)],
          ["Users with memories", num(health.users_with_memories)],
          ["Jobs waiting", `${num(health.jobs_pending)}${health.oldest_pending_job_minutes ? ` · oldest ${num(health.oldest_pending_job_minutes)} min` : ""}`],
          ["Jobs failed", health.jobs_failed ? `<span class="tone-bad">${num(health.jobs_failed)}</span>` : "0"],
          ["Memory batches failing", health.batch_failures ? `<span class="tone-bad">${num(health.batch_failures)}</span>` : "0"],
        ]),
      })}
      ${panel({
        title: "Channels",
        kicker: "Where people talk",
        body: channels(health),
      })}
      ${panel({
        title: "Recently active",
        kicker: "Users",
        actions: '<a class="text-link" href="/users" data-link>All users →</a>',
        body: recentPeople(data.recent_users || []),
      })}
    </div>
    <p class="footnote">Days are UTC. Active means the person opened the app, sent a message, or got a reply.</p>`;
}

function attentionList(items) {
  if (!items.length) return '<div class="all-clear"><span aria-hidden="true">✓</span> All clear. No failures, stuck jobs or open requests.</div>';
  return `<ul class="attention">${items
    .map(
      (item) => `<li class="${esc(item.level)}">
        <a href="${esc(item.route)}" data-link>
          <span class="attention-count">${item.count == null ? "!" : esc(num(item.count))}</span>
          <span class="attention-text"><strong>${esc(item.title)}</strong><small>${esc(item.detail)}</small></span>
          <span class="chev" aria-hidden="true">›</span>
        </a></li>`,
    )
    .join("")}</ul>`;
}

function channels(health) {
  const chats = health.chats_by_channel_7d || {};
  const links = health.linked_channels || {};
  const names = [...new Set(["web", "telegram", "whatsapp", ...Object.keys(chats), ...Object.keys(links)])];
  return facts(
    names.map((name) => [
      titleize(name),
      `${plural(chats[name] || 0, "chat")} this week${name === "web" ? "" : ` · ${num(links[name] || 0)} linked`}`,
    ]),
  );
}

function plural(count, word) {
  return `${num(count)} ${word}${Number(count) === 1 ? "" : "s"}`;
}

function recentPeople(people) {
  if (!people.length) return empty("Nobody yet.");
  return `<ul class="people-mini">${people
    .map(
      (person) => `<li><a href="/users/${encodeURIComponent(person.user_id)}" data-link>
        <span class="avatar">${esc(initials(personName(person)))}</span>
        <span class="person-name">${esc(personName(person))}</span>
        ${timeTag(person.last_active_at)}
      </a></li>`,
    )
    .join("")}</ul>`;
}
