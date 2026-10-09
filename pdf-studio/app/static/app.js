/* PDF Studio – interfață web (vanilla JS, fără dependențe externe). */
(() => {
  "use strict";

  // =================================================================== utilitare
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "html") el.innerHTML = v;
        else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
        else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
        else if (v === true) el.setAttribute(k, "");
        else el.setAttribute(k, v);
      }
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    return d.toLocaleString("ro-RO", { dateStyle: "medium", timeStyle: "short" });
  }

  function fmtSize(n) {
    if (n == null) return "";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1).replace(".", ",") + " KB";
    return (n / 1024 / 1024).toFixed(2).replace(".", ",") + " MB";
  }

  // ---------------------------------------------------------------- toast
  function toast(msg, type = "info", ms) {
    const el = h("div", { class: "toast " + type, role: type === "err" ? "alert" : "status" }, msg);
    $("#toasts").append(el);
    setTimeout(() => el.remove(), ms || (type === "err" ? 8000 : 4500));
    el.addEventListener("click", () => el.remove());
  }

  // ---------------------------------------------------------------- API
  let pending = 0;
  function progress(delta) {
    pending = Math.max(0, pending + delta);
    $("#progress").hidden = pending === 0;
  }

  function errorText(data, status) {
    if (data && data.detail != null) {
      const d = data.detail;
      if (typeof d === "string") return d;
      if (Array.isArray(d)) {
        return d.map((e) => {
          const loc = Array.isArray(e.loc) ? e.loc.filter((x) => x !== "body").join(".") : "";
          return (loc ? `${loc}: ` : "") + (e.msg || JSON.stringify(e));
        }).join("\n");
      }
      return JSON.stringify(d);
    }
    return `Eroare de server (${status}).`;
  }

  /**
   * Cerere către API. `body` poate fi FormData sau obiect (trimis JSON).
   * `as`: "json" (implicit) | "blob" (returnează {blob, filename}).
   */
  async function api(url, { method, body, as = "json" } = {}) {
    const opts = { method: method || (body ? "POST" : "GET") };
    if (body instanceof FormData) opts.body = body;
    else if (body !== undefined) {
      opts.body = JSON.stringify(body);
      opts.headers = { "Content-Type": "application/json" };
    }
    progress(1);
    try {
      let res;
      try {
        res = await fetch(url, opts);
      } catch (e) {
        throw new Error("Serverul local nu răspunde. Verificați că PDF Studio rulează.");
      }
      if (!res.ok) {
        let data = null;
        try { data = await res.json(); } catch (_) { /* nu e JSON */ }
        throw new Error(errorText(data, res.status));
      }
      if (as === "blob") {
        const blob = await res.blob();
        return { blob, filename: filenameFrom(res.headers.get("Content-Disposition")) };
      }
      return await res.json();
    } finally {
      progress(-1);
    }
  }

  function filenameFrom(cd) {
    if (!cd) return null;
    let m = /filename\*\s*=\s*([^']*)''([^;]+)/i.exec(cd);
    if (m) {
      try { return decodeURIComponent(m[2].trim().replace(/^"|"$/g, "")); } catch (_) { /* ignorăm */ }
    }
    m = /filename\s*=\s*"?([^";]+)"?/i.exec(cd);
    return m ? m[1] : null;
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = h("a", { href: url, download: filename || "document" });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  /** Rulează fn cu butonul în stare „ocupat”; erorile sunt afișate ca toast. */
  async function busy(btn, fn) {
    if (btn && btn.disabled) return;
    if (btn) { btn.disabled = true; btn.classList.add("busy"); }
    try {
      return await fn();
    } catch (e) {
      toast(e.message || String(e), "err");
    } finally {
      if (btn) { btn.disabled = false; btn.classList.remove("busy"); }
    }
  }

  function fd(obj) {
    const f = new FormData();
    for (const [k, v] of Object.entries(obj)) {
      if (v == null) continue;
      if (v instanceof Blob) f.append(k, v, v.name || "document.pdf");
      else f.append(k, v);
    }
    return f;
  }

  const isPdf = (f) => f && (f.type === "application/pdf" || /\.pdf$/i.test(f.name || ""));

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(",")[1] || "");
      r.onerror = () => reject(new Error("Fișierul nu a putut fi citit."));
      r.readAsDataURL(file);
    });
  }

  // ---------------------------------------------------------------- drop zone
  function dropZone(host, { accept = ".pdf,application/pdf", multiple = false, title, sub, onChange, validate } = {}) {
    const input = h("input", { type: "file", accept, multiple });
    const filesEl = h("div", { class: "drop-files" });
    const zone = h("div", { class: "drop", tabindex: "0", role: "button" },
      h("div", { class: "drop-title" }, title || (multiple ? "Trageți fișierele aici" : "Trageți fișierul PDF aici")),
      h("div", { class: "drop-sub" }, sub || "sau faceți clic pentru a alege"),
      filesEl, input);
    host.append(zone);
    const state = { files: [] };

    function set(list) {
      let arr = Array.from(list || []);
      if (validate) {
        const bad = arr.filter((f) => !validate(f));
        if (bad.length) toast("Tip de fișier neacceptat: " + bad.map((f) => f.name).join(", "), "warn");
        arr = arr.filter(validate);
      }
      if (!multiple) arr = arr.slice(0, 1);
      if (!arr.length && list && list.length) return;
      state.files = arr;
      filesEl.textContent = arr.map((f) => `${f.name} (${fmtSize(f.size)})`).join(", ");
      if (onChange) onChange(arr);
    }

    zone.addEventListener("click", () => input.click());
    zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    input.addEventListener("click", (e) => e.stopPropagation());
    input.addEventListener("change", () => { set(input.files); input.value = ""; });
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("over"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("over");
      set(e.dataTransfer.files);
    });

    return {
      get file() { return state.files[0] || null; },
      get files() { return state.files.slice(); },
      set,
      clear() { state.files = []; filesEl.textContent = ""; },
    };
  }

  // ---------------------------------------------------------------- PDF info / randare (cu cache)
  const infoCache = new WeakMap();
  function pdfInfo(blob) {
    if (!infoCache.has(blob)) {
      const p = api("/api/pdf/info", { body: fd({ file: blob }) });
      p.catch(() => infoCache.delete(blob));
      infoCache.set(blob, p);
    }
    return infoCache.get(blob);
  }

  const renderCache = new WeakMap();
  function renderPage(blob, page, zoom) {
    let m = renderCache.get(blob);
    if (!m) { m = new Map(); renderCache.set(blob, m); }
    const key = page + "@" + zoom;
    if (!m.has(key)) {
      const p = api("/api/pdf/render", { body: fd({ file: blob, page, zoom }), as: "blob" })
        .then((r) => URL.createObjectURL(r.blob));
      p.catch(() => m.delete(key));
      m.set(key, p);
    }
    return m.get(key);
  }

  /**
   * Previzualizare pagină cu suprapunere pentru selecție (dreptunghi sau punct).
   * Coordonatele sunt raportate ca fracțiuni din pagină (0..1), origine stânga-sus.
   */
  function pageView(stage) {
    const img = h("img", { alt: "Pagină" });
    const overlay = h("div", { class: "page-overlay tool-none" });
    const marks = h("div");
    const wrap = h("div", { class: "page-wrap" }, img, marks, overlay);
    let mode = "none";
    let onRect = null, onPoint = null, onCancel = null;
    let sel = null;
    let drag = null;
    let token = 0;

    function frac(e) {
      const r = overlay.getBoundingClientRect();
      return {
        x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
        y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
      };
    }
    function place(el, x0, y0, x1, y1) {
      Object.assign(el.style, {
        left: Math.min(x0, x1) * 100 + "%", top: Math.min(y0, y1) * 100 + "%",
        width: Math.abs(x1 - x0) * 100 + "%", height: Math.abs(y1 - y0) * 100 + "%",
      });
    }

    overlay.addEventListener("pointerdown", (e) => {
      if (mode === "none" || e.button !== 0) return;
      e.preventDefault();
      const p = frac(e);
      if (mode === "point") { if (onPoint) onPoint(p.x, p.y); return; }
      overlay.setPointerCapture(e.pointerId);
      if (!sel) { sel = h("div", { class: "sel-rect" }); wrap.append(sel); }
      sel.hidden = false;
      drag = { x0: p.x, y0: p.y };
      place(sel, p.x, p.y, p.x, p.y);
    });
    overlay.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const p = frac(e);
      place(sel, drag.x0, drag.y0, p.x, p.y);
    });
    const end = (e) => {
      if (!drag) return;
      const p = frac(e);
      const r = [Math.min(drag.x0, p.x), Math.min(drag.y0, p.y), Math.max(drag.x0, p.x), Math.max(drag.y0, p.y)];
      drag = null;
      if (r[2] - r[0] < 0.005 || r[3] - r[1] < 0.004) { sel.hidden = true; if (onCancel) onCancel(); return; }
      if (onRect) onRect(r, sel);
    };
    overlay.addEventListener("pointerup", end);
    overlay.addEventListener("pointercancel", () => { drag = null; });

    stage.replaceChildren(wrap);

    const view = {
      wrap,
      async load(blob, page, zoom) {
        const my = ++token;
        stage.classList.add("is-loading");
        try {
          const url = await renderPage(blob, page, zoom);
          if (my !== token) return;
          await new Promise((res) => { img.onload = res; img.onerror = res; img.src = url; });
        } finally {
          if (my === token) stage.classList.remove("is-loading");
        }
      },
      setMode(m, handlers = {}) {
        mode = m;
        onRect = handlers.onRect || null;
        onPoint = handlers.onPoint || null;
        onCancel = handlers.onCancel || null;
        overlay.className = "page-overlay" + (m === "none" ? " tool-none" : "");
        if (sel) sel.hidden = true;
      },
      /** Afișează un dreptunghi persistent (ex. poziția semnăturii). */
      showSel(r, cls) {
        if (!sel) { sel = h("div", { class: "sel-rect" }); wrap.append(sel); }
        sel.className = "sel-rect " + (cls || "");
        sel.hidden = !r;
        if (r) place(sel, r[0], r[1], r[2], r[3]);
      },
      hideSel() { if (sel) sel.hidden = true; },
      setMarks(list) {
        marks.replaceChildren(...list.map((m) => {
          const el = h("div", { class: "op-mark " + (m.cls || "") }, m.label ? h("span", { class: "lbl" }, m.label) : null);
          if (m.rect) place(el, ...m.rect);
          else { el.classList.add("pt"); el.style.left = m.x * 100 + "%"; el.style.top = m.y * 100 + "%"; }
          return el;
        }));
      },
    };
    return view;
  }

  // =================================================================== navigare
  const sectionInit = {};
  const sectionDone = new Set();

  function showSection(name) {
    if (!$(`.section[data-section="${name}"]`)) name = "semnare";
    $$(".section").forEach((s) => { s.hidden = s.dataset.section !== name; });
    $$(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.section === name));
    $("#sidebar").classList.remove("open");
    if (sectionInit[name] && !sectionDone.has(name)) {
      sectionDone.add(name);
      try { sectionInit[name](); } catch (e) { console.error(e); toast(e.message, "err"); }
    } else if (sectionInit[name + ":show"]) {
      sectionInit[name + ":show"]();
    }
  }

  // =================================================================== formular semnare (reutilizabil)
  let pkcs11LibsPromise = null;
  function loadPkcs11Libs() {
    if (!pkcs11LibsPromise) {
      pkcs11LibsPromise = api("/api/sign/pkcs11-libs").catch((e) => { pkcs11LibsPromise = null; throw e; });
    }
    return pkcs11LibsPromise;
  }

  function currentOs() {
    const p = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || navigator.userAgent;
    if (/win/i.test(p)) return "windows";
    if (/mac|darwin/i.test(p)) return "darwin";
    return "linux";
  }

  /**
   * Creează formularul de semnare în `host`.
   * opts.getPdf: async () => Blob|null – documentul (pentru previzualizarea semnăturii vizibile)
   * opts.showContact: afișează câmpul Contact
   * Returnează { appendTo(formData), pdfChanged(), setPfx(file, password) }.
   */
  function createSignForm(host, { getPdf, showContact = true } = {}) {
    const root = $("#tpl-sign-form").content.firstElementChild.cloneNode(true);
    host.append(root);
    const r = (role) => $(`[data-role="${role}"]`, root);
    let method = "pkcs11";
    let certs = [];
    let visInfo = null;
    let visPdf = null;
    let visRect = null; // fracțiuni [x0,y0,x1,y1] stânga-sus
    let visPage = 0;

    if (!showContact) r("contact-wrap").hidden = true;

    // --- tab-uri metodă
    $$(".tab", r("method-tabs")).forEach((t) => t.addEventListener("click", () => {
      method = t.dataset.method;
      $$(".tab", root).forEach((x) => x.classList.toggle("active", x === t));
      $$(".method-pane", root).forEach((p) => { p.hidden = p.dataset.method !== method; });
      try { localStorage.setItem("pdfstudio.signMethod", method); } catch (_) { /* ignorăm */ }
    }));
    try {
      const saved = localStorage.getItem("pdfstudio.signMethod");
      const tab = saved && $(`.tab[data-method="${saved}"]`, root);
      if (tab) tab.click();
    } catch (_) { /* ignorăm */ }

    // --- PKCS#11
    const libSel = r("lib-select");
    libSel.append(h("option", { value: "" }, "Se încarcă…"));
    loadPkcs11Libs().then((data) => {
      libSel.replaceChildren();
      const detected = data.detected || [];
      const known = (data.known && data.known[currentOs()]) || [];
      if (detected.length) {
        libSel.append(h("optgroup", { label: "Detectate pe acest calculator" },
          detected.map((p) => h("option", { value: p }, p))));
      } else {
        libSel.append(h("option", { value: "" }, "— nicio bibliotecă detectată; introduceți calea —"));
      }
      const rest = known.filter((p) => !detected.includes(p));
      if (rest.length) {
        libSel.append(h("optgroup", { label: "Căi cunoscute (neinstalate)" },
          rest.map((p) => h("option", { value: p }, p))));
      }
    }).catch((e) => {
      libSel.replaceChildren(h("option", { value: "" }, "— eroare la detectare —"));
      console.warn(e);
    });
    const libPath = () => r("lib-custom").value.trim() || libSel.value;

    r("find-tokens").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      const lib = libPath();
      if (!lib) throw new Error("Alegeți sau introduceți calea bibliotecii PKCS#11.");
      const tokens = await api("/api/sign/tokens", { body: fd({ lib_path: lib }) });
      const sel = r("token-select");
      sel.replaceChildren();
      if (!tokens.length) {
        sel.append(h("option", { value: "" }, "— niciun token găsit —"));
        toast("Nu a fost găsit niciun token. Verificați că este conectat.", "warn");
        return;
      }
      tokens.forEach((t) => sel.append(h("option", { value: t.label },
        `${t.label}${t.manufacturer ? " – " + t.manufacturer : ""}${t.serial ? " (SN " + t.serial + ")" : ""}`)));
      toast(`${tokens.length} token(uri) găsit(e).`, "ok");
    }));

    r("load-certs").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      const lib = libPath();
      const token = r("token-select").value;
      if (!lib) throw new Error("Alegeți biblioteca PKCS#11.");
      if (!token) throw new Error("Căutați și selectați un token.");
      if (!r("pin11").value) throw new Error("Introduceți PIN-ul token-ului.");
      certs = await api("/api/sign/token-certs", { body: fd({ lib_path: lib, token_label: token, pin: r("pin11").value }) });
      const sel = r("cert-select");
      sel.replaceChildren(h("option", { value: "" }, "— implicit (primul certificat) —"));
      certs.forEach((c, i) => sel.append(h("option", { value: String(i) },
        `${c.subject || c.label}${c.email ? " <" + c.email + ">" : ""} – emis de ${c.issuer || "?"}, valabil până la ${fmtDate(c.not_after)}`)));
      if (certs.length) sel.value = "0";
      toast(certs.length ? `${certs.length} certificat(e) încărcat(e).` : "Token-ul nu conține certificate.", certs.length ? "ok" : "warn");
    }));

    // --- semnătură vizibilă
    const visStage = r("vis-stage");
    const view = pageView(visStage);
    view.setMode("rect", {
      onRect: (rect) => { visRect = rect; view.showSel(rect, "sig-rect"); },
      onCancel: () => view.showSel(visRect, "sig-rect"),
    });

    async function showVisible() {
      const pdf = await getPdf();
      if (!pdf) {
        r("visible").checked = false;
        r("visible-pane").hidden = true;
        throw new Error("Selectați întâi documentul PDF pentru a poziționa semnătura.");
      }
      if (pdf !== visPdf) {
        visPdf = pdf;
        visInfo = null;
        visStage.prepend(h("div", { class: "loading" }, h("span", { class: "spinner" }), "Se încarcă pagina…"));
        visInfo = await pdfInfo(pdf);
        const sel = r("vis-page");
        sel.replaceChildren(...Array.from({ length: visInfo.pages }, (_, i) => h("option", { value: String(i) }, String(i + 1))));
        // implicit: ultima pagină
        visPage = Math.max(0, visInfo.pages - 1);
        sel.value = String(visPage);
        visRect = defaultRect(visPage);
      }
      await loadVisPage();
    }
    function defaultRect(page) {
      const [W, H] = visInfo.page_sizes[page] || [595, 842];
      const w = 200, hh = 70, m = 40;
      return [(W - m - w) / W, (H - m - hh) / H, (W - m) / W, (H - m) / H];
    }
    async function loadVisPage() {
      $$(".loading", visStage).forEach((x) => x.remove());
      const [W] = visInfo.page_sizes[visPage] || [595];
      await view.load(visPdf, visPage, Math.min(2, Math.max(0.6, 900 / W)));
      view.showSel(visRect, "sig-rect");
    }
    r("vis-page").addEventListener("change", () => {
      visPage = Number(r("vis-page").value);
      visRect = defaultRect(visPage);
      loadVisPage().catch((e) => toast(e.message, "err"));
    });
    r("visible").addEventListener("change", () => {
      const on = r("visible").checked;
      r("visible-pane").hidden = !on;
      if (on) showVisible().catch((e) => toast(e.message, "err"));
    });

    return {
      root,
      /** Adaugă câmpurile formularului în FormData; aruncă Error dacă lipsesc date. */
      appendTo(f) {
        f.append("method", method);
        if (method === "pkcs11") {
          const lib = libPath();
          if (!lib) throw new Error("Alegeți biblioteca PKCS#11 a token-ului.");
          if (!r("token-select").value) throw new Error("Căutați și selectați token-ul.");
          if (!r("pin11").value) throw new Error("Introduceți PIN-ul token-ului.");
          f.append("lib_path", lib);
          f.append("token_label", r("token-select").value);
          f.append("pin", r("pin11").value);
          const c = certs[Number(r("cert-select").value)];
          if (r("cert-select").value !== "" && c) {
            if (c.label) f.append("cert_label", c.label);
            if (c.key_id) f.append("key_id", c.key_id);
          }
        } else if (method === "pkcs12") {
          const file = r("pfx").files[0];
          if (!file) throw new Error("Selectați fișierul certificatului (.pfx / .p12).");
          f.append("pfx", file, file.name);
          f.append("password", r("pfx-pass").value);
        } else {
          const url = r("csc-url").value.trim();
          if (!url) throw new Error("Introduceți adresa serviciului de semnare în cloud.");
          if (!r("csc-token").value.trim()) throw new Error("Introduceți token-ul de acces.");
          if (!r("csc-cred").value.trim()) throw new Error("Introduceți ID-ul credențialului.");
          f.append("service_url", url);
          f.append("access_token", r("csc-token").value.trim());
          f.append("credential_id", r("csc-cred").value.trim());
          if (r("csc-pin").value) f.append("pin", r("csc-pin").value);
          if (r("csc-otp").value.trim()) f.append("otp", r("csc-otp").value.trim());
        }
        for (const [role, key] of [["reason", "reason"], ["location", "location"], ["tsa", "timestamp_url"]]) {
          const v = r(role).value.trim();
          if (v) f.append(key, v);
        }
        if (showContact && r("contact").value.trim()) f.append("contact", r("contact").value.trim());
        if (r("visible").checked) {
          if (!visInfo || !visRect) throw new Error("Previzualizarea paginii nu s-a încărcat încă; poziționați semnătura.");
          const [W, H] = visInfo.page_sizes[visPage];
          const [x0, y0, x1, y1] = visRect;
          // conversie în puncte PDF, origine stânga-jos
          f.append("visible", "1");
          f.append("page", String(visPage));
          f.append("x", (x0 * W).toFixed(2));
          f.append("y", ((1 - y1) * H).toFixed(2));
          f.append("w", ((x1 - x0) * W).toFixed(2));
          f.append("h", ((y1 - y0) * H).toFixed(2));
        }
      },
      /** Documentul s-a schimbat – reîncarcă previzualizarea dacă e deschisă. */
      pdfChanged() {
        visPdf = null;
        if (r("visible").checked) showVisible().catch((e) => toast(e.message, "err"));
      },
      setPfx(file, password) {
        try {
          const dt = new DataTransfer();
          dt.items.add(file);
          r("pfx").files = dt.files;
        } catch (_) { return false; }
        r("pfx-pass").value = password;
        $(`.tab[data-method="pkcs12"]`, root).click();
        return true;
      },
    };
  }

  // =================================================================== 1. SEMNARE
  let mainSignForm = null;
  sectionInit.semnare = () => {
    const drop = dropZone($("#sign-drop"), {
      validate: isPdf,
      onChange: () => mainSignForm && mainSignForm.pdfChanged(),
    });
    mainSignForm = createSignForm($("#sign-form-host"), { getPdf: async () => drop.file });

    $("#sign-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!drop.file) throw new Error("Selectați documentul PDF de semnat.");
      const f = fd({ file: drop.file });
      mainSignForm.appendTo(f);
      const { blob, filename } = await api("/api/sign", { body: f, as: "blob" });
      saveBlob(blob, filename || "document_semnat.pdf");
      toast("Documentul a fost semnat și descărcat.", "ok");
    }));

    // certificat de test
    const dlg = $("#testcert-dialog");
    $("#testcert-link").addEventListener("click", (e) => {
      e.preventDefault();
      if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    });
    $("#testcert-form").addEventListener("submit", (e) => {
      const submitter = e.submitter;
      if (!submitter || submitter.value !== "ok") return;
      e.preventDefault();
      const form = e.currentTarget;
      busy($("#testcert-go"), async () => {
        const data = Object.fromEntries(new FormData(form));
        const { blob, filename } = await api("/api/sign/test-certificate", { body: fd(data), as: "blob" });
        const name = filename || "certificat_test.pfx";
        saveBlob(blob, name);
        const file = new File([blob], name, { type: "application/x-pkcs12" });
        if (mainSignForm.setPfx(file, data.password)) {
          toast("Certificatul de test a fost descărcat și selectat în formularul de semnare.", "ok");
        } else {
          toast("Certificatul de test a fost descărcat.", "ok");
        }
        dlg.close();
      });
    });
  };

  // =================================================================== 2. VALIDARE
  sectionInit.validare = () => {
    const drop = dropZone($("#val-drop"), { validate: isPdf });
    const roots = dropZone($("#val-roots-drop"), {
      multiple: true, accept: ".cer,.crt,.pem,.der,.p7b",
      title: "Trageți certificatele rădăcină aici",
    });
    const out = $("#val-results");

    $("#val-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!drop.file) throw new Error("Selectați documentul PDF de validat.");
      const f = fd({ file: drop.file });
      roots.files.forEach((r) => f.append("roots", r, r.name));
      out.replaceChildren(h("div", { class: "loading" }, h("span", { class: "spinner" }), "Se validează semnăturile…"));
      try {
        const sigs = await api("/api/validate", { body: f });
        renderValidation(out, sigs, drop.file.name);
      } catch (err) {
        out.replaceChildren();
        throw err;
      }
    }));
  };

  function sigStatus(s) {
    if (s.intact && s.valid && s.trusted) return ["ok", "Validă și de încredere"];
    if (s.intact && s.valid) return ["warn", "Validă, dar emitentul nu este de încredere"];
    if (s.intact) return ["warn", "Intactă, dar validarea nu este completă"];
    return ["err", "Invalidă – documentul a fost modificat sau semnătura este coruptă"];
  }

  function yesNo(v, yes = "Da", no = "Nu") {
    return h("span", { class: "badge " + (v ? "ok" : "err") }, v ? yes : no);
  }

  function renderValidation(out, sigs, filename) {
    out.replaceChildren();
    if (!sigs || !sigs.length) {
      out.append(h("div", { class: "card empty" }, `Documentul „${filename}” nu conține semnături electronice.`));
      return;
    }
    const okAll = sigs.every((s) => sigStatus(s)[0] === "ok");
    out.append(h("div", { class: "alert " + (okAll ? "ok" : "warn") },
      `${sigs.length} semnătur${sigs.length === 1 ? "ă găsită" : "i găsite"} în „${filename}”.`));
    sigs.forEach((s, i) => {
      const [cls, label] = sigStatus(s);
      const rows = [
        ["Semnatar", s.signer_name], ["E-mail", s.signer_email], ["Data semnării", fmtDate(s.signing_time)],
        ["Marcă temporală", s.timestamp ? fmtDate(s.timestamp) : "Fără"], ["Câmp", s.field],
        ["Acoperire", s.coverage], ["Nivel modificări", s.modification_level],
        ["Subiect certificat", s.cert_subject], ["Emitent certificat", s.cert_issuer],
        ["Certificat valabil până la", fmtDate(s.cert_not_after)],
      ];
      out.append(h("div", { class: "card sig-card " + cls },
        h("div", { class: "sig-head" },
          h("h2", null, `Semnătura ${i + 1}${s.signer_name ? " – " + s.signer_name : ""}`),
          h("span", { class: "badge " + cls }, label)),
        h("div", { class: "flags" },
          h("span", null, "Intactă: "), yesNo(s.intact),
          h("span", null, " Validă: "), yesNo(s.valid),
          h("span", null, " De încredere: "), yesNo(s.trusted)),
        s.summary ? h("p", null, s.summary) : null,
        h("dl", { class: "kv" }, rows.flatMap(([k, v]) => [h("dt", null, k), h("dd", null, v == null || v === "" ? "—" : String(v))])),
        s.errors && s.errors.length
          ? h("div", { class: "alert err mt" }, h("strong", null, "Probleme:"), h("ul", null, s.errors.map((x) => h("li", null, x))))
          : null));
    });
  }

  // =================================================================== 3. CONVERSIE
  sectionInit.conversie = () => {
    api("/api/convert/status").then((st) => {
      const w = $("#conv-warning");
      w.replaceChildren();
      if (!st.soffice) {
        w.append(h("div", { class: "alert warn" },
          h("strong", null, "LibreOffice nu a fost găsit. "),
          "Conversia Word/Office → PDF necesită LibreOffice (soffice) instalat; pe Windows se poate folosi și Microsoft Word, dacă este instalat. ",
          "Descărcați LibreOffice gratuit de pe libreoffice.org și reporniți aplicația."));
      }
    }).catch((e) => toast(e.message, "err"));

    const p2w = dropZone($("#conv-p2w-drop"), { validate: isPdf });
    const officeExt = /\.(docx?|odt|rtf|txt|xlsx?|ods|csv|pptx?|odp)$/i;
    const w2p = dropZone($("#conv-w2p-drop"), {
      accept: ".docx,.doc,.odt,.rtf,.txt,.xlsx,.xls,.ods,.csv,.pptx,.ppt,.odp",
      title: "Trageți documentul Word / Office aici",
      sub: "docx, doc, odt, rtf, txt, xlsx, pptx … – sau faceți clic",
      validate: (f) => officeExt.test(f.name),
    });

    $("#conv-p2w-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!p2w.file) throw new Error("Selectați fișierul PDF.");
      const { blob, filename } = await api("/api/convert/pdf-to-word", { body: fd({ file: p2w.file }), as: "blob" });
      saveBlob(blob, filename || "document.docx");
      toast("Conversie reușită.", "ok");
    }));
    $("#conv-w2p-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!w2p.file) throw new Error("Selectați documentul de convertit.");
      const { blob, filename } = await api("/api/convert/to-pdf", { body: fd({ file: w2p.file }), as: "blob" });
      saveBlob(blob, filename || "document.pdf");
      toast("Conversie reușită.", "ok");
    }));
  };

  // =================================================================== 4. EDITARE
  const ed = {
    blob: null, name: "", info: null, page: 0, zoom: 1.5, tool: null, ops: [], view: null,
    opt: {
      text: "", size: 12, color: "#000000",
      rectColor: "#e11d48", fill: false, fillColor: "#fde68a", width: 1.5,
      note: "", imageB64: null, imageName: "",
      search: "", replace: "", replacePage: false,
      rotateAll: false, moveTo: 1, blankAt: 1,
      meta: null,
    },
  };

  const TOOLS = [
    { id: "add_text", label: "Text", kind: "point" },
    { id: "highlight", label: "Evidențiere", kind: "rect" },
    { id: "rect", label: "Dreptunghi", kind: "rect" },
    { id: "whiteout", label: "Acoperire albă", kind: "rect" },
    { id: "redact", label: "Ștergere definitivă", kind: "rect" },
    { id: "image", label: "Imagine", kind: "rect" },
    { id: "note", label: "Notă", kind: "point" },
    { id: "replace_text", label: "Înlocuire text", kind: "form" },
    { id: "rotate", label: "Rotire pagină", kind: "form" },
    { id: "delete_page", label: "Ștergere pagină", kind: "form" },
    { id: "move_page", label: "Mutare pagină", kind: "form" },
    { id: "insert_blank", label: "Pagină goală", kind: "form" },
    { id: "set_metadata", label: "Metadate", kind: "form" },
  ];

  function pageSize(p) { return (ed.info && ed.info.page_sizes[p]) || [595, 842]; }
  const round = (v) => Math.round(v * 100) / 100;

  function opText(op) {
    const pg = (p) => `pag. ${p + 1}`;
    switch (op.type) {
      case "add_text": return `Text „${op.text.slice(0, 40)}${op.text.length > 40 ? "…" : ""}” (${pg(op.page)})`;
      case "highlight": return `Evidențiere (${pg(op.page)})`;
      case "rect": return `Dreptunghi${op.fill ? " plin" : ""} (${pg(op.page)})`;
      case "whiteout": return `Acoperire albă (${pg(op.page)})`;
      case "redact": return `Ștergere definitivă (${pg(op.page)})`;
      case "image": return `Imagine ${op._name || ""} (${pg(op.page)})`;
      case "note": return `Notă „${op.text.slice(0, 40)}” (${pg(op.page)})`;
      case "replace_text": return `Înlocuire „${op.search}” → „${op.replace}”${op.page != null ? " (" + pg(op.page) + ")" : " (toate paginile)"}`;
      case "rotate": return `Rotire ${op.angle}°${op.page == null ? " (toate paginile)" : " (" + pg(op.page) + ")"}`;
      case "delete_page": return `Ștergere ${pg(op.page)}`;
      case "move_page": return `Mutare pag. ${op.from + 1} → poziția ${op.to + 1}`;
      case "insert_blank": return `Pagină goală la poziția ${op.at + 1}`;
      case "set_metadata": return `Metadate (titlu: ${op.title || "—"})`;
      default: return op.type;
    }
  }

  function addOp(op) {
    ed.ops.push(op);
    renderOps();
    renderMarks();
  }

  function renderOps() {
    const list = $("#ed-ops");
    list.replaceChildren(...ed.ops.map((op, i) => h("li", null,
      h("div", { class: "op-row" },
        h("span", { class: "link", title: "Mergi la pagină", onclick: () => { if (op.page != null && op.page < ed.info.pages) goPage(op.page); } }, opText(op)),
        h("button", { class: "x", title: "Elimină", "aria-label": "Elimină", onclick: () => { ed.ops.splice(i, 1); renderOps(); renderMarks(); } }, "×")))));
    $("#ed-opcount").textContent = String(ed.ops.length);
  }

  function renderMarks() {
    if (!ed.view) return;
    const [W, H] = pageSize(ed.page);
    const marks = [];
    ed.ops.forEach((op, i) => {
      if (op.page !== ed.page) return;
      if (op.rect) {
        marks.push({ rect: [op.rect[0] / W, op.rect[1] / H, op.rect[2] / W, op.rect[3] / H], cls: op.type, label: `${i + 1}` });
      } else if (op.x != null) {
        marks.push({ x: op.x / W, y: op.y / H, label: `${i + 1}. ${op.text.slice(0, 20)}` });
      }
    });
    ed.view.setMarks(marks);
  }

  function setTool(id) {
    ed.tool = ed.tool === id ? null : id;
    $$(".tool", $("#ed-tools")).forEach((b) => b.classList.toggle("active", b.dataset.tool === ed.tool));
    renderToolOptions();
    const t = TOOLS.find((x) => x.id === ed.tool);
    if (!t || t.kind === "form") { ed.view.setMode("none"); return; }
    if (t.kind === "point") ed.view.setMode("point", { onPoint: onEditorPoint });
    else ed.view.setMode("rect", { onRect: onEditorRect });
  }

  function onEditorPoint(fx, fy) {
    const [W, H] = pageSize(ed.page);
    const x = round(fx * W), y = round(fy * H);
    if (ed.tool === "add_text") {
      const text = ed.opt.text.trim() ? ed.opt.text : window.prompt("Textul de adăugat:", "");
      if (!text) return;
      addOp({ type: "add_text", page: ed.page, x, y, text, size: Number(ed.opt.size) || 12, color: ed.opt.color });
    } else if (ed.tool === "note") {
      const text = ed.opt.note.trim() ? ed.opt.note : window.prompt("Textul notei:", "");
      if (!text) return;
      addOp({ type: "note", page: ed.page, x, y, text });
    }
  }

  function onEditorRect(fr, sel) {
    const [W, H] = pageSize(ed.page);
    const rect = [round(fr[0] * W), round(fr[1] * H), round(fr[2] * W), round(fr[3] * H)];
    if (sel) sel.hidden = true;
    switch (ed.tool) {
      case "highlight": addOp({ type: "highlight", page: ed.page, rect }); break;
      case "rect": addOp({ type: "rect", page: ed.page, rect, color: ed.opt.rectColor, fill: ed.opt.fill ? ed.opt.fillColor : null, width: Number(ed.opt.width) || 1 }); break;
      case "whiteout": addOp({ type: "whiteout", page: ed.page, rect }); break;
      case "redact": addOp({ type: "redact", page: ed.page, rect }); break;
      case "image":
        if (!ed.opt.imageB64) { toast("Alegeți întâi imaginea din bara de opțiuni.", "warn"); return; }
        addOp({ type: "image", page: ed.page, rect, image_b64: ed.opt.imageB64, _name: ed.opt.imageName });
        break;
      default: break;
    }
  }

  function optField(label, input) { return h("label", { class: "field" }, label, input); }
  function bindOpt(input, key, conv = (v) => v) {
    const isCheck = input.type === "checkbox";
    if (isCheck) input.checked = !!ed.opt[key]; else input.value = ed.opt[key];
    input.addEventListener(isCheck ? "change" : "input", () => { ed.opt[key] = isCheck ? input.checked : conv(input.value); });
    return input;
  }
  const tip = (t) => h("span", { class: "tip" }, t);

  function renderToolOptions() {
    const box = $("#ed-tool-opts");
    box.replaceChildren();
    const pnum = ed.page + 1;
    switch (ed.tool) {
      case "add_text":
        box.append(
          optField("Text", bindOpt(h("input", { type: "text", placeholder: "Textul de inserat" }), "text")),
          optField("Mărime", bindOpt(h("input", { type: "number", min: "4", max: "200", class: "num" }), "size", Number)),
          optField("Culoare", bindOpt(h("input", { type: "color" }), "color")),
          tip("Faceți clic pe pagină unde începe textul (colțul stânga-sus)."));
        break;
      case "highlight": box.append(tip("Trageți un dreptunghi peste textul de evidențiat.")); break;
      case "rect":
        box.append(
          optField("Contur", bindOpt(h("input", { type: "color" }), "rectColor")),
          optField("Grosime", bindOpt(h("input", { type: "number", min: "0", max: "20", step: "0.5", class: "num" }), "width", Number)),
          h("label", { class: "check" }, bindOpt(h("input", { type: "checkbox" }), "fill"), "Umplere"),
          optField("Culoare umplere", bindOpt(h("input", { type: "color" }), "fillColor")),
          tip("Trageți pe pagină pentru a desena."));
        break;
      case "whiteout": box.append(tip("Trageți un dreptunghi: zona va fi acoperită cu alb (conținutul rămâne în fișier, sub acoperire).")); break;
      case "redact": box.append(tip("Trageți un dreptunghi: textul și imaginile din zonă vor fi eliminate definitiv din document.")); break;
      case "image": {
        const inp = h("input", { type: "file", accept: "image/png,image/jpeg,image/gif,image/bmp,image/webp" });
        inp.addEventListener("change", async () => {
          const f = inp.files[0];
          if (!f) return;
          try {
            ed.opt.imageB64 = await fileToBase64(f);
            ed.opt.imageName = f.name;
            toast("Imagine pregătită. Trageți pe pagină zona în care va fi plasată.", "ok");
          } catch (e) { toast(e.message, "err"); }
        });
        box.append(optField("Imagine (PNG/JPG)", inp),
          tip(ed.opt.imageName ? `Imagine curentă: ${ed.opt.imageName}. Trageți pe pagină zona dorită.` : "Alegeți imaginea, apoi trageți pe pagină zona dorită."));
        break;
      }
      case "note":
        box.append(optField("Textul notei", bindOpt(h("input", { type: "text", placeholder: "Comentariu" }), "note")),
          tip("Faceți clic pe pagină pentru a plasa nota."));
        break;
      case "replace_text": {
        const s = bindOpt(h("input", { type: "text", placeholder: "Text căutat" }), "search");
        const r = bindOpt(h("input", { type: "text", placeholder: "Text nou" }), "replace");
        box.append(optField("Caută", s), optField("Înlocuiește cu", r),
          h("label", { class: "check" }, bindOpt(h("input", { type: "checkbox" }), "replacePage"), `Doar pagina curentă (${pnum})`),
          h("button", { class: "btn small primary", onclick: () => {
            if (!ed.opt.search) { toast("Introduceți textul căutat.", "warn"); return; }
            addOp({ type: "replace_text", search: ed.opt.search, replace: ed.opt.replace, page: ed.opt.replacePage ? ed.page : null });
          } }, "Adaugă"));
        break;
      }
      case "rotate": {
        const rot = (angle) => addOp({ type: "rotate", page: ed.opt.rotateAll ? null : ed.page, angle });
        box.append(
          h("label", { class: "check" }, bindOpt(h("input", { type: "checkbox" }), "rotateAll"), "Toate paginile"),
          h("button", { class: "btn small", onclick: () => rot(90) }, "↻ 90° dreapta"),
          h("button", { class: "btn small", onclick: () => rot(270) }, "↺ 90° stânga"),
          h("button", { class: "btn small", onclick: () => rot(180) }, "180°"),
          tip(`Se aplică paginii ${pnum} dacă nu este bifat „Toate paginile”.`));
        break;
      }
      case "delete_page":
        box.append(h("button", { class: "btn small danger", onclick: () => {
          if (ed.info.pages <= 1) { toast("Documentul are o singură pagină.", "warn"); return; }
          addOp({ type: "delete_page", page: ed.page });
        } }, `Șterge pagina ${pnum}`), tip("Navigați la pagina dorită, apoi apăsați butonul."));
        break;
      case "move_page": {
        ed.opt.moveTo = Math.min(ed.opt.moveTo, ed.info.pages);
        const inp = bindOpt(h("input", { type: "number", min: "1", max: String(ed.info.pages), class: "num" }), "moveTo", Number);
        box.append(optField(`Mută pagina ${pnum} pe poziția`, inp),
          h("button", { class: "btn small primary", onclick: () => {
            const to = Math.round(ed.opt.moveTo) - 1;
            if (!(to >= 0 && to < ed.info.pages)) { toast(`Poziția trebuie să fie între 1 și ${ed.info.pages}.`, "warn"); return; }
            if (to === ed.page) { toast("Pagina se află deja pe această poziție.", "warn"); return; }
            addOp({ type: "move_page", from: ed.page, to });
          } }, "Adaugă"));
        break;
      }
      case "insert_blank": {
        ed.opt.blankAt = ed.page + 2;
        const inp = bindOpt(h("input", { type: "number", min: "1", max: String(ed.info.pages + 1), class: "num" }), "blankAt", Number);
        box.append(optField("Inserează pagină goală pe poziția", inp),
          h("button", { class: "btn small primary", onclick: () => {
            const at = Math.round(ed.opt.blankAt) - 1;
            if (!(at >= 0 && at <= ed.info.pages)) { toast(`Poziția trebuie să fie între 1 și ${ed.info.pages + 1}.`, "warn"); return; }
            addOp({ type: "insert_blank", at });
          } }, "Adaugă"), tip(`Implicit: după pagina curentă (${pnum}).`));
        break;
      }
      case "set_metadata": {
        const md = (ed.info && ed.info.metadata) || {};
        const fields = {};
        const mk = (key, label) => { fields[key] = h("input", { type: "text", value: md[key] || "" }); return optField(label, fields[key]); };
        box.append(mk("title", "Titlu"), mk("author", "Autor"), mk("subject", "Subiect"), mk("keywords", "Cuvinte cheie"),
          h("button", { class: "btn small primary", onclick: () => {
            const op = { type: "set_metadata" };
            for (const k of Object.keys(fields)) op[k] = fields[k].value;
            addOp(op);
          } }, "Adaugă"));
        break;
      }
      default:
        box.append(tip("Alegeți un instrument de mai sus. Pentru text, note și forme faceți clic sau trageți pe pagină."));
    }
  }

  async function goPage(p) {
    if (!ed.info) return;
    ed.page = Math.max(0, Math.min(ed.info.pages - 1, p));
    $("#ed-pagenum").value = String(ed.page + 1);
    $$(".thumb", $("#ed-thumbs")).forEach((t, i) => t.classList.toggle("active", i === ed.page));
    const active = $(".thumb.active", $("#ed-thumbs"));
    if (active) active.scrollIntoView({ block: "nearest" });
    renderMarks();
    if (TOOLS.find((t) => t.id === ed.tool && t.kind === "form")) renderToolOptions();
    try {
      await ed.view.load(ed.blob, ed.page, ed.zoom);
    } catch (e) { toast(e.message, "err"); }
  }

  let thumbObserver = null;
  function renderThumbs() {
    const box = $("#ed-thumbs");
    if (thumbObserver) thumbObserver.disconnect();
    const blob = ed.blob;
    const queue = [];
    let running = 0;
    const pump = () => {
      while (running < 2 && queue.length) {
        const { img, i } = queue.shift();
        running++;
        renderPage(blob, i, 0.25).then((url) => { img.src = url; }).catch(() => { /* ignorăm */ })
          .finally(() => { running--; pump(); });
      }
    };
    thumbObserver = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (!en.isIntersecting) return;
        thumbObserver.unobserve(en.target);
        if (blob !== ed.blob) return;
        queue.push({ img: $("img", en.target), i: Number(en.target.dataset.i) });
      });
      pump();
    }, { root: box, rootMargin: "300px" });
    box.replaceChildren(...Array.from({ length: ed.info.pages }, (_, i) => {
      const t = h("div", { class: "thumb" + (i === ed.page ? " active" : ""), "data-i": String(i), onclick: () => goPage(i) },
        h("div", { class: "ti" }, h("img", { alt: `Pagina ${i + 1}` })), String(i + 1));
      thumbObserver.observe(t);
      return t;
    }));
  }

  async function loadEditorDoc(blob, name, keepPage = false) {
    const info = await pdfInfo(blob);
    ed.blob = blob;
    ed.name = name;
    ed.info = info;
    ed.ops = [];
    if (!keepPage) ed.page = 0;
    ed.page = Math.min(ed.page, info.pages - 1);
    $("#ed-load-card").hidden = true;
    $("#ed-workspace").hidden = false;
    $("#ed-filename").textContent = name;
    $("#ed-pages").textContent = `· ${info.pages} pagin${info.pages === 1 ? "ă" : "i"}${info.encrypted ? " · criptat" : ""}`;
    $("#ed-pagecount").textContent = String(info.pages);
    $("#ed-pagenum").max = String(info.pages);
    const warn = $("#ed-sigwarn");
    warn.replaceChildren();
    if (info.signature_count > 0) {
      warn.append(h("div", { class: "alert warn" },
        h("strong", null, `Documentul conține ${info.signature_count} semnătur${info.signature_count === 1 ? "ă" : "i"} electronic${info.signature_count === 1 ? "ă" : "e"}. `),
        "Orice modificare va invalida semnăturile existente. Pentru a adăuga o semnătură nouă folosiți secțiunea „Semnare”."));
    }
    renderOps();
    renderThumbs();
    renderToolOptions();
    await goPage(ed.page);
  }

  async function applyEdits(download) {
    if (!ed.ops.length) throw new Error("Nu există operații de aplicat.");
    const ops = ed.ops.map((op) => {
      const o = { ...op };
      delete o._name;
      return o;
    });
    const { blob, filename } = await api("/api/pdf/edit", { body: fd({ file: ed.blob, ops: JSON.stringify(ops) }), as: "blob" });
    if (download) saveBlob(blob, filename || "document_editat.pdf");
    const file = new File([blob], ed.name, { type: "application/pdf" });
    await loadEditorDoc(file, ed.name, true);
    toast(download ? "Modificările au fost aplicate și documentul descărcat." : "Modificările au fost aplicate. Puteți continua editarea.", "ok");
  }

  sectionInit.editare = () => {
    // sub-tab-uri
    $$("#ed-subtabs .subtab").forEach((b) => b.addEventListener("click", () => {
      $$("#ed-subtabs .subtab").forEach((x) => x.classList.toggle("active", x === b));
      $$("#sec-editare .subpane").forEach((p) => { p.hidden = p.dataset.sub !== b.dataset.sub; });
    }));

    ed.view = pageView($("#ed-stage"));
    $("#ed-tools").append(...TOOLS.map((t) => h("button", { class: "tool", "data-tool": t.id, onclick: () => setTool(t.id) }, t.label)));

    dropZone($("#ed-drop"), {
      validate: isPdf, title: "Trageți aici PDF-ul de editat",
      onChange: (files) => {
        if (!files[0]) return;
        const zone = $("#ed-drop .drop");
        zone.classList.add("over");
        loadEditorDoc(files[0], files[0].name).catch((e) => toast(e.message, "err")).finally(() => zone.classList.remove("over"));
      },
    });

    $("#ed-prev").addEventListener("click", () => goPage(ed.page - 1));
    $("#ed-next").addEventListener("click", () => goPage(ed.page + 1));
    $("#ed-pagenum").addEventListener("change", (e) => goPage(Number(e.target.value) - 1));
    $("#ed-zoom").addEventListener("change", (e) => { ed.zoom = Number(e.target.value); goPage(ed.page); });
    $("#ed-clear-ops").addEventListener("click", () => { ed.ops = []; renderOps(); renderMarks(); });
    $("#ed-apply").addEventListener("click", (e) => busy(e.currentTarget, () => applyEdits(false)));
    $("#ed-apply-dl").addEventListener("click", (e) => busy(e.currentTarget, () => applyEdits(true)));
    $("#ed-close").addEventListener("click", () => {
      if (ed.ops.length && !window.confirm("Aveți operații neaplicate. Închideți documentul?")) return;
      ed.blob = null; ed.info = null; ed.ops = [];
      $("#ed-workspace").hidden = true;
      $("#ed-load-card").hidden = false;
    });
    document.addEventListener("keydown", (e) => {
      if ($("#sec-editare").hidden || !ed.info || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") goPage(ed.page + 1);
      if (e.key === "ArrowLeft" || e.key === "PageUp") goPage(ed.page - 1);
      if (e.key === "Escape" && ed.tool) setTool(ed.tool);
    });

    initMerge();
    initSplit();
    initCompress();
    initText();
  };

  function initMerge() {
    const files = [];
    const list = $("#merge-list");
    const render = () => {
      list.replaceChildren(...files.map((f, i) => h("li", null,
        h("strong", null, `${i + 1}.`), h("span", { class: "fn" }, `${f.name} (${fmtSize(f.size)})`),
        h("button", { class: "btn small", disabled: i === 0, title: "Mută în sus", onclick: () => { [files[i - 1], files[i]] = [files[i], files[i - 1]]; render(); } }, "↑"),
        h("button", { class: "btn small", disabled: i === files.length - 1, title: "Mută în jos", onclick: () => { [files[i + 1], files[i]] = [files[i], files[i + 1]]; render(); } }, "↓"),
        h("button", { class: "btn small danger", title: "Elimină", onclick: () => { files.splice(i, 1); render(); } }, "×"))));
    };
    const dz = dropZone($("#merge-drop"), {
      multiple: true, validate: isPdf, title: "Trageți PDF-urile aici",
      onChange: (arr) => { files.push(...arr); render(); dz.clear(); },
    });
    $("#merge-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (files.length < 2) throw new Error("Adăugați cel puțin două fișiere PDF.");
      const f = new FormData();
      files.forEach((x) => f.append("files", x, x.name));
      const { blob, filename } = await api("/api/pdf/merge", { body: f, as: "blob" });
      saveBlob(blob, filename || "combinat.pdf");
      toast("Fișierele au fost combinate.", "ok");
    }));
  }

  function initSplit() {
    const dz = dropZone($("#split-drop"), { validate: isPdf });
    $("#split-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!dz.file) throw new Error("Selectați fișierul PDF.");
      const ranges = $("#split-ranges").value.trim();
      if (!ranges) throw new Error("Introduceți intervalele de pagini, de ex. 1-3,4,5-end.");
      const { blob, filename } = await api("/api/pdf/split", { body: fd({ file: dz.file, ranges }), as: "blob" });
      saveBlob(blob, filename || "impartit.zip");
      toast("Documentul a fost împărțit (arhivă ZIP).", "ok");
    }));
  }

  function initCompress() {
    const dz = dropZone($("#compress-drop"), { validate: isPdf });
    $("#compress-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!dz.file) throw new Error("Selectați fișierul PDF.");
      const { blob, filename } = await api("/api/pdf/compress", { body: fd({ file: dz.file }), as: "blob" });
      saveBlob(blob, filename || "comprimat.pdf");
      const before = dz.file.size, after = blob.size;
      const pct = before ? Math.round((1 - after / before) * 100) : 0;
      $("#compress-result").replaceChildren(h("div", { class: "alert " + (pct > 0 ? "ok" : "warn") + " mt" },
        `Dimensiune: ${fmtSize(before)} → ${fmtSize(after)}` + (pct > 0 ? ` (−${pct}%)` : " (documentul era deja optimizat)")));
    }));
  }

  function initText() {
    const dz = dropZone($("#text-drop"), { validate: isPdf });
    const out = $("#text-out");
    $("#text-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!dz.file) throw new Error("Selectați fișierul PDF.");
      const res = await api("/api/pdf/text", { body: fd({ file: dz.file }) });
      out.value = res.text || "";
      $("#text-copy").disabled = $("#text-save").disabled = !out.value;
      if (!out.value.trim()) toast("Documentul nu conține text extractibil (posibil scanat).", "warn");
    }));
    $("#text-copy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(out.value); toast("Text copiat.", "ok"); }
      catch (_) { out.select(); document.execCommand("copy"); toast("Text copiat.", "ok"); }
    });
    $("#text-save").addEventListener("click", () => {
      const stem = (dz.file && dz.file.name.replace(/\.pdf$/i, "")) || "text";
      saveBlob(new Blob([out.value], { type: "text/plain;charset=utf-8" }), stem + ".txt");
    });
  }

  // =================================================================== 5. FLUXURI
  const WF_STATUS = {
    draft: ["Ciornă", ""], in_progress: ["În desfășurare", "info"],
    completed: ["Finalizat", "ok"], cancelled: ["Anulat", "err"],
  };
  const SIGNER_STATUS = {
    pending: ["În așteptare", ""], sent: ["Trimis spre semnare", "info"],
    signed: ["Semnat", "ok"], rejected: ["Respins", "err"],
  };
  const statusBadge = (map, s) => { const [t, c] = map[s] || [s || "?", ""]; return h("span", { class: "badge " + c }, t); };

  let wfSigners = [];
  let wfDetailId = null;

  sectionInit.fluxuri = () => {
    const drop = dropZone($("#wf-drop"), { validate: isPdf, title: "Trageți aici PDF-ul de semnat" });
    const signersEl = $("#wf-signers");

    function renderSigners() {
      signersEl.replaceChildren(...wfSigners.map((s, i) => {
        const name = h("input", { type: "text", placeholder: "Nume", value: s.name });
        const email = h("input", { type: "email", placeholder: "e-mail", value: s.email });
        name.addEventListener("input", () => { s.name = name.value; });
        email.addEventListener("input", () => { s.email = email.value; });
        return h("li", null, name, email,
          h("button", { class: "btn small", type: "button", disabled: i === 0, title: "Mută în sus", onclick: () => { [wfSigners[i - 1], wfSigners[i]] = [wfSigners[i], wfSigners[i - 1]]; renderSigners(); } }, "↑"),
          h("button", { class: "btn small", type: "button", disabled: i === wfSigners.length - 1, title: "Mută în jos", onclick: () => { [wfSigners[i + 1], wfSigners[i]] = [wfSigners[i], wfSigners[i + 1]]; renderSigners(); } }, "↓"),
          h("button", { class: "btn small danger", type: "button", title: "Elimină", onclick: () => { wfSigners.splice(i, 1); renderSigners(); } }, "×"));
      }));
    }
    function resetCreate() {
      wfSigners = [{ name: "", email: "" }];
      $("#wf-name").value = "";
      $("#wf-message").value = "";
      drop.clear();
      renderSigners();
    }
    resetCreate();

    $("#wf-add-signer").addEventListener("click", () => { wfSigners.push({ name: "", email: "" }); renderSigners(); });
    $("#wf-new").addEventListener("click", () => { $("#wf-create").hidden = false; $("#wf-name").focus(); });
    $("#wf-create-cancel").addEventListener("click", () => { $("#wf-create").hidden = true; resetCreate(); });
    $("#wf-refresh").addEventListener("click", (e) => busy(e.currentTarget, loadWorkflows));
    $("#wf-inbox").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      const box = $("#wf-inbox-result");
      const results = await api("/api/workflows/check-inbox", { method: "POST" });
      renderInboxResults(box, results);
      await loadWorkflows();
    }));

    $("#wf-create-btn").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      const name = $("#wf-name").value.trim();
      if (!name) throw new Error("Introduceți denumirea fluxului.");
      if (!drop.file) throw new Error("Selectați documentul PDF.");
      const signers = wfSigners.map((s) => ({ name: s.name.trim(), email: s.email.trim() })).filter((s) => s.email || s.name);
      if (!signers.length) throw new Error("Adăugați cel puțin un semnatar.");
      const bad = signers.find((s) => !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s.email));
      if (bad) throw new Error(`Adresă de e-mail invalidă: „${bad.email || bad.name}”.`);
      const wf = await api("/api/workflows", {
        body: fd({ file: drop.file, name, signers: JSON.stringify(signers), message: $("#wf-message").value, start: $("#wf-start").checked ? "true" : "false" }),
      });
      toast("Fluxul a fost creat" + ($("#wf-start").checked ? " și pornit." : "."), "ok");
      $("#wf-create").hidden = true;
      resetCreate();
      await loadWorkflows();
      openWorkflow(wf.id);
    }));

    loadWorkflows().catch((e) => toast(e.message, "err"));
  };
  sectionInit["fluxuri:show"] = () => {
    if (wfDetailId == null) loadWorkflows().catch((e) => toast(e.message, "err"));
  };

  function renderInboxResults(box, results) {
    box.replaceChildren();
    if (!results || !results.length) {
      box.append(h("div", { class: "alert" }, "Nu există mesaje noi pentru fluxurile de semnare."));
      return;
    }
    box.append(h("div", { class: "card" },
      h("h3", null, `Rezultat verificare inbox (${results.length} mesaj${results.length === 1 ? "" : "e"})`),
      h("ul", { class: "signer-steps" }, results.map((r) => h("li", null,
        h("span", { class: "badge " + (r.ok ? "ok" : "err") }, r.ok ? "Importat" : "Eroare"),
        h("div", null,
          h("div", null, h("strong", null, `Flux #${r.workflow_id}`), ` – ${r.subject || ""}`),
          h("div", { class: "hint" }, `De la: ${r.sender || "?"}${r.filename ? " · " + r.filename : ""}`),
          r.ok && r.report ? h("div", null, r.report.message || "") : null,
          r.ok && r.report && r.report.warnings && r.report.warnings.length
            ? h("ul", { class: "hint" }, r.report.warnings.map((w) => h("li", null, w))) : null,
          r.error ? h("div", { class: "hint", style: { color: "var(--err)" } }, r.error) : null)))),
      h("button", { class: "btn small", onclick: () => box.replaceChildren() }, "Închide")));
  }

  async function loadWorkflows() {
    const box = $("#wf-list");
    const list = await api("/api/workflows");
    if (!list.length) {
      box.replaceChildren(h("div", { class: "card empty" }, "Nu există fluxuri de semnare. Apăsați „Flux nou” pentru a crea unul."));
      return;
    }
    box.replaceChildren(h("div", { class: "card table-wrap", style: { padding: "0" } },
      h("table", { class: "wf-table" },
        h("thead", null, h("tr", null, ["#", "Denumire", "Stare", "Progres", "Semnatar curent", "Actualizat"].map((t) => h("th", null, t)))),
        h("tbody", null, list.map((w) => h("tr", { onclick: () => openWorkflow(w.id) },
          h("td", null, String(w.id)),
          h("td", null, h("strong", null, w.name), h("div", { class: "hint" }, w.filename || "")),
          h("td", null, statusBadge(WF_STATUS, w.status)),
          h("td", null, `${w.signed_count ?? "?"} / ${w.signer_count ?? "?"}`),
          h("td", null, w.status === "in_progress" && w.current_signer ? `${w.current_signer.name || ""} <${w.current_signer.email}>` : "—"),
          h("td", null, fmtDate(w.updated_at || w.created_at))))))));
  }

  function showWfList() {
    wfDetailId = null;
    $("#wf-detail-view").hidden = true;
    $("#wf-list-view").hidden = false;
    loadWorkflows().catch((e) => toast(e.message, "err"));
  }

  async function openWorkflow(id) {
    try {
      const wf = await api(`/api/workflows/${id}`);
      wfDetailId = id;
      renderWorkflowDetail(wf);
      $("#wf-list-view").hidden = true;
      $("#wf-detail-view").hidden = false;
      window.scrollTo(0, 0);
    } catch (e) { toast(e.message, "err"); }
  }

  function renderReport(report) {
    if (!report) return null;
    const warnings = report.warnings || [];
    const errors = report.errors || [];
    return h("div", { class: "alert " + (errors.length ? "err" : warnings.length ? "warn" : "ok") },
      h("strong", null, report.message || (report.ok ? "Operațiune reușită." : "Operațiune eșuată.")),
      report.signature_count != null ? h("div", null, `Semnături în document: ${report.signature_count}`) : null,
      warnings.length ? h("div", null, h("div", null, "Avertismente:"), h("ul", null, warnings.map((w) => h("li", null, w)))) : null,
      errors.length ? h("div", null, h("div", null, "Erori:"), h("ul", null, errors.map((w) => h("li", null, w)))) : null);
  }

  function renderWorkflowDetail(wf, report) {
    const v = $("#wf-detail-view");
    const active = wf.status === "in_progress";
    const reportBox = h("div", null, renderReport(report));
    const refresh = (newWf, rep) => renderWorkflowDetail(newWf, rep);

    let docBlob = null;
    const getDoc = async () => {
      if (!docBlob) {
        const { blob, filename } = await api(`/api/workflows/${wf.id}/document`, { as: "blob" });
        docBlob = new File([blob], filename || wf.filename || "document.pdf", { type: "application/pdf" });
      }
      return docBlob;
    };

    const actBtn = (label, cls, fn) => h("button", { class: "btn " + (cls || ""), onclick: (e) => busy(e.currentTarget, fn) }, label);

    const header = h("div", null,
      h("button", { class: "btn small back", onclick: showWfList }, "‹ Înapoi la listă"),
      h("div", { class: "title-row" },
        h("h1", null, wf.name, " ", statusBadge(WF_STATUS, wf.status)),
        h("div", { class: "row-actions" },
          actBtn("Descarcă documentul curent", "", async () => {
            const { blob, filename } = await api(`/api/workflows/${wf.id}/document`, { as: "blob" });
            saveBlob(blob, filename || wf.filename);
          }),
          wf.status === "draft" ? actBtn("Pornește fluxul", "primary", async () => {
            refresh(await api(`/api/workflows/${wf.id}/start`, { method: "POST" }));
            toast("Fluxul a fost pornit.", "ok");
          }) : null,
          active ? actBtn("Trimite reamintire", "", async () => {
            refresh(await api(`/api/workflows/${wf.id}/remind`, { method: "POST" }));
            toast("Reamintirea a fost trimisă.", "ok");
          }) : null,
          wf.status === "draft" || active ? actBtn("Anulează fluxul", "danger", async () => {
            if (!window.confirm("Sigur anulați acest flux de semnare?")) return;
            refresh(await api(`/api/workflows/${wf.id}/cancel`, { method: "POST" }));
            toast("Fluxul a fost anulat.", "ok");
          }) : null,
          actBtn("Reîmprospătează", "", async () => refresh(await api(`/api/workflows/${wf.id}`))))),
      h("p", { class: "hint" }, `Document: ${wf.filename || ""}` + (wf.tag ? ` · Etichetă e-mail: ${wf.tag}` : "") + (wf.created_at ? ` · Creat: ${fmtDate(wf.created_at)}` : "")),
      wf.message ? h("p", null, h("em", null, wf.message)) : null);

    const signers = h("div", { class: "card" }, h("h2", null, "Semnatari"),
      h("ol", { class: "signer-steps" }, (wf.signers || []).map((s, i) => h("li", { class: active && i === wf.current_step ? "current" : "" },
        h("span", { class: "step-num" }, String(i + 1)),
        h("div", { style: { flex: "1" } },
          h("div", null, s.name || s.email, s.name ? h("span", { class: "muted" }, ` <${s.email}>`) : null),
          h("div", { class: "hint" }, [s.sent_at ? `Trimis: ${fmtDate(s.sent_at)}` : null, s.signed_at ? `Semnat: ${fmtDate(s.signed_at)}` : null].filter(Boolean).join(" · "))),
        active && i === wf.current_step ? h("span", { class: "badge warn" }, "Pasul curent") : null,
        statusBadge(SIGNER_STATUS, s.status)))));

    const blocks = [header, reportBox, signers];

    if (active) {
      // încărcare manuală
      const upCard = h("div", { class: "card" }, h("h2", null, "Încarcă documentul semnat"),
        h("p", { class: "hint" }, "Dacă semnatarul curent v-a trimis PDF-ul semnat pe altă cale, încărcați-l aici. Va fi validat și trimis mai departe."));
      const upHost = h("div");
      upCard.append(upHost);
      const up = dropZone(upHost, { validate: isPdf, title: "Trageți aici PDF-ul semnat" });
      upCard.append(h("div", { class: "actions" }, actBtn("Încarcă și validează", "primary", async () => {
        if (!up.file) throw new Error("Selectați PDF-ul semnat.");
        const res = await api(`/api/workflows/${wf.id}/submit`, { body: fd({ file: up.file }) });
        refresh(res.workflow, res.report);
        toast(res.report && res.report.message ? res.report.message : "Document acceptat.", "ok");
      })));

      // semnez eu acum
      const cur = (wf.signers || [])[wf.current_step];
      const signCard = h("div", { class: "card" }, h("h2", null, "Semnez eu acum"),
        h("p", { class: "hint" }, `Dacă dvs. sunteți semnatarul curent${cur ? ` (${cur.name || ""} <${cur.email}>)` : ""}, semnați documentul direct din aplicație.`));
      const signHost = h("div");
      signCard.append(signHost);
      const form = createSignForm(signHost, { getPdf: getDoc, showContact: false });
      signCard.append(h("div", { class: "actions" }, actBtn("Semnează și trimite mai departe", "primary", async () => {
        const f = new FormData();
        form.appendTo(f);
        const res = await api(`/api/workflows/${wf.id}/sign-local`, { body: f });
        refresh(res.workflow, res.report);
        toast(res.report && res.report.message ? res.report.message : "Document semnat.", "ok");
      })));
      blocks.push(h("div", { class: "grid2" }, upCard, signCard));
    }

    if (wf.versions && wf.versions.length) {
      blocks.push(h("div", { class: "card" }, h("h2", null, "Versiuni ale documentului"),
        h("div", { class: "table-wrap" }, h("table", { class: "wf-table" },
          h("thead", null, h("tr", null, ["Pas", "Sursă", "Data", "Semnături", "Mărime"].map((t) => h("th", null, t)))),
          h("tbody", null, wf.versions.map((x) => h("tr", { style: { cursor: "default" } },
            h("td", null, String(x.step)), h("td", null, ({ original: "original", manual: "încărcare manuală", email: "e-mail", local: "semnat local" })[x.source] || x.source || ""),
            h("td", null, fmtDate(x.created_at)), h("td", null, String(x.sig_count ?? "")), h("td", null, fmtSize(x.size)))))))));
    }

    blocks.push(h("div", { class: "card" }, h("h2", null, "Istoric"),
      wf.events && wf.events.length
        ? h("ul", { class: "timeline" }, wf.events.slice().reverse().map((e) => h("li", null,
          h("div", { class: "when" }, fmtDate(e.ts), e.kind ? " · " + e.kind : ""),
          h("div", { style: e.kind === "error" || e.kind === "rejected" ? { color: "var(--err)" } : e.kind === "warning" ? { color: "var(--warn)" } : null }, e.message))))
        : h("p", { class: "muted" }, "Niciun eveniment.")));

    v.replaceChildren(...blocks);
  }

  // =================================================================== 6. SETĂRI
  const PRESETS = {
    gmail: { smtp_host: "smtp.gmail.com", smtp_port: 465, smtp_tls: "ssl", imap_host: "imap.gmail.com", imap_port: 993 },
    outlook: { smtp_host: "smtp.office365.com", smtp_port: 587, smtp_tls: "starttls", imap_host: "outlook.office365.com", imap_port: 993 },
    yahoo: { smtp_host: "smtp.mail.yahoo.com", smtp_port: 465, smtp_tls: "ssl", imap_host: "imap.mail.yahoo.com", imap_port: 993 },
  };

  sectionInit.setari = () => {
    const form = $("#settings-form");
    const el = (n) => form.elements.namedItem(n);

    api("/api/settings").then((s) => {
      for (const [k, v] of Object.entries(s)) {
        const input = el(k);
        if (!input) continue;
        if (input.type === "checkbox") input.checked = !!v && v !== "0" && v !== "false";
        else input.value = v == null ? "" : String(v);
      }
    }).catch((e) => toast(e.message, "err"));

    $("#set-preset").addEventListener("change", (e) => {
      const p = PRESETS[e.target.value];
      if (!p) return;
      for (const [k, v] of Object.entries(p)) el(k).value = String(v);
      const user = el("smtp_user").value || el("from_email").value;
      if (user) {
        if (!el("imap_user").value) el("imap_user").value = user;
        if (!el("from_email").value) el("from_email").value = user;
      }
      if (!el("imap_folder").value) el("imap_folder").value = "INBOX";
      toast("Presetare aplicată. Completați utilizatorul și parola de aplicație, apoi salvați.", "info");
    });

    const collect = () => {
      const out = {};
      for (const input of form.elements) {
        if (!input.name) continue;
        if (input.type === "checkbox") out[input.name] = input.checked;
        else if (input.type === "number") out[input.name] = input.value === "" ? null : Number(input.value);
        else out[input.name] = input.value.trim();
      }
      return out;
    };
    const save = () => api("/api/settings", { body: collect() });

    $("#settings-save").addEventListener("click", (e) => busy(e.currentTarget, async () => {
      await save();
      toast("Setările au fost salvate.", "ok");
    }));
    const test = (btn, url) => busy(btn, async () => {
      await save();
      const r = await api(url, { method: "POST" });
      toast(r.message || (r.ok ? "Conexiune reușită." : "Conexiunea a eșuat."), r.ok ? "ok" : "err");
    });
    $("#test-smtp").addEventListener("click", (e) => test(e.currentTarget, "/api/settings/test-smtp"));
    $("#test-imap").addEventListener("click", (e) => test(e.currentTarget, "/api/settings/test-imap"));
  };

  // =================================================================== pornire
  $("#menu-btn").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
  document.addEventListener("click", (e) => {
    const sb = $("#sidebar");
    if (sb.classList.contains("open") && !sb.contains(e.target) && e.target !== $("#menu-btn")) sb.classList.remove("open");
  });
  window.addEventListener("hashchange", () => showSection(location.hash.slice(1)));
  // previne deschiderea fișierelor plasate în afara zonelor de încărcare
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());
  showSection(location.hash.slice(1) || "semnare");
})();
