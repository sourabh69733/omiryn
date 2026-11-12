// Pools page: list, one open pool, and the operator actions (create, pick, propose, ask, introduce, status).
import { renderPickResult, renderPoolList, renderPoolView } from "../pools.js";
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
    const button = event.target.closest("[data-propose], [data-ask], [data-pick]");
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
      } else if (button.dataset.pick) {
        button.textContent = "Picking… (runs model checks)";
        state.pick = await api(`/api/admin/pools/${encodeURIComponent(button.dataset.pick)}/pick`, { method: "POST" });
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
