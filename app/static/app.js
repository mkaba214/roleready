// RoleReady demo UI. Plain JS, no build step. All text goes through textContent (no innerHTML with data).
(() => {
  const ROLE_TASKS = {
    contributor: ["view_assets", "edit_drafts", "schedule_posts"],
    viewer: ["view_assets", "view_analytics"],
  };
  const ALL_TASKS = ["view_assets", "edit_drafts", "schedule_posts", "view_analytics", "manage_access"];
  const $ = (id) => document.getElementById(id);
  const state = { config: null, user: null, me: null, idToken: null, firebase: null };

  // DOM helper: h("td", {class: "x"}, "text", childNode)
  function h(tag, attrs = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "onclick") el.addEventListener("click", v);
      else if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid ?? "")));
    return el;
  }

  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (t.hidden = true), 4500);
  }

  async function api(path, { method = "GET", body } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (state.config.auth_mode === "demo" && state.user) headers["X-Demo-User"] = state.user;
    if (state.config.auth_mode === "firebase" && state.firebase?.auth().currentUser) {
      headers["Authorization"] = "Bearer " + (await state.firebase.auth().currentUser.getIdToken());
    }
    const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let data = null;
    try { data = await res.json(); } catch { /* empty body */ }
    if (!res.ok && !(res.status === 403 && data && "allowed" in data)) {
      const detail = data?.errors?.join("; ") || data?.detail || res.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return { status: res.status, data };
  }

  // Time zones ---------------------------------------------------------------
  // Times are stored in UTC. Each invitation carries the owner's IANA zone, and the
  // form reads and shows wall-clock times in that zone (not the browser's).
  const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const TZ_CHOICES = [...new Set([BROWSER_TZ, "America/Chicago", "America/New_York", "America/Denver",
    "America/Phoenix", "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu", "UTC"])];

  function fmt(iso, tz) {
    if (!iso) return "";
    const opts = { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" };
    try {
      return new Date(iso).toLocaleString([], { ...opts, timeZone: tz || undefined });
    } catch { return new Date(iso).toLocaleString([], opts); }  // unknown zone: show browser time, still labeled
  }
  // Milliseconds to add to UTC to get wall-clock time in tz at that instant.
  function tzOffsetMs(date, tz) {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric",
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })
      .formatToParts(date).map((x) => [x.type, x.value]));
    return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - Math.floor(date.getTime() / 1000) * 1000;
  }
  // "2026-11-09T09:00" read as wall-clock time in tz -> UTC ISO string
  function zonedInputToIso(value, tz) {
    const [d, t] = value.split("T");
    const [y, m, day] = d.split("-").map(Number);
    const [hh, mm] = t.split(":").map(Number);
    const wall = Date.UTC(y, m - 1, day, hh, mm);
    let utc = wall - tzOffsetMs(new Date(wall), tz);
    utc = wall - tzOffsetMs(new Date(utc), tz); // second pass settles DST edges
    return new Date(utc).toISOString();
  }
  // UTC ISO string -> "YYYY-MM-DDTHH:MM" wall-clock in tz, for datetime-local inputs
  function isoToZonedInput(iso, tz) {
    const date = new Date(iso);
    return new Date(date.getTime() + tzOffsetMs(date, tz)).toISOString().slice(0, 16);
  }

  // Identity -----------------------------------------------------------------
  function renderIdentity() {
    const box = $("identity");
    box.replaceChildren();
    if (state.config.auth_mode === "demo") {
      const sel = h("select", { "aria-label": "Demo user" },
        h("option", { value: "" }, "Choose a demo user"),
        state.config.demo_users.map((u) => h("option", { value: u, selected: u === state.user }, u)));
      sel.addEventListener("change", () => { state.user = sel.value || null; try { localStorage.setItem("rr-user", state.user || ""); } catch {} refresh(); });
      box.append(h("span", { class: "muted" }, "Demo mode"), sel);
    } else if (state.firebase) {
      const u = state.firebase.auth().currentUser;
      if (u) {
        box.append(h("span", {}, u.email), h("button", { class: "ghost", onclick: () => state.firebase.auth().signOut() }, "Sign out"));
      } else {
        const email = h("input", { type: "email", placeholder: "email" });
        const pw = h("input", { type: "password", placeholder: "password" });
        box.append(email, pw, h("button", { onclick: async () => {
          try { await state.firebase.auth().signInWithEmailAndPassword(email.value, pw.value); } catch (e) { toast(e.message); }
        } }, "Sign in"));
      }
    } else {
      box.append(h("span", { class: "muted" }, "Firebase sign-in is not configured"));
    }
  }

  function signedIn() {
    return state.config.auth_mode === "demo" ? Boolean(state.user) : Boolean(state.firebase?.auth().currentUser);
  }

  // Owner view ---------------------------------------------------------------
  function renderTaskBoxes(role, checked = []) {
    const fs = $("task-boxes");
    fs.replaceChildren(h("legend", {}, "Tasks"));
    for (const t of ROLE_TASKS[role]) {
      fs.append(h("label", {}, h("input", { type: "checkbox", name: "task", value: t, checked: checked.includes(t) }), " ", t));
    }
  }

  function setTimezone(tz) {
    const sel = $("tz-select");
    if (tz && ![...sel.options].some((o) => o.value === tz)) sel.append(h("option", { value: tz }, tz));
    if (tz) sel.value = tz;
  }

  function fillForm(draft) {
    const f = $("invite-form");
    f.invitee_email.value = draft.invitee_email || "";
    if (draft.role && ROLE_TASKS[draft.role]) f.role.value = draft.role;
    renderTaskBoxes(f.role.value, draft.task_types || []);
    setTimezone(draft.timezone || BROWSER_TZ);
    const tz = f.timezone.value;
    if (draft.start_at) f.start_at.value = isoToZonedInput(draft.start_at, tz);
    if (draft.expires_at) f.expires_at.value = isoToZonedInput(draft.expires_at, tz);
    f.reason.value = draft.reason || "";
    f.source.value = "assistant";
  }

  const STATUS_TEXT = (met) => (met === true ? "met" : met === false ? "NOT MET" : "tracked");
  async function loadMetrics() {
    const { data } = await api("/metrics");
    $("metrics").replaceChildren(...data.measures.map((m) => h("tr", {},
      h("td", {}, m.measure), h("td", {}, m.target), h("td", {}, m.actual),
      h("td", { class: m.met === true ? "allow" : m.met === false ? "deny" : "muted" }, STATUS_TEXT(m.met)))));
  }

  async function loadOwner() {
    const [inv, grants] = await Promise.all([api("/invitations"), api("/grants")]);
    $("invitations").replaceChildren(...inv.data.map((i) => h("tr", {},
      h("td", {}, i.invitee_email), h("td", {}, i.role), h("td", {}, i.task_types.join(", ")),
      h("td", {}, fmt(i.start_at, i.timezone), " to ", fmt(i.expires_at, i.timezone)), h("td", {}, i.status, i.source === "assistant" ? " (assistant)" : ""),
      h("td", {},
        i.status === "draft" ? h("button", { onclick: () => approve(i.id) }, "Approve") : "",
        ["draft", "approved"].includes(i.status) ? h("button", { class: "danger", onclick: () => cancel(i.id) }, "Cancel") : ""))));
    $("grants").replaceChildren(...grants.data.map((g) => h("tr", {},
      h("td", {}, g.user_email), h("td", {}, g.role), h("td", {}, (g.task_types || []).join(", ")),
      h("td", {}, fmt(g.start_at, g.timezone), " to ", fmt(g.expires_at, g.timezone)), h("td", { class: STATE_CLASS[g.state] || "" }, g.state),
      h("td", {}, g.status === "active" ? h("button", { class: "danger", onclick: () => revoke(g.id) }, "Revoke") : ""))));
    await Promise.all([loadAudit(), loadMetrics()]);
  }

  async function loadAudit() {
    const { data } = await api("/audit");
    $("audit").replaceChildren(...data.slice().reverse().map((e) => h("tr", {},
      h("td", {}, e.seq), h("td", {}, fmt(e.ts)), h("td", {}, e.actor), h("td", {}, e.action), h("td", {}, e.target || ""),
      h("td", { class: e.decision || "" }, e.decision || ""), h("td", {}, e.reason || ""))));
  }

  async function approve(id) {
    try {
      const { data } = await api(`/invitations/${id}/approve`, { method: "POST" });
      const box = $("invite-link");
      box.hidden = false;
      box.replaceChildren(h("strong", {}, "Invite link (shown once): "), data.invite_link, " ",
        h("button", { class: "ghost", onclick: () => navigator.clipboard?.writeText(data.invite_link).then(() => toast("Copied")) }, "Copy"),
        h("div", { class: "muted" }, "Token: ", data.invite_token));
      await loadOwner();
    } catch (e) { toast(e.message); }
  }
  async function cancel(id) { try { await api(`/invitations/${id}/cancel`, { method: "POST" }); await loadOwner(); } catch (e) { toast(e.message); } }
  async function revoke(id) { try { await api(`/grants/${id}/revoke`, { method: "POST" }); toast("Access revoked"); await loadOwner(); } catch (e) { toast(e.message); } }

  // Member view --------------------------------------------------------------
  const STATE_CLASS = { active: "allow", pending: "muted", expired: "deny", revoked: "deny" };

  async function loadMember() {
    $("my-grants").replaceChildren(...(state.me.grants.length ? state.me.grants.map((g) => h("li", {},
      h("strong", {}, g.role), ` · ${(g.task_types || []).join(", ")} · ${fmt(g.start_at, g.timezone)} to ${fmt(g.expires_at, g.timezone)} · `,
      h("span", { class: STATE_CLASS[g.state] || "" }, g.state))) : [h("li", { class: "muted" }, "No access yet.")]));
  }

  async function tryTask(task) {
    try {
      const { data } = await api(`/actions/${task}`, { method: "POST" });
      $("task-results").prepend(h("li", {}, new Date().toLocaleTimeString(), " · ", task, " · ",
        h("span", { class: data.allowed ? "allow" : "deny" }, data.allowed ? "allowed" : `denied (${data.reason})`)));
      state.me = (await api("/me")).data;  // states change with the clock, so re-read them
      await loadMember();
    } catch (e) { toast(e.message); }
  }

  async function accept(token) {
    try {
      await api("/invitations/accept", { method: "POST", body: { token } });
      toast("Invitation accepted");
      $("accept-token").value = "";
      history.replaceState(null, "", location.pathname);
      $("invite-banner").hidden = true;
      await refresh();
    } catch (e) { toast(e.message); }
  }

  // Refresh ------------------------------------------------------------------
  async function refresh() {
    renderIdentity();
    const ok = signedIn();
    $("signed-out").hidden = ok;
    $("owner-view").hidden = true;
    $("member-view").hidden = true;
    if (!ok) return;
    try {
      state.me = (await api("/me")).data;
    } catch (e) { toast(e.message); return; }
    if (state.me.is_owner) {
      $("owner-view").hidden = false;
      $("assistant-card").hidden = !state.config.assistant_enabled;
      $("run-expiry").hidden = state.config.auth_mode !== "demo";
      await loadOwner().catch((e) => toast(e.message));
    } else {
      $("member-view").hidden = false;
      await loadMember();
    }
  }

  // Wire up ------------------------------------------------------------------
  function wire() {
    const f = $("invite-form");
    renderTaskBoxes("contributor", ["view_assets", "edit_drafts"]);
    f.role.addEventListener("change", () => renderTaskBoxes(f.role.value));
    $("tz-select").replaceChildren(...TZ_CHOICES.map((tz) => h("option", { value: tz }, tz)));
    setTimezone(state.config.timezone && TZ_CHOICES.includes(state.config.timezone) ? state.config.timezone : BROWSER_TZ);
    const setWindow = (startMs, endMs) => {
      f.start_at.value = isoToZonedInput(new Date(startMs).toISOString(), f.timezone.value);
      f.expires_at.value = isoToZonedInput(new Date(endMs).toISOString(), f.timezone.value);
    };
    const now = Date.now();
    setWindow(now + 5 * 60000, now + 4 * 86400000);
    // Changing the zone keeps the same moment and re-displays it, so a default window never jumps into the past.
    let lastTz = f.timezone.value;
    f.timezone.addEventListener("change", () => {
      for (const input of [f.start_at, f.expires_at]) {
        if (input.value) input.value = isoToZonedInput(zonedInputToIso(input.value, lastTz), f.timezone.value);
      }
      lastTz = f.timezone.value;
    });

    $("quick-window").addEventListener("click", () => {
      const n = Date.now();
      setWindow(n + 30000, n + 3 * 60000 + 30000);
      toast("Window set: starts in 30 seconds, ends 3 minutes later");
    });

    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const tz = f.timezone.value;
      const body = {
        invitee_email: f.invitee_email.value,
        role: f.role.value,
        task_types: [...f.querySelectorAll("input[name=task]:checked")].map((i) => i.value),
        start_at: zonedInputToIso(f.start_at.value, tz),
        expires_at: zonedInputToIso(f.expires_at.value, tz),
        timezone: tz,
        reason: f.reason.value,
        source: f.source.value,
      };
      try { await api("/invitations", { method: "POST", body }); f.source.value = "manual"; toast("Draft created. Approve it below."); await loadOwner(); }
      catch (e) { toast(e.message); }
    });

    $("assistant-draft").addEventListener("click", async () => {
      const btn = $("assistant-draft");
      btn.disabled = true;
      $("assistant-status").textContent = "Drafting...";
      $("assistant-notes").replaceChildren();
      try {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const { data } = await api("/agent/draft-invitation", { method: "POST", body: { request: $("assistant-input").value, timezone: tz } });
        if (data.draft) fillForm(data.draft);
        $("assistant-status").textContent = data.ok ? `Draft ready (${data.model}, ${data.latency_ms} ms). Review the form, then create.` : "Draft needs fixes.";
        $("assistant-notes").replaceChildren(
          ...data.errors.map((m) => h("li", { class: "err" }, m)),
          ...data.warnings.map((m) => h("li", { class: "warn" }, m)));
      } catch (e) { $("assistant-status").textContent = ""; toast(e.message); }
      btn.disabled = false;
    });

    $("explain-go").addEventListener("click", async () => {
      $("explain-answer").textContent = "Thinking...";
      try {
        const { data } = await api("/agent/explain-audit", { method: "POST", body: { question: $("explain-input").value } });
        $("explain-answer").textContent = data.answer + (data.grounded ? "" : "\n(Warning: answer cites events not in the log.)");
      } catch (e) { $("explain-answer").textContent = ""; toast(e.message); }
    });

    $("audit-refresh").addEventListener("click", () => loadOwner().catch((e) => toast(e.message)));
    $("metrics-refresh").addEventListener("click", () => loadMetrics().catch((e) => toast(e.message)));
    $("audit-verify").addEventListener("click", async () => {
      const { data } = await api("/audit/verify");
      $("verify-result").textContent = data.ok ? `Chain intact: ${data.checked} events verified.` : `Chain broken at ${data.broken_at}: ${data.problem}`;
    });
    $("run-expiry").addEventListener("click", async () => {
      const { data } = await api("/dev/run-expiry", { method: "POST" });
      toast(`Expiry job: ${data.expired.length} expired, ${data.already_handled} already handled`);
      await loadOwner();
    });

    $("accept-go").addEventListener("click", () => accept($("accept-token").value.trim()));
    $("banner-accept").addEventListener("click", () => accept(new URLSearchParams(location.hash.slice(1)).get("invite")));
    $("task-buttons").replaceChildren(...ALL_TASKS.map((t) => h("button", { class: "ghost", onclick: () => tryTask(t) }, t)));

    checkInvite();
    window.addEventListener("hashchange", checkInvite);
  }

  function checkInvite() {
    const invite = new URLSearchParams(location.hash.slice(1)).get("invite");
    if (invite) { $("invite-banner").hidden = false; $("accept-token").value = invite; }
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => { const s = h("script", { src }); s.onload = resolve; s.onerror = reject; document.head.append(s); });
  }

  async function start() {
    state.config = (await (await fetch("/config")).json());
    $("ws-name").textContent = "· " + state.config.workspace.name;
    wire();
    if (state.config.auth_mode === "demo") {
      try { state.user = localStorage.getItem("rr-user") || null; } catch { state.user = null; }
    } else if (state.config.firebase) {
      await loadScript("https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js");
      await loadScript("https://www.gstatic.com/firebasejs/10.12.2/firebase-auth-compat.js");
      window.firebase.initializeApp(state.config.firebase);
      state.firebase = window.firebase;
      // Local Floci only: sign in against the emulated Firebase Auth instead of Google.
      if (state.config.firebase_auth_emulator_url) state.firebase.auth().useEmulator(state.config.firebase_auth_emulator_url);
      state.firebase.auth().onAuthStateChanged(() => refresh());
    }
    await refresh();
  }

  start().catch((e) => toast("Could not start: " + e.message));
})();
