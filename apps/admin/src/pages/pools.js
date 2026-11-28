// Pools page: list, one open pool, and the operator actions (create, pick, propose, ask, send again, introduce, set plan, status).
import { pickProgressLabel, planChanges, renderPickResult, renderPoolList, renderPoolView } from "../pools.js";
import { esc, skeleton } from "../ui.js";

const state = { pools: [], selectedPoolId: null, view: null, pick: null };

export async function render({ root, api, setStatus, isCurrent }) {
  root.innerHTML = skeleton(3);
  const data = await api("/api/admin/pools");
  if (!isCurrent()) return;
  state.pools = data.pools || [];
  if (!state.pools.some((pool) => pool.id === state.selectedPoolId)) state.selectedPoolId = state.pools[0]?.id || null;
  root.innerHTML = `
    <section class="panel">
      <header class="panel-head">
        <div><p class="kicker">Match pools</p><h2>Pools</h2></div>
        <form class="pool-create" id="pool-create">
          <label>Name <input name="name" maxlength="80" placeholder="Sunrise Residency" required></label>
          <label>Match day
            <select name="match_weekday">${["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
              .map((day, index) => `<option value="${index}" ${index === 6 ? "selected" : ""}>${day}</option>`)
              .join("")}</select>
          </label>
          <button type="submit">Create pool</button>
        </form>
      </header>
      <div class="panel-body"><div class="table-wrap"><table>
        <thead><tr><th>Name</th><th>Join code</th><th>Match day</th><th>Created</th></tr></thead>
        <tbody id="pool-list">${renderPoolList(state.pools, state.selectedPoolId)}</tbody>
      </table></div></div>
    </section>
    <section class="panel pool-detail" id="pool-detail" hidden></section>`;
  bind(root, api, setStatus);
  if (state.selectedPoolId) await openPool(root, api, setStatus, state.selectedPoolId);
}

async function openPool(root, api, setStatus, poolId) {
  if (state.selectedPoolId !== poolId) state.pick = null;
  state.selectedPoolId = poolId;
  root.querySelector("#pool-list").innerHTML = renderPoolList(state.pools, poolId);
  const detail = root.querySelector("#pool-detail");
  detail.hidden = false;
  detail.innerHTML = skeleton(2);
  try {
    state.view = await api(`/api/admin/pools/${encodeURIComponent(poolId)}`);
    detail.innerHTML = renderPoolView(state.view);
    detail.querySelector("#pool-pick-result").innerHTML = renderPickResult(state.pick, state.view);
  } catch (error) {
    detail.innerHTML = `<div class="empty bad">${esc(error.message)}</div>`;
    setStatus(error.message, "bad");
  }
}

// The pick is a background job on the server: start it, then ask how it stands until it is done.
// A big pool takes minutes; the server keeps what it has judged, so a reload loses nothing.
const PICK_POLL_MS = 3000;

async function runPick(api, poolId, onProgress) {
  const address = `/api/admin/pools/${encodeURIComponent(poolId)}/pick`;
  let run = (await api(address, { method: "POST" })).run;
  while (run && ["queued", "running"].includes(run.status)) {
    onProgress(run);
    await new Promise((resolve) => setTimeout(resolve, PICK_POLL_MS));
    run = (await api(address)).run;
  }
  if (!run || run.status !== "done") throw new Error(`The pick did not finish${run?.error ? ` (${run.error})` : ""}. Pairs judged so far are kept; start it again.`);
  return run.proposal;
}

function bind(root, api, setStatus) {
  const reopen = () => openPool(root, api, setStatus, state.selectedPoolId);

  root.querySelector("#pool-create").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    try {
      const pool = await api("/api/admin/pools", {
        method: "POST",
        body: JSON.stringify({ name: String(form.get("name") || "").trim(), match_weekday: Number(form.get("match_weekday")) }),
      });
      state.selectedPoolId = pool.id;
      await render({ root, api, setStatus, isCurrent: () => true });
      setStatus("Pool created. Share the join code.");
    } catch (error) {
      setStatus(error.message, "bad");
    }
  });

  const list = root.querySelector("#pool-list");
  list.addEventListener("click", (event) => {
    const row = event.target.closest("[data-pool-id]");
    if (row) void openPool(root, api, setStatus, row.dataset.poolId);
  });
  list.addEventListener("keydown", (event) => {
    const row = event.target.closest("[data-pool-id]");
    if (row && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      void openPool(root, api, setStatus, row.dataset.poolId);
    }
  });

  const detail = root.querySelector("#pool-detail");
  detail.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-propose], [data-ask], [data-pick], [data-resend]");
    if (!button || !state.selectedPoolId) return;
    const label = button.textContent;
    button.disabled = true;
    try {
      if (button.dataset.propose) {
        button.textContent = "Checking…";
        const [userA, userB] = button.dataset.propose.split("|");
        await api(`/api/admin/pools/${encodeURIComponent(state.selectedPoolId)}/pairs`, { method: "POST", body: JSON.stringify({ user_a: userA, user_b: userB }) });
        setStatus("Pair proposed. Read the check, then ask or introduce them.");
      } else if (button.dataset.ask) {
        if (!window.confirm("Omi will message both people in their chats and ask if they want to meet. Send?")) {
          button.disabled = false;
          return;
        }
        button.textContent = "Asking…";
        await api(`/api/admin/pairs/${encodeURIComponent(button.dataset.ask)}/ask`, { method: "POST" });
        setStatus("Asked. Each person answers in their own chat.");
      } else if (button.dataset.resend) {
        button.textContent = "Sending…";
        const result = await api(`/api/admin/pairs/${encodeURIComponent(button.dataset.resend)}/resend`, { method: "POST" });
        const count = result.queued?.length || 0;
        setStatus(`Sending again to ${count} ${count === 1 ? "person" : "people"}. Reload in a minute to see if it arrived.`);
      } else if (button.dataset.pick) {
        button.textContent = "Picking… (runs model checks)";
        state.pick = await runPick(api, button.dataset.pick, (run) => { button.textContent = pickProgressLabel(run); });
        setStatus("Pick done. Nothing reaches anyone until you ask or introduce.");
      }
      await reopen();
    } catch (error) {
      button.disabled = false;
      button.textContent = label;
      setStatus(error.message, "bad");
    }
  });

  detail.addEventListener("submit", async (event) => {
    const form = event.target.closest("form.pool-introduce");
    if (!form) return;
    event.preventDefault();
    const data = new FormData(form);
    const payload = { place: String(data.get("place") || "").trim(), when: String(data.get("when") || "").trim() };
    const meetAt = String(data.get("meet_at") || "");
    if (meetAt) payload.meet_at = new Date(meetAt).toISOString();
    form.querySelector("button").disabled = true;
    try {
      await api(`/api/admin/pairs/${encodeURIComponent(form.dataset.pairId)}/introduce`, { method: "POST", body: JSON.stringify(payload) });
      setStatus("Introduced. Omi tells both in their own chats, reminds them, and checks in.");
      await reopen();
    } catch (error) {
      form.querySelector("button").disabled = false;
      setStatus(error.message, "bad");
    }
  });

  detail.addEventListener("submit", async (event) => {
    const form = event.target.closest("form.pool-set-plan");
    if (!form) return;
    event.preventDefault();
    // Only what the operator changed is sent; the server keeps the rest of the plan as it is.
    const field = (name) => form.elements[name];
    const changes = planChanges(
      { place: field("place").defaultValue, when: field("when").defaultValue, meet_at: field("meet_at").defaultValue },
      { place: field("place").value, when: field("when").value, meet_at: field("meet_at").value },
    );
    if (!Object.keys(changes).length) {
      setStatus("Nothing changed in the plan.");
      return;
    }
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      await api(`/api/admin/pairs/${encodeURIComponent(form.dataset.pairId)}/plan`, { method: "POST", body: JSON.stringify(changes) });
      setStatus("Plan saved. Omi tells both in their own chats.");
      await reopen();
    } catch (error) {
      button.disabled = false;
      setStatus(error.message, "bad");
    }
  });

  detail.addEventListener("change", async (event) => {
    const select = event.target.closest("[data-pair-status]");
    if (!select) return;
    try {
      await api(`/api/admin/pairs/${encodeURIComponent(select.dataset.pairStatus)}`, { method: "PATCH", body: JSON.stringify({ status: select.value }) });
      setStatus("Status saved.");
      await reopen();
    } catch (error) {
      setStatus(error.message, "bad");
    }
  });
}
