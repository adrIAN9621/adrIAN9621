/* Carpatica Asistență IT – consola tehnicianului (JS simplu, fără dependențe). */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  };

  const QUALITY = {
    fast: { quality: 40, scale: 0.75, fps: 15 },
    balanced: { quality: 60, scale: 1.0, fps: 10 },
    quality: { quality: 85, scale: 1.0, fps: 6 },
  };
  const EVENT_NAMES = {
    login: "Autentificare", login_failed: "Autentificare eșuată", logout: "Deconectare",
    connect_request: "Cerere conectare", accepted: "Acceptat", rejected: "Refuzat",
    timeout: "Fără răspuns", session_end: "Sesiune încheiată", wrong_code: "Cod greșit",
    agent_registered: "Calculator nou", agent_rejected: "Calculator respins",
  };
  const BAD_EVENTS = new Set(["login_failed", "rejected", "timeout", "wrong_code", "agent_rejected"]);
  const GOOD_EVENTS = new Set(["accepted", "login", "agent_registered"]);

  let me = null;
  let agents = [];
  let agentsTimer = null;
  let currentTab = "agents";

  // ------------------------------------------------------------------ utilitare
  async function api(path, opts) {
    opts = opts || {};
    const init = { method: opts.method || "GET", credentials: "same-origin", headers: {} };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    const r = await fetch(path, init);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (r.status === 401 && path !== "/api/login") {
      showLogin();
      throw new Error("Sesiunea a expirat. Autentificați-vă din nou.");
    }
    if (!r.ok) throw new Error((data && data.error) || ("Eroare " + r.status));
    return data;
  }

  function toast(text, opts) {
    opts = opts || {};
    const t = el("div", "toast" + (opts.error ? " err" : ""));
    t.appendChild(el("span", null, text));
    if (opts.action) {
      const b = el("button", null, opts.action.label);
      b.addEventListener("click", () => { opts.action.fn(); t.remove(); });
      t.appendChild(b);
    }
    $("toasts").appendChild(t);
    setTimeout(() => t.remove(), opts.ms || 5000);
  }

  function fmtTime(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleString("ro-RO", { day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
  function fmtAgo(ts) {
    if (!ts) return "—";
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return "acum";
    if (s < 3600) return "acum " + Math.floor(s / 60) + " min";
    if (s < 86400) return "acum " + Math.floor(s / 3600) + " h";
    return fmtTime(ts);
  }
  const fmtId = (id) => String(id || "").replace(/(\d{3})(?=\d)/g, "$1 ");
  const digits = (v) => String(v || "").replace(/\D/g, "");

  // modal generic (confirmare / introducere text)
  function modal(title, text, opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      $("modal-title").textContent = title;
      $("modal-text").textContent = text || "";
      const inp = $("modal-input");
      inp.classList.toggle("hidden", !opts.input);
      inp.value = opts.value || "";
      $("modal-ok").textContent = opts.ok || "OK";
      $("modal").classList.remove("hidden");
      if (opts.input) setTimeout(() => inp.focus(), 0); else $("modal-ok").focus();
      const done = (val) => {
        $("modal").classList.add("hidden");
        $("modal-ok").removeEventListener("click", ok);
        $("modal-cancel").removeEventListener("click", cancel);
        resolve(val);
      };
      const ok = () => done(opts.input ? inp.value : true);
      const cancel = () => done(null);
      $("modal-ok").addEventListener("click", ok);
      $("modal-cancel").addEventListener("click", cancel);
    });
  }

  // ------------------------------------------------------------------ autentificare
  function showLogin() {
    stopAgentsRefresh();
    $("app-view").classList.add("hidden");
    $("session-view").classList.add("hidden");
    $("login-view").classList.remove("hidden");
    setTimeout(() => $("login-user").focus(), 0);
  }

  function showApp() {
    $("login-view").classList.add("hidden");
    $("app-view").classList.remove("hidden");
    $("me-name").textContent = me.display_name;
    switchTab(currentTab);
  }

  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("login-error").textContent = "";
    $("login-btn").disabled = true;
    try {
      me = await api("/api/login", { method: "POST",
        body: { username: $("login-user").value.trim(), password: $("login-pass").value } });
      $("login-pass").value = "";
      showApp();
    } catch (err) {
      $("login-error").textContent = err.message;
    } finally {
      $("login-btn").disabled = false;
    }
  });

  $("logout-btn").addEventListener("click", async () => {
    try { await api("/api/logout", { method: "POST" }); } catch (e) { /* ignorat */ }
    me = null;
    showLogin();
  });

  // ------------------------------------------------------------------ taburi
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.addEventListener("click", () => switchTab(b.dataset.tab)));

  function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll(".nav-item").forEach((b) =>
      b.classList.toggle("active", b.dataset.tab === tab));
    $("tab-agents").classList.toggle("hidden", tab !== "agents");
    $("tab-audit").classList.toggle("hidden", tab !== "audit");
    $("page-title").textContent = tab === "agents" ? "Calculatoare" : "Jurnal de audit";
    if (tab === "agents") startAgentsRefresh(); else { stopAgentsRefresh(); loadAudit(); }
  }

  // ------------------------------------------------------------------ calculatoare
  function startAgentsRefresh() {
    stopAgentsRefresh();
    loadAgents();
    agentsTimer = setInterval(loadAgents, 5000);
  }
  function stopAgentsRefresh() {
    if (agentsTimer) clearInterval(agentsTimer);
    agentsTimer = null;
  }

  async function loadAgents() {
    try {
      agents = await api("/api/agents");
      renderAgents();
    } catch (e) { /* tratat în api() */ }
  }

  function renderAgents() {
    const q = $("agent-search").value.trim().toLowerCase();
    const qd = digits(q);
    const list = agents.filter((a) => !q ||
      (qd && a.agent_id.includes(qd)) ||
      (a.hostname || "").toLowerCase().includes(q) ||
      (a.user || "").toLowerCase().includes(q));
    const tbody = $("agents-table").querySelector("tbody");
    tbody.replaceChildren();
    for (const a of list) {
      const tr = el("tr", a.online ? "" : "offline");
      const st = el("span", "status" + (a.online ? (a.in_session ? " busy" : " on") : ""),
        a.online ? (a.in_session ? "În sesiune" : "Online") : "Offline");
      const td0 = el("td"); td0.appendChild(st); tr.appendChild(td0);
      tr.appendChild(el("td", "mono", fmtId(a.agent_id)));
      tr.appendChild(el("td", null, a.hostname || "—"));
      tr.appendChild(el("td", null, a.user || "—"));
      tr.appendChild(el("td", null, a.os || "—"));
      tr.appendChild(el("td", null, a.version || "—"));
      tr.appendChild(el("td", null, a.online ? "acum" : fmtAgo(a.last_seen)));
      const td = el("td");
      if (a.online && !a.in_session) {
        const b = el("button", "btn btn-secondary btn-sm", "Conectare…");
        b.addEventListener("click", () => {
          $("c-id").value = fmtId(a.agent_id);
          $("c-code").value = "";
          $("c-code").focus();
          window.scrollTo({ top: 0, behavior: "smooth" });
        });
        td.appendChild(b);
      }
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    const online = agents.filter((a) => a.online).length;
    $("agents-count").textContent = online + " online / " + agents.length;
    $("agents-empty").classList.toggle("hidden", list.length > 0);
  }
  $("agent-search").addEventListener("input", renderAgents);

  $("c-id").addEventListener("input", (e) => { e.target.value = fmtId(digits(e.target.value).slice(0, 9)); });
  $("c-code").addEventListener("input", (e) => { e.target.value = digits(e.target.value).slice(0, 6); });

  // ------------------------------------------------------------------ audit
  async function loadAudit() {
    try {
      const rows = await api("/api/audit?limit=300");
      const tbody = $("audit-table").querySelector("tbody");
      tbody.replaceChildren();
      for (const r of rows) {
        const tr = el("tr");
        tr.appendChild(el("td", null, fmtTime(r.ts)));
        const td = el("td");
        td.appendChild(el("span", "ev" + (BAD_EVENTS.has(r.event) ? " bad" : GOOD_EVENTS.has(r.event) ? " good" : ""),
          EVENT_NAMES[r.event] || r.event));
        tr.appendChild(td);
        tr.appendChild(el("td", null, r.tech || "—"));
        tr.appendChild(el("td", "mono", r.agent_id ? fmtId(r.agent_id) : "—"));
        tr.appendChild(el("td", null, r.hostname || "—"));
        tr.appendChild(el("td", "mono", r.ip || "—"));
        tr.appendChild(el("td", null, r.details || ""));
        tbody.appendChild(tr);
      }
    } catch (e) { toast(e.message, { error: true }); }
  }
  $("audit-refresh").addEventListener("click", loadAudit);

  // ------------------------------------------------------------------ sesiune
  const canvas = $("screen");
  const ctx = canvas.getContext("2d");
  let ws = null;
  let sess = null; // {state, hostname, monitors, ...}

  $("connect-form").addEventListener("submit", (e) => {
    e.preventDefault();
    $("connect-error").textContent = "";
    const id = digits($("c-id").value);
    const code = digits($("c-code").value);
    if (id.length !== 9) { $("connect-error").textContent = "ID-ul are 9 cifre."; return; }
    if (code.length !== 6) { $("connect-error").textContent = "Codul de acces are 6 cifre."; return; }
    startConnection(id, code);
  });

  function startConnection(agentId, code) {
    if (ws) return;
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    const sock = new WebSocket(proto + location.host + "/ws/tech");
    ws = sock;
    ws.binaryType = "arraybuffer";
    sess = { state: "connecting", agentId: agentId, hostname: "", monitors: [] };
    $("waiting-text").textContent = "Angajatul trebuie să confirme conexiunea pe calculatorul său.";
    $("waiting").classList.remove("hidden");
    ws.onopen = () => send({ t: "connect", agent_id: agentId, code: code });
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        let m;
        try { m = JSON.parse(ev.data); } catch (e) { return; }
        onMessage(m);
      } else {
        onTile(ev.data);
      }
    };
    ws.onclose = (ev) => {
      if (ws !== sock) return;
      const wasActive = sess && sess.state === "active";
      const wasPending = sess && (sess.state === "waiting" || sess.state === "connecting");
      ws = null;
      if (wasActive) finishSession("Conexiunea cu serverul s-a întrerupt.");
      else if (wasPending) {
        $("waiting").classList.add("hidden");
        $("connect-error").textContent = ev.code === 4401 ? "Sesiunea a expirat. Autentificați-vă din nou."
          : "Conexiunea cu serverul a eșuat.";
        sess = null;
        if (ev.code === 4401) showLogin();
      }
    };
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function onMessage(m) {
    switch (m.t) {
      case "waiting":
        sess.state = "waiting";
        if (m.hostname) $("waiting-text").textContent =
          "Angajatul de pe „" + m.hostname + "” trebuie să confirme conexiunea.";
        break;
      case "error":
        $("waiting").classList.add("hidden");
        if (sess && sess.state === "active") toast(m.message, { error: true });
        else {
          $("connect-error").textContent = m.message;
          closeWs();
        }
        break;
      case "started":
        $("waiting").classList.add("hidden");
        beginSession(m);
        break;
      case "ended":
        finishSession(m.reason || "Sesiunea s-a încheiat.");
        break;
      case "frame_done":
        onFrameDone(m.seq);
        break;
      case "cursor":
        break;
      case "view_only":
        {
          const was = sess.viewOnly;
          sess.viewOnly = !!m.value;
          $("sess-viewonly").classList.toggle("hidden", !sess.viewOnly);
          if (sess.viewOnly && !was) { releaseAllKeys(); toast("Utilizatorul a activat „Doar vizualizare”. Controlul este blocat."); }
          else if (!sess.viewOnly && was) toast("Controlul a fost reactivat de utilizator.");
        }
        break;
      case "clipboard":
        if (typeof m.text === "string") {
          const txt = m.text;
          toast("Clipboard primit de la calculatorul la distanță (" + txt.length + " caractere).",
            { ms: 15000, action: { label: "Copiază", fn: () => copyLocal(txt) } });
        }
        break;
      case "chat":
        addChat(m.from || sess.hostname || "Utilizator", m.text, false);
        break;
      case "pong":
        break;
      default:
        break;
    }
  }

  function closeWs() {
    if (ws) { try { ws.close(); } catch (e) { /* ignorat */ } }
    ws = null;
    sess = null;
  }

  $("waiting-cancel").addEventListener("click", () => {
    send({ t: "end" });
    $("waiting").classList.add("hidden");
    closeWs();
  });

  // ----- început / sfârșit
  function beginSession(m) {
    stopAgentsRefresh();
    Object.assign(sess, {
      state: "active", id: m.session_id, hostname: m.hostname || "", monitors: m.monitors || [],
      viewOnly: false, tiles: [], chain: Promise.resolve(), frames: 0, bytes: 0,
      actual: false, unread: 0, sw: 0, sh: 0,
    });
    $("sess-host").textContent = (m.hostname || "Calculator") + (m.user ? " – " + m.user : "") +
      " (" + fmtId(m.agent_id || sess.agentId) + ")";
    $("sess-viewonly").classList.add("hidden");
    const sel = $("sel-monitor");
    sel.replaceChildren();
    (sess.monitors.length ? sess.monitors : [{ index: 0, width: 0, height: 0, primary: true }]).forEach((mon, i) => {
      const idx = mon.index !== undefined ? mon.index : i;
      const o = el("option", null, "Monitor " + (idx + 1) + (mon.width ? " (" + mon.width + "×" + mon.height + ")" : "") +
        (mon.primary ? " – principal" : ""));
      o.value = idx;
      if (mon.primary) o.selected = true;
      sel.appendChild(o);
    });
    $("chat-log").replaceChildren();
    $("chat-panel").classList.add("hidden");
    updateUnread();
    canvas.width = 1; canvas.height = 1;
    $("screen-msg").classList.remove("hidden");
    $("screen-msg").textContent = "Se așteaptă imaginea…";
    setActual(false);
    $("app-view").classList.add("hidden");
    $("session-view").classList.remove("hidden");
    setStatus("Conectat", "");
    send(Object.assign({ t: "quality" }, QUALITY[$("sel-quality").value]));
    sess.statTimer = setInterval(updateStats, 1000);
    sess.pingTimer = setInterval(() => send({ t: "ping" }), 20000);
    canvas.focus();
  }

  function finishSession(reason) {
    if (!sess) return;
    releaseAllKeys();
    clearInterval(sess.statTimer);
    clearInterval(sess.pingTimer);
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    closeWs();
    $("session-view").classList.add("hidden");
    $("app-view").classList.remove("hidden");
    toast("Sesiune încheiată: " + reason, { ms: 7000 });
    switchTab(currentTab);
  }

  $("btn-end").addEventListener("click", async () => {
    if (await modal("Încheiați sesiunea?", "Conexiunea cu calculatorul la distanță va fi închisă.", { ok: "Încheie sesiunea" })) {
      send({ t: "end" });
      setTimeout(() => { if (sess && sess.state === "active") finishSession("Sesiune încheiată de tehnician"); }, 1500);
    }
  });

  function setStatus(text, cls) {
    const s = $("st-state");
    s.textContent = text;
    s.className = "st-dot" + (cls ? " " + cls : "");
  }

  function updateStats() {
    if (!sess) return;
    $("st-fps").textContent = sess.frames + " fps";
    $("st-kbps").textContent = Math.round(sess.bytes / 1024) + " KB/s";
    sess.frames = 0; sess.bytes = 0;
  }

  // ----- dale (tiles)
  function onTile(buf) {
    if (!sess || sess.state !== "active" || buf.byteLength < 17) return;
    const dv = new DataView(buf);
    const type = dv.getUint8(0);
    const seq = dv.getUint32(1, true);
    const x = dv.getUint16(5, true), y = dv.getUint16(7, true);
    const w = dv.getUint16(9, true), h = dv.getUint16(11, true);
    const sw = dv.getUint16(13, true), sh = dv.getUint16(15, true);
    sess.bytes += buf.byteLength;
    const blob = new Blob([new Uint8Array(buf, 17)], { type: type === 2 ? "image/png" : "image/jpeg" });
    const p = createImageBitmap(blob).catch(() => null);
    sess.tiles.push({ seq, x, y, w, h, sw, sh, p });
  }

  function onFrameDone(seq) {
    const tiles = sess.tiles;
    sess.tiles = [];
    const s = sess;
    s.chain = s.chain.then(async () => {
      const bms = await Promise.all(tiles.map((t) => t.p));
      if (sess !== s) { bms.forEach((b) => b && b.close()); return; }
      tiles.forEach((t, i) => {
        if (t.sw && t.sh && (t.sw !== canvas.width || t.sh !== canvas.height)) resizeCanvas(t.sw, t.sh);
        const bm = bms[i];
        if (bm) { ctx.drawImage(bm, t.x, t.y, t.w || bm.width, t.h || bm.height); bm.close(); }
      });
      if (tiles.length) $("screen-msg").classList.add("hidden");
      s.frames++;
      send({ t: "ack", seq: seq });
    }).catch(() => send({ t: "ack", seq: seq }));
  }

  function resizeCanvas(w, h) {
    canvas.width = w; canvas.height = h;
    sess.sw = w; sess.sh = h;
    $("st-res").textContent = w + "×" + h;
    fitCanvas();
  }

  function fitCanvas() {
    if (!sess) return;
    const w = canvas.width, h = canvas.height;
    if (sess.actual) {
      canvas.style.width = w + "px"; canvas.style.height = h + "px";
      return;
    }
    const wrap = $("screen-wrap");
    const k = Math.min(wrap.clientWidth / w, wrap.clientHeight / h);
    canvas.style.width = Math.max(1, Math.floor(w * k)) + "px";
    canvas.style.height = Math.max(1, Math.floor(h * k)) + "px";
  }
  window.addEventListener("resize", fitCanvas);
  document.addEventListener("fullscreenchange", () => setTimeout(fitCanvas, 50));

  function setActual(on) {
    if (sess) sess.actual = on;
    $("btn-actual").classList.toggle("on", on);
    $("screen-wrap").classList.toggle("actual", on);
    fitCanvas();
  }
  $("btn-actual").addEventListener("click", () => setActual(!(sess && sess.actual)));

  // ----- mouse
  function toRemote(e) {
    const r = canvas.getBoundingClientRect();
    const x = Math.round((e.clientX - r.left) * canvas.width / r.width);
    const y = Math.round((e.clientY - r.top) * canvas.height / r.height);
    return { x: Math.max(0, Math.min(canvas.width - 1, x)), y: Math.max(0, Math.min(canvas.height - 1, y)) };
  }
  const canControl = () => sess && sess.state === "active" && !sess.viewOnly && canvas.width > 1;
  const BTN = ["left", "middle", "right"];

  let lastMove = 0, moveTimer = null, pendingMove = null;
  function flushMove() {
    moveTimer = null;
    if (pendingMove) { send(pendingMove); pendingMove = null; lastMove = performance.now(); }
  }
  canvas.addEventListener("mousemove", (e) => {
    if (!canControl()) return;
    const p = toRemote(e);
    pendingMove = { t: "mouse", action: "move", x: p.x, y: p.y };
    const dt = performance.now() - lastMove;
    if (dt >= 33) flushMove();
    else if (!moveTimer) moveTimer = setTimeout(flushMove, 33 - dt);
  });
  canvas.addEventListener("mousedown", (e) => {
    canvas.focus();
    e.preventDefault();
    if (!canControl()) return;
    flushMove();
    const p = toRemote(e);
    send({ t: "mouse", action: "down", x: p.x, y: p.y, button: BTN[e.button] || "left" });
  });
  canvas.addEventListener("mouseup", (e) => {
    e.preventDefault();
    if (!canControl()) return;
    flushMove();
    const p = toRemote(e);
    send({ t: "mouse", action: "up", x: p.x, y: p.y, button: BTN[e.button] || "left" });
  });
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (!canControl()) return;
    // dx/dy în „trepte” de rotiță; sens ca în browser: dy > 0 = derulare în jos
    const unit = e.deltaMode === 1 ? 3 : e.deltaMode === 2 ? 0.1 : 100;
    const norm = (d) => d === 0 ? 0 : Math.sign(d) * Math.max(1, Math.round(Math.abs(d) / unit));
    const p = toRemote(e);
    send({ t: "mouse", action: "wheel", x: p.x, y: p.y, dx: norm(e.deltaX), dy: norm(e.deltaY) });
  }, { passive: false });

  // ----- tastatură
  const pressed = new Map();
  canvas.addEventListener("keydown", (e) => {
    if (!sess || sess.state !== "active") return;
    e.preventDefault();
    e.stopPropagation();
    if (!canControl()) return;
    pressed.set(e.code, e.key);
    send({ t: "key", action: "down", code: e.code, key: e.key });
  });
  canvas.addEventListener("keyup", (e) => {
    if (!sess || sess.state !== "active") return;
    e.preventDefault();
    e.stopPropagation();
    if (!canControl() && !pressed.has(e.code)) return;
    pressed.delete(e.code);
    send({ t: "key", action: "up", code: e.code, key: e.key });
  });
  function releaseAllKeys() {
    for (const [code, key] of pressed) send({ t: "key", action: "up", code: code, key: key });
    pressed.clear();
  }
  canvas.addEventListener("blur", releaseAllKeys);
  window.addEventListener("blur", releaseAllKeys);

  // ----- bara de unelte
  $("sel-monitor").addEventListener("change", (e) => {
    send({ t: "monitor", index: parseInt(e.target.value, 10) || 0 });
    $("screen-msg").textContent = "Se schimbă monitorul…";
    canvas.focus();
  });
  $("sel-quality").addEventListener("change", (e) => {
    send(Object.assign({ t: "quality" }, QUALITY[e.target.value]));
    canvas.focus();
  });
  $("btn-refresh").addEventListener("click", () => { send({ t: "refresh" }); canvas.focus(); });

  $("btn-text").addEventListener("click", async () => {
    if (!canControl()) { toast("Controlul nu este disponibil.", { error: true }); return; }
    const text = await modal("Trimite text", "Textul va fi tastat pe calculatorul la distanță, în fereastra activă.",
      { input: true, ok: "Tastează" });
    if (text) send({ t: "text", text: text });
    canvas.focus();
  });

  $("btn-clip").addEventListener("click", async () => {
    if (!canControl()) { toast("Controlul nu este disponibil.", { error: true }); return; }
    let text = null;
    try { if (navigator.clipboard && navigator.clipboard.readText) text = await navigator.clipboard.readText(); }
    catch (e) { text = null; }
    if (text === null) {
      text = await modal("Trimite clipboard", "Lipiți (Ctrl+V) textul care trebuie pus în clipboard-ul calculatorului la distanță.",
        { input: true, ok: "Trimite" });
    }
    if (text) { send({ t: "clipboard", text: text }); toast("Clipboard trimis (" + text.length + " caractere)."); }
    canvas.focus();
  });

  function copyLocal(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => toast("Copiat în clipboard."),
        () => modal("Clipboard primit", "Copiați manual textul de mai jos.", { input: true, value: text }));
    } else {
      modal("Clipboard primit", "Copiați manual textul de mai jos.", { input: true, value: text });
    }
  }

  $("btn-fs").addEventListener("click", () => {
    const v = $("session-view");
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else if (v.requestFullscreen) v.requestFullscreen().catch(() => toast("Ecranul complet nu este disponibil.", { error: true }));
  });

  // ----- chat
  function addChat(who, text, mine) {
    const m = el("div", "msg" + (mine ? " me" : ""));
    m.appendChild(el("span", "who", who));
    m.appendChild(document.createTextNode(String(text || "")));
    $("chat-log").appendChild(m);
    $("chat-log").scrollTop = $("chat-log").scrollHeight;
    if (!mine && $("chat-panel").classList.contains("hidden")) {
      sess.unread++;
      updateUnread();
      toast("Mesaj de la " + who + ": " + text, { ms: 6000 });
    }
  }
  function updateUnread() {
    const u = sess ? sess.unread || 0 : 0;
    $("chat-unread").textContent = u;
    $("chat-unread").classList.toggle("hidden", !u);
  }
  function toggleChat(show) {
    const p = $("chat-panel");
    const vis = show === undefined ? p.classList.contains("hidden") : show;
    p.classList.toggle("hidden", !vis);
    if (vis) { sess.unread = 0; updateUnread(); $("chat-input").focus(); }
    setTimeout(fitCanvas, 0);
  }
  $("btn-chat").addEventListener("click", () => toggleChat());
  $("chat-close").addEventListener("click", () => toggleChat(false));
  $("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const t = $("chat-input").value.trim();
    if (!t) return;
    send({ t: "chat", text: t, from: me ? me.display_name : "" });
    addChat(me ? me.display_name : "Eu", t, true);
    $("chat-input").value = "";
  });

  // ------------------------------------------------------------------ pornire
  setInterval(() => {
    $("clock").textContent = new Date().toLocaleString("ro-RO", { weekday: "short", hour: "2-digit", minute: "2-digit" });
  }, 1000);

  (async function init() {
    try {
      const r = await fetch("/api/me", { credentials: "same-origin" });
      if (r.ok) { me = await r.json(); showApp(); } else showLogin();
    } catch (e) { showLogin(); }
  })();
})();
