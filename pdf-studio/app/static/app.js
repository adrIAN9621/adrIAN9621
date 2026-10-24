/* PDF Studio – interfață web în stil Adobe Acrobat (vanilla JS, fără dependențe). */
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
  function createSignForm(host, { getPdf, showContact = true, getVisible = null, onVisibleToggle = null, visibleDefault = false } = {}) {
    const root = $("#tpl-sign-form").content.firstElementChild.cloneNode(true);
    host.append(root);
    const r = (role) => $(`[data-role="${role}"]`, root);
    const external = typeof getVisible === "function";
    let method = "winstore";
    let certs = [];
    let winCerts = [];
    let visInfo = null;
    let visPdf = null;
    let visRect = null; // fracțiuni [x0,y0,x1,y1] stânga-sus
    let visPage = 0;

    if (!showContact) r("contact-wrap").hidden = true;

    // --- tab-uri metodă (ascunse implicit; dezvăluite prin „Alte metode”)
    $$(".tab", r("method-tabs")).forEach((t) => t.addEventListener("click", () => {
      method = t.dataset.method;
      $$(".tab", root).forEach((x) => x.classList.toggle("active", x === t));
      $$(".method-pane", root).forEach((p) => { p.hidden = p.dataset.method !== method; });
    }));
    const toggleBtn = r("toggle-methods");
    if (toggleBtn) toggleBtn.addEventListener("click", () => {
      const tabs = r("method-tabs");
      tabs.hidden = !tabs.hidden;
    });

    // --- Certificat Windows (magazinul „MY”, ca în Adobe)
    async function loadWinCerts(silent) {
      const sel = r("win-cert");
      try {
        winCerts = await api("/api/sign/windows-certs");
      } catch (_) {
        if (!silent) toast("Nu s-au putut citi certificatele din Windows.", "warn");
        return;
      }
      if (!winCerts.length) {
        sel.replaceChildren(h("option", { value: "" }, "— niciun certificat găsit —"));
        if (!silent) toast("Nu s-a găsit niciun certificat în Windows (doar pe Windows, cu driverul instalat).", "warn");
        return;
      }
      const cur = sel.value;
      sel.replaceChildren();
      winCerts.forEach((c) => sel.append(h("option", { value: c.thumbprint },
        `${c.subject}${c.issuer ? " — " + c.issuer : ""}`)));
      sel.value = (cur && winCerts.some((c) => c.thumbprint === cur)) ? cur : winCerts[0].thumbprint;
      if (!silent) toast(`${winCerts.length} certificat(e) găsite.`, "ok");
    }
    r("win-load").addEventListener("click", (e) => busy(e.currentTarget, () => loadWinCerts(false)));
    loadWinCerts(true);  // completează lista automat la deschidere

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
    if (external) {
      // Poziționarea se face pe vizualizatorul central; panoul intern nu este folosit.
      r("visible").checked = !!visibleDefault;
      r("visible-pane").hidden = true;
      if (onVisibleToggle) onVisibleToggle(r("visible").checked);
      r("visible").addEventListener("change", () => {
        if (onVisibleToggle) onVisibleToggle(r("visible").checked);
      });
    } else {
      const visStage = r("vis-stage");
      const view = pageView(visStage);
      view.setMode("rect", {
        onRect: (rect) => { visRect = rect; view.showSel(rect, "sig-rect"); },
        onCancel: () => view.showSel(visRect, "sig-rect"),
      });

      // eslint-disable-next-line no-inner-declarations
      var showVisible = async function showVisible() {
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
          visPage = Math.max(0, visInfo.pages - 1);
          sel.value = String(visPage);
          visRect = defaultRect(visPage);
        }
        await loadVisPage();
      };
      // eslint-disable-next-line no-inner-declarations
      function defaultRect(page) {
        const [W, H] = visInfo.page_sizes[page] || [595, 842];
        const w = 200, hh = 70, m = 40;
        return [(W - m - w) / W, (H - m - hh) / H, (W - m) / W, (H - m) / H];
      }
      // eslint-disable-next-line no-inner-declarations
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
    }

    return {
      root,
      /** Adaugă câmpurile formularului în FormData; aruncă Error dacă lipsesc date. */
      appendTo(f) {
        f.append("method", method);
        if (method === "winstore") {
          const tp = r("win-cert").value;
          if (!tp) throw new Error("Încărcați și selectați un certificat din Windows.");
          f.append("thumbprint", tp);
        } else if (method === "pkcs11") {
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
          let vInfo = visInfo, vPage = visPage, vRect = visRect;
          if (external) {
            const st = getVisible();
            if (!st || !st.info || !st.rect) {
              throw new Error("Previzualizarea paginii nu s-a încărcat încă; poziționați semnătura.");
            }
            vInfo = st.info; vPage = st.page; vRect = st.rect;
          }
          if (!vInfo || !vRect) throw new Error("Previzualizarea paginii nu s-a încărcat încă; poziționați semnătura.");
          const [W, H] = vInfo.page_sizes[vPage];
          const [x0, y0, x1, y1] = vRect;
          // conversie în puncte PDF, origine stânga-jos
          f.append("visible", "1");
          f.append("page", String(vPage));
          f.append("x", (x0 * W).toFixed(2));
          f.append("y", ((1 - y1) * H).toFixed(2));
          f.append("w", ((x1 - x0) * W).toFixed(2));
          f.append("h", ((y1 - y0) * H).toFixed(2));
        }
      },
      /** Documentul s-a schimbat – reîncarcă previzualizarea dacă e deschisă. */
      pdfChanged() {
        if (external) return; // vizualizatorul central este gestionat separat
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

  // =================================================================== validare (randare)
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

  // =================================================================== MODELUL DE DOCUMENT + VIZUALIZATOR
  /**
   * Un singur „document curent”. Toate instrumentele operează pe el; cele care îl
   * transformă (semnare, editare, comprimare, organizare) îl înlocuiesc și
   * reîmprospătează vizualizatorul.
   */
  const D = {
    file: null,     // File (PDF curent)
    info: null,     // rezultat /api/pdf/info
    page: 0,
    zoom: "fit",
    ops: [],        // operații de editare în așteptare (editor + editare text)
    tool: null,     // instrumentul activ din bara verticală
    editTool: null, // sub-instrument de editare desen
    textEditMode: false,
    listeners: [],  // callback-uri la schimbarea documentului
  };
  const onDocChange = (fn) => D.listeners.push(fn);
  function emitDocChange() { D.listeners.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } }); }

  function pageSize(p) { return (D.info && D.info.page_sizes[p]) || [595, 842]; }
  const round = (v) => Math.round(v * 100) / 100;

  const viewer = (() => {
    const stage = $("#viewer-stage");
    const pv = pageView(stage);
    let interaction = "none"; // none | sign | point | rect
    let handlers = {};        // pentru point/rect (editor)
    let sigEnabled = true;
    const sigRects = {};
    let thumbObserver = null;

    function sigDefaultRect(page) {
      const [W, H] = pageSize(page);
      const w = 200, hh = 70, m = 40;
      return [(W - m - w) / W, (H - m - hh) / H, (W - m) / W, (H - m) / H];
    }
    function sigRectFor(page) {
      if (!(page in sigRects)) sigRects[page] = sigDefaultRect(page);
      return sigRects[page];
    }
    function paintSig() {
      pv.showSel(interaction === "sign" && sigEnabled && D.info ? sigRectFor(D.page) : null, "sig-rect");
    }
    function zoomFor() {
      const [W, H] = pageSize(D.page);
      const avail = Math.max(240, stage.clientWidth - 36);
      if (D.zoom === "fit") return Math.round(Math.min(3, Math.max(0.3, avail / W)) * 20) / 20;
      if (D.zoom === "fit-page") {
        const availH = Math.max(240, stage.clientHeight - 36);
        return Math.round(Math.min(3, Math.max(0.3, Math.min(avail / W, availH / H))) * 20) / 20;
      }
      return Number(D.zoom);
    }

    function applyMode() {
      if (interaction === "sign") {
        pv.setMode(sigEnabled ? "rect" : "none", {
          onRect: (rect) => { sigRects[D.page] = rect; paintSig(); },
          onCancel: () => paintSig(),
        });
        paintSig();
      } else if (interaction === "point") {
        pv.setMode("point", { onPoint: handlers.onPoint });
        pv.showSel(null);
      } else if (interaction === "rect") {
        pv.setMode("rect", { onRect: handlers.onRect });
        pv.showSel(null);
      } else {
        pv.setMode("none");
        pv.showSel(null);
      }
    }

    function syncPager() {
      const n = D.info ? D.info.pages : 0;
      $("#vw-pagecount").textContent = String(n);
      $("#vw-pagenum").max = String(n);
      $("#vw-pagenum").value = String(D.page + 1);
      $("#vw-prev").disabled = D.page <= 0;
      $("#vw-next").disabled = D.page >= n - 1;
      $$(".vthumb", $("#viewer-thumbs")).forEach((t, i) => t.classList.toggle("active", i === D.page));
      const active = $(".vthumb.active", $("#viewer-thumbs"));
      if (active) active.scrollIntoView({ block: "nearest" });
    }

    async function render() {
      if (!D.file || !D.info) return;
      await pv.load(D.file, D.page, zoomFor());
      applyMode();
      renderMarks();
      syncPager();
      if (D.textEditMode) renderTextEditOverlay();
    }

    function renderThumbs() {
      const box = $("#viewer-thumbs");
      if (thumbObserver) thumbObserver.disconnect();
      const file = D.file;
      const queue = [];
      let running = 0;
      const pump = () => {
        while (running < 2 && queue.length) {
          const { img, i } = queue.shift();
          running++;
          renderPage(file, i, 0.22).then((url) => { img.src = url; }).catch(() => {})
            .finally(() => { running--; pump(); });
        }
      };
      thumbObserver = new IntersectionObserver((entries) => {
        entries.forEach((en) => {
          if (!en.isIntersecting) return;
          thumbObserver.unobserve(en.target);
          if (file !== D.file) return;
          queue.push({ img: $("img", en.target), i: Number(en.target.dataset.i) });
        });
        pump();
      }, { root: box, rootMargin: "400px" });
      box.replaceChildren(...Array.from({ length: D.info.pages }, (_, i) => {
        const t = h("div", { class: "vthumb" + (i === D.page ? " active" : ""), "data-i": String(i), onclick: () => api_goPage(i) },
          h("div", { class: "vti" }, h("img", { alt: `Pagina ${i + 1}` })), h("span", { class: "vtn" }, String(i + 1)));
        thumbObserver.observe(t);
        return t;
      }));
    }

    function api_goPage(p) {
      if (!D.info) return;
      D.page = Math.max(0, Math.min(D.info.pages - 1, p));
      clearTextEditOverlay();
      render().catch((e) => toast(e.message, "err"));
      if (D.tool === "edit") renderToolOptions(); // actualizează formularele dependente de pagină
    }

    return {
      get wrap() { return pv.wrap; },
      async setFile(file, { keepPage = false } = {}) {
        D.file = file;
        D.info = await pdfInfo(file);
        if (!keepPage) D.page = 0;
        D.page = Math.min(D.page, Math.max(0, D.info.pages - 1));
        $("#viewer-empty").hidden = true;
        $("#viewer-doc").hidden = false;
        $("#cur-file").textContent = file.name;
        $("#cur-file").title = file.name;
        $("#download-btn").disabled = false;
        renderThumbs();
        updateSigBanner();
        await render();
        emitDocChange();
      },
      goPage: api_goPage,
      setZoom(z) { D.zoom = z; return render(); },
      zoomStep(dir) {
        const cur = zoomFor();
        const z = Math.min(3, Math.max(0.3, Math.round((cur + dir * 0.25) * 20) / 20));
        D.zoom = String(z);
        $("#vw-zoom").value = [..."0.5,0.75,1,1.5,2".split(",")].includes(String(z)) ? String(z) : $("#vw-zoom").value;
        return render();
      },
      render,
      setInteraction(mode, hs = {}) { interaction = mode; handlers = hs; applyMode(); },
      setSigEnabled(on) { sigEnabled = !!on; if (interaction === "sign") applyMode(); },
      getVisible() {
        if (!D.info) return null;
        return { info: D.info, page: D.page, rect: sigRectFor(D.page) };
      },
      resetSig() { for (const k of Object.keys(sigRects)) delete sigRects[k]; },
      setMarks: (l) => pv.setMarks(l),
      currentZoom: zoomFor,
    };
  })();

  function updateSigBanner() {
    const b = $("#sig-banner");
    if (!D.info || !D.info.signature_count) { b.hidden = true; return; }
    const n = D.info.signature_count;
    b.hidden = false;
    b.replaceChildren(
      h("span", { class: "sb-icon", "aria-hidden": "true" }, "✓"),
      h("span", { class: "sb-text" }, `Document semnat · ${n} semnătur${n === 1 ? "ă" : "i"} electronic${n === 1 ? "ă" : "e"} în document.`),
      h("button", { class: "btn small", onclick: () => openTool("validate", { run: true }) }, "Panou semnături"));
  }

  // =================================================================== editor: instrumente de desenare / pagini
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
  const edOpt = {
    text: "", size: 12, color: "#000000",
    rectColor: "#e11d48", fill: false, fillColor: "#fde68a", width: 1.5,
    note: "", imageB64: null, imageName: "",
    search: "", replace: "", replacePage: false,
    rotateAll: false, moveTo: 1, blankAt: 1,
  };

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
      case "edit_text": return `Editare text „${(op._orig || "").slice(0, 24)}” → „${op.text.slice(0, 24)}” (${pg(op.page)})`;
      case "replace_text": return `Înlocuire „${op.search}” → „${op.replace}”${op.page != null ? " (" + pg(op.page) + ")" : " (toate paginile)"}`;
      case "rotate": return `Rotire ${op.angle}°${op.page == null ? " (toate paginile)" : " (" + pg(op.page) + ")"}`;
      case "delete_page": return `Ștergere ${pg(op.page)}`;
      case "move_page": return `Mutare pag. ${op.from + 1} → poziția ${op.to + 1}`;
      case "insert_blank": return `Pagină goală la poziția ${op.at + 1}`;
      case "set_metadata": return `Metadate (titlu: ${op.title || "—"})`;
      default: return op.type;
    }
  }

  function addOp(op) { D.ops.push(op); renderOps(); renderMarks(); }

  function renderOps() {
    const list = $("#ed-ops");
    if (!list) return;
    list.replaceChildren(...D.ops.map((op, i) => h("li", null,
      h("div", { class: "op-row" },
        h("span", { class: "link", title: "Mergi la pagină", onclick: () => { if (op.page != null && op.page < D.info.pages) viewer.goPage(op.page); } }, opText(op)),
        h("button", { class: "x", title: "Elimină", "aria-label": "Elimină", onclick: () => { D.ops.splice(i, 1); renderOps(); renderMarks(); } }, "×")))));
    const cnt = $("#ed-opcount");
    if (cnt) cnt.textContent = String(D.ops.length);
  }

  function renderMarks() {
    if (!D.info) return;
    const [W, H] = pageSize(D.page);
    const marks = [];
    D.ops.forEach((op, i) => {
      if (op.page !== D.page) return;
      if (op.rect) marks.push({ rect: [op.rect[0] / W, op.rect[1] / H, op.rect[2] / W, op.rect[3] / H], cls: op.type, label: `${i + 1}` });
      else if (op.x != null) marks.push({ x: op.x / W, y: op.y / H, label: `${i + 1}. ${op.text.slice(0, 20)}` });
    });
    viewer.setMarks(marks);
  }

  // ---------------------------------------------------------------- click-to-edit (editare text pe pagină)
  let textEditLayer = null;
  let textEditToken = 0;

  function clearTextEditOverlay() {
    textEditToken++;
    if (textEditLayer) { textEditLayer.remove(); textEditLayer = null; }
  }

  // Eșantionează culoarea de fundal din imaginea paginii, lângă fiecare text,
  // ca să putem acoperi textul original (evită efectul de „dublare").
  function makeBgSampler(pageW, pageH) {
    let dataImg = null, iw = 0, ih = 0;
    try {
      const img = viewer.wrap.querySelector("img");
      if (img && img.naturalWidth) {
        const c = document.createElement("canvas");
        iw = img.naturalWidth; ih = img.naturalHeight;
        c.width = iw; c.height = ih;
        const cx = c.getContext("2d");
        cx.drawImage(img, 0, 0);
        dataImg = cx.getImageData(0, 0, iw, ih).data;
      }
    } catch (_) { dataImg = null; }

    return function (bbox) {
      if (!dataImg) return "#fff";
      const sx = iw / pageW, sy = ih / pageH;
      const [x0, y0, x1, y1] = bbox;
      const midX = (x0 + x1) / 2, midY = (y0 + y1) / 2;
      // puncte chiar în afara textului (acolo e aproape sigur fundalul)
      const pts = [
        [midX, y0 - 2], [midX, y1 + 2], [x0 - 2, midY], [x1 + 2, midY],
        [x0 - 2, y0 - 2], [x1 + 2, y0 - 2], [x0 - 2, y1 + 2], [x1 + 2, y1 + 2],
      ];
      const counts = {};
      let best = null, bestN = 0;
      for (const [px, py] of pts) {
        const ix = Math.min(iw - 1, Math.max(0, Math.round(px * sx)));
        const iy = Math.min(ih - 1, Math.max(0, Math.round(py * sy)));
        const o = (iy * iw + ix) * 4;
        const key = (dataImg[o] >> 4) + "," + (dataImg[o + 1] >> 4) + "," + (dataImg[o + 2] >> 4);
        counts[key] = (counts[key] || 0) + 1;
        if (counts[key] > bestN) { bestN = counts[key]; best = [dataImg[o], dataImg[o + 1], dataImg[o + 2]]; }
      }
      return best ? `rgb(${best[0]},${best[1]},${best[2]})` : "#fff";
    };
  }

  async function renderTextEditOverlay() {
    if (!D.textEditMode || !D.file) return;
    const my = ++textEditToken;
    const page = D.page;
    const zoom = viewer.currentZoom();
    let data;
    try {
      data = await api("/api/pdf/spans", { body: fd({ file: D.file, page }) });
    } catch (e) {
      if (my === textEditToken) toast(e.message, "err");
      return;
    }
    if (my !== textEditToken || !D.textEditMode || D.page !== page) return;
    if (textEditLayer) { textEditLayer.remove(); textEditLayer = null; }
    const [PW, PH] = pageSize(page);
    const sampleBg = makeBgSampler(PW, PH);
    // scara reală afișată (contează la „Potrivire lățime"), nu valoarea zoom
    const pimg = viewer.wrap.querySelector("img");
    const sx = (pimg && pimg.clientWidth) ? pimg.clientWidth / PW : zoom;
    const sy = (pimg && pimg.clientHeight) ? pimg.clientHeight / PH : zoom;
    const layer = h("div", { class: "edit-text-layer" });
    (data.spans || []).forEach((sp) => {
      const [x0, y0, x1, y1] = sp.bbox;
      const w = Math.max(0, (x1 - x0) * sx);
      const hh = Math.max(0, (y1 - y0) * sy);
      const div = h("div", { class: "edit-span", contenteditable: "true", spellcheck: "false", title: "Faceți clic pentru a rescrie textul" });
      div.textContent = sp.text;
      // fundalul = culoarea din spatele textului (acoperă textul original -> fără dublare)
      const bg = sampleBg(sp.bbox);
      Object.assign(div.style, {
        left: (x0 * sx) + "px", top: (y0 * sy) + "px",
        minWidth: w + "px",
        // nu lăsăm caseta să iasă din pagină (în gutter) când textul crește
        maxWidth: Math.max(w, (PW - x0) * sx) + "px",
        height: hh + "px", lineHeight: hh + "px",
        fontSize: (sp.size * sy) + "px", color: sp.color,
        fontWeight: sp.bold ? "700" : "400", fontStyle: sp.italic ? "italic" : "normal",
        background: bg || "#fff",
      });
      const orig = sp.text;
      let myOp = null;
      div.addEventListener("blur", () => {
        const nt = div.textContent;
        if (myOp) {
          const idx = D.ops.indexOf(myOp);
          if (nt === orig) {
            if (idx >= 0) D.ops.splice(idx, 1);
            myOp = null;
            renderOps(); renderMarks();
          } else { myOp.text = nt; renderOps(); renderMarks(); }
          return;
        }
        if (nt === orig) return;
        myOp = { type: "edit_text", page, rect: [x0, y0, x1, y1], text: nt, size: sp.size, color: sp.color, _orig: orig };
        addOp(myOp);
      });
      layer.append(div);
    });
    viewer.wrap.append(layer);
    textEditLayer = layer;
  }

  function onEditorPoint(fx, fy) {
    const [W, H] = pageSize(D.page);
    const x = round(fx * W), y = round(fy * H);
    if (D.editTool === "add_text") {
      const text = edOpt.text.trim() ? edOpt.text : window.prompt("Textul de adăugat:", "");
      if (!text) return;
      addOp({ type: "add_text", page: D.page, x, y, text, size: Number(edOpt.size) || 12, color: edOpt.color });
    } else if (D.editTool === "note") {
      const text = edOpt.note.trim() ? edOpt.note : window.prompt("Textul notei:", "");
      if (!text) return;
      addOp({ type: "note", page: D.page, x, y, text });
    }
  }

  function onEditorRect(fr, sel) {
    const [W, H] = pageSize(D.page);
    const rect = [round(fr[0] * W), round(fr[1] * H), round(fr[2] * W), round(fr[3] * H)];
    if (sel) sel.hidden = true;
    switch (D.editTool) {
      case "highlight": addOp({ type: "highlight", page: D.page, rect }); break;
      case "rect": addOp({ type: "rect", page: D.page, rect, color: edOpt.rectColor, fill: edOpt.fill ? edOpt.fillColor : null, width: Number(edOpt.width) || 1 }); break;
      case "whiteout": addOp({ type: "whiteout", page: D.page, rect }); break;
      case "redact": addOp({ type: "redact", page: D.page, rect }); break;
      case "image":
        if (!edOpt.imageB64) { toast("Alegeți întâi imaginea din bara de opțiuni.", "warn"); return; }
        addOp({ type: "image", page: D.page, rect, image_b64: edOpt.imageB64, _name: edOpt.imageName });
        break;
      default: break;
    }
  }

  function optField(label, input) { return h("label", { class: "field" }, label, input); }
  function bindOpt(input, key, conv = (v) => v) {
    const isCheck = input.type === "checkbox";
    if (isCheck) input.checked = !!edOpt[key]; else input.value = edOpt[key];
    input.addEventListener(isCheck ? "change" : "input", () => { edOpt[key] = isCheck ? input.checked : conv(input.value); });
    return input;
  }
  const tip = (t) => h("span", { class: "tip" }, t);

  function setEditTool(id) {
    if (D.textEditMode) setTextEdit(false);
    D.editTool = D.editTool === id ? null : id;
    $$(".tool", $("#ed-tools") || document.createElement("div")).forEach((b) => b.classList.toggle("active", b.dataset.tool === D.editTool));
    renderToolOptions();
    const t = TOOLS.find((x) => x.id === D.editTool);
    if (!t || t.kind === "form") { viewer.setInteraction("none"); return; }
    if (t.kind === "point") viewer.setInteraction("point", { onPoint: onEditorPoint });
    else viewer.setInteraction("rect", { onRect: onEditorRect });
  }

  function setTextEdit(on) {
    D.textEditMode = !!on;
    if (D.textEditMode && D.editTool) { D.editTool = null; viewer.setInteraction("none"); }
    const btn = $("#ed-texttoggle");
    if (btn) btn.classList.toggle("active", D.textEditMode);
    if (D.textEditMode) {
      viewer.setInteraction("none");
      const box = $("#ed-tool-opts");
      if (box) box.replaceChildren(tip("Faceți clic pe un text din pagină pentru a-l rescrie direct. Modificările apar în lista de operații și se aplică la „Aplică”."));
      renderTextEditOverlay();
    } else {
      clearTextEditOverlay();
      renderToolOptions();
    }
  }

  function renderToolOptions() {
    const box = $("#ed-tool-opts");
    if (!box) return;
    box.replaceChildren();
    if (D.textEditMode) { box.append(tip("Faceți clic pe un text din pagină pentru a-l rescrie.")); return; }
    const pnum = D.page + 1;
    switch (D.editTool) {
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
            edOpt.imageB64 = await fileToBase64(f);
            edOpt.imageName = f.name;
            toast("Imagine pregătită. Trageți pe pagină zona în care va fi plasată.", "ok");
          } catch (e) { toast(e.message, "err"); }
        });
        box.append(optField("Imagine (PNG/JPG)", inp),
          tip(edOpt.imageName ? `Imagine curentă: ${edOpt.imageName}. Trageți pe pagină zona dorită.` : "Alegeți imaginea, apoi trageți pe pagină zona dorită."));
        break;
      }
      case "note":
        box.append(optField("Textul notei", bindOpt(h("input", { type: "text", placeholder: "Comentariu" }), "note")),
          tip("Faceți clic pe pagină pentru a plasa nota."));
        break;
      case "replace_text": {
        const s = bindOpt(h("input", { type: "text", placeholder: "Text căutat" }), "search");
        const rr = bindOpt(h("input", { type: "text", placeholder: "Text nou" }), "replace");
        box.append(optField("Caută", s), optField("Înlocuiește cu", rr),
          h("label", { class: "check" }, bindOpt(h("input", { type: "checkbox" }), "replacePage"), `Doar pagina curentă (${pnum})`),
          h("button", { class: "btn small primary", onclick: () => {
            if (!edOpt.search) { toast("Introduceți textul căutat.", "warn"); return; }
            addOp({ type: "replace_text", search: edOpt.search, replace: edOpt.replace, page: edOpt.replacePage ? D.page : null });
          } }, "Adaugă"));
        break;
      }
      case "rotate": {
        const rot = (angle) => addOp({ type: "rotate", page: edOpt.rotateAll ? null : D.page, angle });
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
          if (D.info.pages <= 1) { toast("Documentul are o singură pagină.", "warn"); return; }
          addOp({ type: "delete_page", page: D.page });
        } }, `Șterge pagina ${pnum}`), tip("Navigați la pagina dorită, apoi apăsați butonul."));
        break;
      case "move_page": {
        edOpt.moveTo = Math.min(edOpt.moveTo, D.info.pages);
        const inp = bindOpt(h("input", { type: "number", min: "1", max: String(D.info.pages), class: "num" }), "moveTo", Number);
        box.append(optField(`Mută pagina ${pnum} pe poziția`, inp),
          h("button", { class: "btn small primary", onclick: () => {
            const to = Math.round(edOpt.moveTo) - 1;
            if (!(to >= 0 && to < D.info.pages)) { toast(`Poziția trebuie să fie între 1 și ${D.info.pages}.`, "warn"); return; }
            if (to === D.page) { toast("Pagina se află deja pe această poziție.", "warn"); return; }
            addOp({ type: "move_page", from: D.page, to });
          } }, "Adaugă"));
        break;
      }
      case "insert_blank": {
        edOpt.blankAt = D.page + 2;
        const inp = bindOpt(h("input", { type: "number", min: "1", max: String(D.info.pages + 1), class: "num" }), "blankAt", Number);
        box.append(optField("Inserează pagină goală pe poziția", inp),
          h("button", { class: "btn small primary", onclick: () => {
            const at = Math.round(edOpt.blankAt) - 1;
            if (!(at >= 0 && at <= D.info.pages)) { toast(`Poziția trebuie să fie între 1 și ${D.info.pages + 1}.`, "warn"); return; }
            addOp({ type: "insert_blank", at });
          } }, "Adaugă"), tip(`Implicit: după pagina curentă (${pnum}).`));
        break;
      }
      case "set_metadata": {
        const md = (D.info && D.info.metadata) || {};
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

  async function applyEdits(download) {
    if (!D.ops.length) throw new Error("Nu există operații de aplicat.");
    const ops = D.ops.map((op) => { const o = { ...op }; delete o._name; delete o._orig; return o; });
    const { blob, filename } = await api("/api/pdf/edit", { body: fd({ file: D.file, ops: JSON.stringify(ops) }), as: "blob" });
    if (download) saveBlob(blob, filename || "document_editat.pdf");
    const name = D.file.name;
    const file = new File([blob], name, { type: "application/pdf" });
    D.ops = [];
    clearTextEditOverlay();
    await viewer.setFile(file, { keepPage: true });
    renderOps();
    toast(download ? "Modificările au fost aplicate și documentul descărcat." : "Modificările au fost aplicate. Puteți continua editarea.", "ok");
  }

  // =================================================================== PANOURI (dreapta)
  const rpBody = () => $("#rp-body");
  const panelCache = {};
  let esignSetPfx = null; // setată de panoul E-Sign activ, folosită de dialogul de certificat de test

  function buildEsign() {
    const host = h("div", { class: "panel esign-panel" });
    const formHost = h("div", { id: "sign-form-host", class: "card" });
    const successHost = h("div", { id: "sign-success-host" });
    const signBtn = h("button", { class: "btn primary block", id: "sign-btn" }, "Semnează");
    const testLink = h("a", { href: "#", class: "link small", id: "testcert-link" }, "Generează certificat de test");

    host.append(
      h("p", { class: "lead" }, "Semnați electronic PDF-ul deschis (PAdES). Documentul primește implicit o semnătură vizibilă; trageți un dreptunghi pe pagina din vizualizator pentru a o poziționa."),
      formHost,
      h("div", { class: "actions" }, signBtn, testLink),
      successHost);

    const form = createSignForm(formHost, {
      getPdf: async () => D.file,
      getVisible: () => viewer.getVisible(),
      onVisibleToggle: (on) => viewer.setSigEnabled(on),
      visibleDefault: true,
    });

    function hideSuccess() { successHost.replaceChildren(); signBtn.hidden = false; }
    function showSuccess(blob, filename) {
      const name = filename || "document_semnat.pdf";
      signBtn.hidden = true;
      const infoLine = h("div", { class: "muted small" }, "Se analizează documentul semnat…");
      const valOut = h("div", { class: "sign-success-val" });
      const panel = h("div", { class: "card sign-success" },
        h("div", { class: "sign-success-head" },
          h("span", { class: "sign-success-check", "aria-hidden": "true" }, "✓"),
          h("h2", null, "Document semnat")),
        infoLine,
        h("div", { class: "actions" },
          h("button", { class: "btn primary", type: "button", onclick: () => saveBlob(blob, name) }, "Descarcă documentul semnat"),
          h("button", { class: "btn", type: "button", onclick: (e) => busy(e.currentTarget, async () => {
            valOut.replaceChildren(h("div", { class: "loading" }, h("span", { class: "spinner" }), "Se validează semnătura…"));
            try {
              const sigs = await api("/api/validate", { body: fd({ file: D.file }) });
              renderValidation(valOut, sigs, D.file.name);
            } catch (err) { valOut.replaceChildren(); toast(err.message || "Validarea a eșuat.", "err"); }
          }) }, "Validează semnătura"),
          h("button", { class: "btn", type: "button", onclick: hideSuccess }, "Semnează din nou")),
        valOut);
      successHost.replaceChildren(panel);
      pdfInfo(D.file).then((inf) => {
        const n = inf.signature_count;
        infoLine.textContent = `${name} · ${n} semnătur${n === 1 ? "ă" : "i"} în document.`;
      }).catch(() => { infoLine.textContent = name; });
    }

    signBtn.addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!D.file) throw new Error("Deschideți întâi un document PDF.");
      const f = fd({ file: D.file });
      form.appendTo(f);
      const { blob, filename } = await api("/api/sign", { body: f, as: "blob" });
      const name = D.file.name.replace(/\.pdf$/i, "") + "_semnat.pdf";
      const outName = filename || name;
      const file = new File([blob], outName, { type: "application/pdf" });
      viewer.resetSig();
      await viewer.setFile(file, { keepPage: true });
      form.pdfChanged();
      showSuccess(blob, outName);
      toast("Documentul a fost semnat.", "ok");
    }));

    const dlg = $("#testcert-dialog");
    testLink.addEventListener("click", (e) => {
      e.preventDefault();
      esignSetPfx = (file, pass) => form.setPfx(file, pass);
      if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    });

    return {
      el: host, mode: "sign", needsDoc: true,
      show() { hideSuccess(); viewer.setInteraction("sign"); viewer.setSigEnabled($(`[data-role="visible"]`, formHost).checked); },
      docChanged() { form.pdfChanged(); },
      _setPfx: (file, pass) => form.setPfx(file, pass),
    };
  }

  function buildValidate() {
    const host = h("div", { class: "panel" });
    const rootsHost = h("div");
    const out = h("div", { id: "val-results" });
    const btn = h("button", { class: "btn primary block", id: "val-btn" }, "Validează");
    host.append(
      h("p", { class: "lead" }, "Verificați integritatea și încrederea semnăturilor din documentul deschis."),
      h("details", { class: "mt" },
        h("summary", null, "Certificate rădăcină de încredere suplimentare (opțional)"),
        h("p", { class: "hint" }, "De exemplu certificatul CA al furnizorului (.cer, .crt, .pem, .der)."),
        rootsHost),
      h("div", { class: "actions" }, btn), out);
    const roots = dropZone(rootsHost, { multiple: true, accept: ".cer,.crt,.pem,.der,.p7b", title: "Trageți certificatele rădăcină aici" });

    async function run() {
      if (!D.file) throw new Error("Deschideți întâi un document PDF.");
      const f = fd({ file: D.file });
      roots.files.forEach((r) => f.append("roots", r, r.name));
      out.replaceChildren(h("div", { class: "loading" }, h("span", { class: "spinner" }), "Se validează semnăturile…"));
      try {
        const sigs = await api("/api/validate", { body: f });
        renderValidation(out, sigs, D.file.name);
      } catch (err) { out.replaceChildren(); throw err; }
    }
    btn.addEventListener("click", (e) => busy(e.currentTarget, run));
    return { el: host, mode: "none", needsDoc: true, show(opts) { if (opts && opts.run) busy(btn, run); }, docChanged() { out.replaceChildren(); } };
  }

  function buildEditText() {
    const host = h("div", { class: "panel" });
    const toggle = h("button", { class: "btn primary block", id: "ed-texttoggle" }, "✎ Activează editarea textului");
    const opsBox = editorOpsBlock();
    host.append(
      h("p", { class: "lead" }, "Faceți clic pe orice text din pagină și rescrieți-l direct, ca în Acrobat. Modificările se adună în listă și se aplică la „Aplică”."),
      toggle,
      h("div", { class: "tool-options", id: "ed-tool-opts" }),
      opsBox);
    toggle.addEventListener("click", () => {
      setTextEdit(!D.textEditMode);
      toggle.textContent = D.textEditMode ? "✓ Editarea textului activă (clic pentru a opri)" : "✎ Activează editarea textului";
    });
    return {
      el: host, mode: "none", needsDoc: true,
      show() { renderOps(); if (D.textEditMode) renderTextEditOverlay(); },
      docChanged() { renderOps(); toggle.textContent = "✎ Activează editarea textului"; },
    };
  }

  function editorOpsBlock() {
    return h("div", { class: "ops-panel" },
      h("h3", null, "Operații în așteptare ", h("span", { class: "badge", id: "ed-opcount" }, "0")),
      h("ol", { id: "ed-ops", class: "ops-list" }),
      h("div", { class: "actions" },
        h("button", { class: "btn small", id: "ed-clear-ops", onclick: () => { D.ops = []; renderOps(); renderMarks(); } }, "Golește lista"),
        h("button", { class: "btn", id: "ed-apply", onclick: (e) => busy(e.currentTarget, () => applyEdits(false)) }, "Aplică"),
        h("button", { class: "btn primary", id: "ed-apply-dl", onclick: (e) => busy(e.currentTarget, () => applyEdits(true)) }, "Aplică și descarcă")),
      h("p", { class: "hint" }, "Operațiile se aplică în ordine și reîmprospătează vizualizatorul. Operațiile pe pagini (ștergere, mutare, inserare) schimbă numerotarea pentru operațiile ulterioare."));
  }

  function buildEdit() {
    const host = h("div", { class: "panel" });
    const tools = h("div", { class: "toolbar", id: "ed-tools" });
    tools.append(...TOOLS.map((t) => h("button", { class: "tool", "data-tool": t.id, onclick: () => setEditTool(t.id) }, t.label)));
    host.append(
      h("p", { class: "lead" }, "Adăugați text, evidențieri, forme, note, imagini, redactări sau operații pe pagini. Desenați direct pe pagina din vizualizator."),
      tools,
      h("div", { class: "tool-options", id: "ed-tool-opts" }),
      editorOpsBlock());
    return {
      el: host, mode: "none", needsDoc: true,
      show() { renderOps(); renderToolOptions(); if (D.editTool) { const t = TOOLS.find((x) => x.id === D.editTool); if (t && t.kind === "point") viewer.setInteraction("point", { onPoint: onEditorPoint }); else if (t && t.kind === "rect") viewer.setInteraction("rect", { onRect: onEditorRect }); } },
      docChanged() { renderOps(); renderToolOptions(); },
    };
  }

  function buildExportWord() {
    const host = h("div", { class: "panel" });
    host.append(
      h("p", { class: "lead" }, "Convertește documentul PDF deschis într-un fișier Word (.docx) editabil."),
      h("div", { class: "actions" },
        h("button", { class: "btn primary block", onclick: (e) => busy(e.currentTarget, async () => {
          if (!D.file) throw new Error("Deschideți întâi un document PDF.");
          const { blob, filename } = await api("/api/convert/pdf-to-word", { body: fd({ file: D.file }), as: "blob" });
          saveBlob(blob, filename || "document.docx");
          toast("Conversie reușită. Fișierul Word a fost descărcat.", "ok");
        }) }, "Convertește în Word")));
    return { el: host, mode: "none", needsDoc: true, show() {}, docChanged() {} };
  }

  function buildCreatePdf() {
    const host = h("div", { class: "panel" });
    const warn = h("div");
    const dzHost = h("div");
    host.append(
      h("p", { class: "lead" }, "Creează un PDF dintr-un document Word sau Office. Rezultatul devine documentul curent din vizualizator."),
      warn, dzHost,
      h("div", { class: "actions" }, h("button", { class: "btn primary block", id: "w2p-btn" }, "Creează PDF")));
    const officeExt = /\.(docx?|odt|rtf|txt|xlsx?|ods|csv|pptx?|odp)$/i;
    const dz = dropZone(dzHost, {
      accept: ".docx,.doc,.odt,.rtf,.txt,.xlsx,.xls,.ods,.csv,.pptx,.ppt,.odp",
      title: "Trageți documentul Word / Office aici",
      sub: "docx, doc, odt, rtf, txt, xlsx, pptx … – sau faceți clic",
      validate: (f) => officeExt.test(f.name),
    });
    api("/api/convert/status").then((st) => {
      if (!st.soffice) warn.replaceChildren(h("div", { class: "alert warn" },
        h("strong", null, "LibreOffice nu a fost găsit. "),
        "Conversia Office → PDF necesită LibreOffice (soffice); pe Windows se poate folosi și Microsoft Word. Descărcați de pe libreoffice.org și reporniți aplicația."));
    }).catch(() => {});
    $("#w2p-btn", host).addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!dz.file) throw new Error("Selectați documentul de convertit.");
      const { blob, filename } = await api("/api/convert/to-pdf", { body: fd({ file: dz.file }), as: "blob" });
      const name = filename || "document.pdf";
      saveBlob(blob, name);
      const file = new File([blob], name, { type: "application/pdf" });
      await viewer.setFile(file);
      toast("PDF creat și deschis în vizualizator.", "ok");
    }));
    return { el: host, mode: "none", needsDoc: false, show() {}, docChanged() {} };
  }

  function buildCombine() {
    const host = h("div", { class: "panel" });
    const dzHost = h("div");
    const list = h("ol", { class: "file-list", id: "merge-list" });
    host.append(
      h("p", { class: "lead" }, "Adăugați mai multe PDF-uri și stabiliți ordinea. Documentul combinat devine documentul curent."),
      dzHost, list,
      h("div", { class: "actions" }, h("button", { class: "btn primary block", id: "merge-btn" }, "Combină")));
    const files = [];
    const render = () => list.replaceChildren(...files.map((f, i) => h("li", null,
      h("strong", null, `${i + 1}.`), h("span", { class: "fn" }, `${f.name} (${fmtSize(f.size)})`),
      h("button", { class: "btn small", disabled: i === 0, title: "Mută în sus", onclick: () => { [files[i - 1], files[i]] = [files[i], files[i - 1]]; render(); } }, "↑"),
      h("button", { class: "btn small", disabled: i === files.length - 1, title: "Mută în jos", onclick: () => { [files[i + 1], files[i]] = [files[i], files[i + 1]]; render(); } }, "↓"),
      h("button", { class: "btn small danger", title: "Elimină", onclick: () => { files.splice(i, 1); render(); } }, "×"))));
    const dz = dropZone(dzHost, { multiple: true, validate: isPdf, title: "Trageți PDF-urile aici", onChange: (arr) => { files.push(...arr); render(); dz.clear(); } });
    // dacă există un document deschis, oferă-l ca prim fișier
    $("#merge-btn", host).addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (files.length < 2) throw new Error("Adăugați cel puțin două fișiere PDF.");
      const f = new FormData();
      files.forEach((x) => f.append("files", x, x.name));
      const { blob, filename } = await api("/api/pdf/merge", { body: f, as: "blob" });
      const name = filename || "combinat.pdf";
      saveBlob(blob, name);
      const file = new File([blob], name, { type: "application/pdf" });
      await viewer.setFile(file);
      toast("Fișierele au fost combinate și deschise în vizualizator.", "ok");
    }));
    return {
      el: host, mode: "none", needsDoc: false,
      show() { if (D.file && !files.some((x) => x.name === D.file.name)) { files.unshift(D.file); render(); } },
      docChanged() {},
    };
  }

  function buildOrganize() {
    const host = h("div", { class: "panel" });
    const rangesInp = h("input", { type: "text", id: "split-ranges", placeholder: "ex. 1-3,4,5-end" });
    host.append(
      h("p", { class: "lead" }, "Împărțiți documentul în mai multe fișiere (ZIP) sau reorganizați paginile."),
      h("div", { class: "card" },
        h("h3", null, "Împarte în fișiere"),
        h("label", { class: "field" }, "Intervale de pagini", rangesInp),
        h("p", { class: "hint" }, "Fiecare interval devine un fișier separat; rezultatul este o arhivă ZIP. „end” = ultima pagină."),
        h("div", { class: "actions" }, h("button", { class: "btn primary", id: "split-btn" }, "Împarte"))),
      h("div", { class: "card" },
        h("h3", null, "Reorganizează paginile"),
        h("p", { class: "hint" }, "Rotire, ștergere, mutare sau inserare de pagini, aplicate pe documentul curent."),
        h("div", { class: "actions org-ops" },
          h("button", { class: "btn small", onclick: () => addOp({ type: "rotate", page: null, angle: 90 }) }, "↻ Rotește tot 90°"),
          h("button", { class: "btn small", onclick: () => { if (D.info.pages <= 1) { toast("Documentul are o singură pagină.", "warn"); return; } addOp({ type: "delete_page", page: D.page }); } }, "Șterge pagina curentă"),
          h("button", { class: "btn small", onclick: () => addOp({ type: "insert_blank", at: D.page + 1 }) }, "Pagină goală după cea curentă")),
        editorOpsBlock()));
    $("#split-btn", host).addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!D.file) throw new Error("Deschideți întâi un document PDF.");
      const ranges = rangesInp.value.trim();
      if (!ranges) throw new Error("Introduceți intervalele de pagini, de ex. 1-3,4,5-end.");
      const { blob, filename } = await api("/api/pdf/split", { body: fd({ file: D.file, ranges }), as: "blob" });
      saveBlob(blob, filename || "impartit.zip");
      toast("Documentul a fost împărțit (arhivă ZIP).", "ok");
    }));
    return { el: host, mode: "none", needsDoc: true, show() { renderOps(); }, docChanged() { renderOps(); } };
  }

  function buildCompress() {
    const host = h("div", { class: "panel" });
    const result = h("div", { id: "compress-result" });
    host.append(
      h("p", { class: "lead" }, "Reduceți dimensiunea documentului PDF deschis. Rezultatul devine documentul curent."),
      h("div", { class: "actions" }, h("button", { class: "btn primary block", id: "compress-btn" }, "Comprimă")), result);
    $("#compress-btn", host).addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!D.file) throw new Error("Deschideți întâi un document PDF.");
      const before = D.file.size;
      const { blob, filename } = await api("/api/pdf/compress", { body: fd({ file: D.file }), as: "blob" });
      saveBlob(blob, filename || "comprimat.pdf");
      const after = blob.size;
      const pct = before ? Math.round((1 - after / before) * 100) : 0;
      const name = D.file.name;
      const file = new File([blob], name, { type: "application/pdf" });
      await viewer.setFile(file, { keepPage: true });
      result.replaceChildren(h("div", { class: "alert " + (pct > 0 ? "ok" : "warn") + " mt" },
        `Dimensiune: ${fmtSize(before)} → ${fmtSize(after)}` + (pct > 0 ? ` (−${pct}%)` : " (documentul era deja optimizat)")));
      toast("Documentul a fost comprimat.", "ok");
    }));
    return { el: host, mode: "none", needsDoc: true, show() { result.replaceChildren(); }, docChanged() { result.replaceChildren(); } };
  }

  function buildExtract() {
    const host = h("div", { class: "panel" });
    const out = h("textarea", { id: "text-out", class: "text-out", readonly: true, placeholder: "Textul extras va apărea aici." });
    const copyBtn = h("button", { class: "btn", id: "text-copy", disabled: true }, "Copiază");
    const saveBtn = h("button", { class: "btn", id: "text-save", disabled: true }, "Salvează .txt");
    host.append(
      h("p", { class: "lead" }, "Extrageți textul din documentul PDF deschis."),
      h("div", { class: "actions" }, h("button", { class: "btn primary", id: "text-btn" }, "Extrage"), copyBtn, saveBtn),
      out);
    $("#text-btn", host).addEventListener("click", (e) => busy(e.currentTarget, async () => {
      if (!D.file) throw new Error("Deschideți întâi un document PDF.");
      const res = await api("/api/pdf/text", { body: fd({ file: D.file }) });
      out.value = res.text || "";
      copyBtn.disabled = saveBtn.disabled = !out.value;
      if (!out.value.trim()) toast("Documentul nu conține text extractibil (posibil scanat).", "warn");
    }));
    copyBtn.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(out.value); toast("Text copiat.", "ok"); }
      catch (_) { out.select(); document.execCommand("copy"); toast("Text copiat.", "ok"); }
    });
    saveBtn.addEventListener("click", () => {
      const stem = (D.file && D.file.name.replace(/\.pdf$/i, "")) || "text";
      saveBlob(new Blob([out.value], { type: "text/plain;charset=utf-8" }), stem + ".txt");
    });
    return { el: host, mode: "none", needsDoc: true, show() {}, docChanged() { out.value = ""; copyBtn.disabled = saveBtn.disabled = true; } };
  }

  const BUILDERS = {
    esign: buildEsign, validate: buildValidate, edittext: buildEditText, edit: buildEdit,
    export_word: buildExportWord, create_pdf: buildCreatePdf, combine: buildCombine,
    organize: buildOrganize, compress: buildCompress, extract: buildExtract,
  };

  function getPanel(id) {
    if (!panelCache[id]) {
      panelCache[id] = BUILDERS[id]();
      onDocChange(() => { try { panelCache[id].docChanged(); } catch (_) {} });
    }
    return panelCache[id];
  }

  // =================================================================== BARA DE INSTRUMENTE (rail) + navigare
  const ICONS = {
    pen: '<path d="M4 20h4L19 9l-4-4L4 16v4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M14 6l4 4" stroke="currentColor" stroke-width="2"/>',
    check: '<path d="M4 7l5 5 11-11" transform="translate(0 4)" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
    text: '<path d="M5 5h14M12 5v14M8 19h8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    tools: '<path d="M14 7a4 4 0 00-5.2 5.2L3 18v3h3l5.8-5.8A4 4 0 0017 10l-3 3-2-2 3-3a4 4 0 00-1-1z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    word: '<rect x="4" y="3" width="16" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 8l1.5 8L12 10l2.5 6L16 8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
    create: '<rect x="5" y="3" width="14" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 9v6M9 12h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    combine: '<rect x="3" y="4" width="11" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><rect x="9" y="7" width="11" height="14" rx="2" fill="var(--surface)" stroke="currentColor" stroke-width="2"/>',
    pages: '<rect x="4" y="3" width="10" height="13" rx="1.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M17 8h3v13H9v-3" fill="none" stroke="currentColor" stroke-width="2"/>',
    compress: '<path d="M12 3v7m0 0l-3-3m3 3l3-3M12 21v-7m0 0l-3 3m3-3l3 3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    extract: '<path d="M5 4h9l5 5v11H5z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M8 13h8M8 16h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    flow: '<circle cx="6" cy="6" r="2.5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="18" cy="12" r="2.5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="6" cy="18" r="2.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 7l8 4M8 17l8-4" stroke="currentColor" stroke-width="2"/>',
    gear: '<circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.5 4.5l2 2M17.5 17.5l2 2M19.5 4.5l-2 2M6.5 17.5l-2 2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  };
  function icon(name) {
    const span = h("span", { class: "ti-ico" });
    span.innerHTML = `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">${ICONS[name] || ""}</svg>`;
    return span;
  }

  const RAIL = [
    { id: "esign", label: "Semnează electronic", group: "semnare", icon: "pen" },
    { id: "validate", label: "Validează semnături", group: "semnare", icon: "check" },
    { id: "edittext", label: "Editează textul", group: "editeaza", icon: "text" },
    { id: "edit", label: "Instrumente de editare", group: "editeaza", icon: "tools" },
    { id: "export_word", label: "Export în Word", group: "conversie", icon: "word" },
    { id: "create_pdf", label: "Creează PDF din Word/Office", group: "conversie", icon: "create" },
    { id: "combine", label: "Combină fișiere", group: "conversie", icon: "combine" },
    { id: "organize", label: "Organizează / Împarte pagini", group: "editeaza", icon: "pages" },
    { id: "compress", label: "Comprimă", group: "editeaza", icon: "compress" },
    { id: "extract", label: "Extrage text", group: "editeaza", icon: "extract" },
    // „Fluxuri de semnare" și „Setări" sunt ascunse din bară (dezactivate la cerere).
  ];

  let activeTab = "all";

  function buildRail() {
    const rail = $("#toolrail");
    rail.replaceChildren(...RAIL.map((t) => {
      const item = h("button", { class: "tool-item", "data-tool": t.id, "data-group": t.group || "", title: t.label },
        icon(t.icon), h("span", { class: "ti-label" }, t.label));
      item.addEventListener("click", () => openTool(t.id));
      return item;
    }));
  }

  function filterRail() {
    $$(".tool-item", $("#toolrail")).forEach((it) => {
      const g = it.dataset.group;
      const q = ($("#tool-search").value || "").trim().toLowerCase();
      const tabOk = activeTab === "all" || activeTab === "citeste" || g === activeTab;
      const searchOk = !q || it.textContent.toLowerCase().includes(q);
      it.hidden = !(tabOk && searchOk);
    });
  }

  function setTab(tab) {
    activeTab = tab;
    $$(".menutab", $("#menutabs")).forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    filterRail();
    if (tab === "citeste") closePanel();
  }

  function closePanel() {
    $("#rightpanel").hidden = true;
    document.body.classList.remove("panel-open");
    D.tool = null;
    $$(".tool-item", $("#toolrail")).forEach((b) => b.classList.remove("active"));
    $("#vw-tool-label").textContent = "";
    viewer.setInteraction("none");
    if (D.textEditMode) setTextEdit(false);
  }

  function openScreen(name) {
    $$(".screen").forEach((s) => { s.hidden = s.id !== "screen-" + name; });
    document.body.classList.add("screen-open");
    if (name === "fluxuri") initFluxuri();
    if (name === "setari") initSetari();
  }
  function closeScreens() { $$(".screen").forEach((s) => s.hidden = true); document.body.classList.remove("screen-open"); }

  function openTool(id, opts) {
    const meta = RAIL.find((t) => t.id === id);
    if (!meta) return;
    if (meta.screen) {
      $$(".tool-item", $("#toolrail")).forEach((b) => b.classList.toggle("active", b.dataset.tool === id));
      openScreen(meta.screen);
      return;
    }
    closeScreens();
    const panel = getPanel(id);
    if (panel.needsDoc && !D.file) {
      $("#rightpanel").hidden = false;
      document.body.classList.add("panel-open");
      $("#rp-title").textContent = meta.label;
      rpBody().replaceChildren(h("div", { class: "panel" },
        h("div", { class: "alert warn" }, "Acest instrument necesită un document deschis."),
        h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: () => $("#open-btn").click() }, "Deschide un PDF"))));
      $$(".tool-item", $("#toolrail")).forEach((b) => b.classList.toggle("active", b.dataset.tool === id));
      D.tool = id;
      return;
    }
    D.tool = id;
    $$(".tool-item", $("#toolrail")).forEach((b) => b.classList.toggle("active", b.dataset.tool === id));
    $("#rightpanel").hidden = false;
    document.body.classList.add("panel-open");
    $("#rp-title").textContent = meta.label;
    rpBody().replaceChildren(panel.el);
    $("#vw-tool-label").textContent = meta.label;
    viewer.setInteraction(panel.mode || "none");
    try { panel.show(opts); } catch (e) { console.error(e); }
  }

  // =================================================================== FLUXURI (ecran dedicat)
  const WF_STATUS = { draft: ["Ciornă", ""], in_progress: ["În desfășurare", "info"], completed: ["Finalizat", "ok"], cancelled: ["Anulat", "err"] };
  const SIGNER_STATUS = { pending: ["În așteptare", ""], sent: ["Trimis spre semnare", "info"], signed: ["Semnat", "ok"], rejected: ["Respins", "err"] };
  const EVENT_KIND = { created: "creat", sent: "trimis", signed: "semnat", warning: "avertisment", error: "eroare", rejected: "respins", completed: "finalizat", cancelled: "anulat", reminder: "reamintire" };
  const statusBadge = (map, s) => { const [t, c] = map[s] || [s || "?", ""]; return h("span", { class: "badge " + c }, t); };

  let wfSigners = [];
  let wfDetailId = null;
  let wfInited = false;

  function initFluxuri() {
    if (!wfInited) {
      wfInited = true;
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
      function resetCreate() { wfSigners = [{ name: "", email: "" }]; $("#wf-name").value = ""; $("#wf-message").value = ""; drop.clear(); renderSigners(); }
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
        const wf = await api("/api/workflows", { body: fd({ file: drop.file, name, signers: JSON.stringify(signers), message: $("#wf-message").value, start: $("#wf-start").checked ? "true" : "false" }) });
        toast("Fluxul a fost creat" + ($("#wf-start").checked ? " și pornit." : "."), "ok");
        $("#wf-create").hidden = true;
        resetCreate();
        await loadWorkflows();
        openWorkflow(wf.id);
      }));
    }
    if (wfDetailId == null) loadWorkflows().catch((e) => toast(e.message, "err"));
  }

  function renderInboxResults(box, results) {
    box.replaceChildren();
    if (!results || !results.length) { box.append(h("div", { class: "alert" }, "Nu există mesaje noi pentru fluxurile de semnare.")); return; }
    box.append(h("div", { class: "card" },
      h("h3", null, `Rezultat verificare inbox (${results.length} mesaj${results.length === 1 ? "" : "e"})`),
      h("ul", { class: "signer-steps" }, results.map((r) => h("li", null,
        h("span", { class: "badge " + (r.ok ? "ok" : "err") }, r.ok ? "Importat" : "Eroare"),
        h("div", null,
          h("div", null, h("strong", null, `Flux #${r.workflow_id}`), ` – ${r.subject || ""}`),
          h("div", { class: "hint" }, `De la: ${r.sender || "?"}${r.filename ? " · " + r.filename : ""}`),
          r.ok && r.report ? h("div", null, r.report.message || "") : null,
          r.ok && r.report && r.report.warnings && r.report.warnings.length ? h("ul", { class: "hint" }, r.report.warnings.map((w) => h("li", null, w))) : null,
          r.error ? h("div", { class: "hint", style: { color: "var(--err)" } }, r.error) : null)))),
      h("button", { class: "btn small", onclick: () => box.replaceChildren() }, "Închide")));
  }

  async function loadWorkflows() {
    const box = $("#wf-list");
    const list = await api("/api/workflows");
    if (!list.length) { box.replaceChildren(h("div", { class: "card empty" }, "Nu există fluxuri de semnare. Apăsați „Flux nou” pentru a crea unul.")); return; }
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

  function showWfList() { wfDetailId = null; $("#wf-detail-view").hidden = true; $("#wf-list-view").hidden = false; loadWorkflows().catch((e) => toast(e.message, "err")); }

  async function openWorkflow(id) {
    try {
      const wf = await api(`/api/workflows/${id}`);
      wfDetailId = id;
      renderWorkflowDetail(wf);
      $("#wf-list-view").hidden = true;
      $("#wf-detail-view").hidden = false;
      $("#screen-fluxuri").scrollTop = 0;
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
          actBtn("Descarcă documentul curent", "", async () => { const { blob, filename } = await api(`/api/workflows/${wf.id}/document`, { as: "blob" }); saveBlob(blob, filename || wf.filename); }),
          wf.status === "draft" ? actBtn("Pornește fluxul", "primary", async () => { refresh(await api(`/api/workflows/${wf.id}/start`, { method: "POST" })); toast("Fluxul a fost pornit.", "ok"); }) : null,
          active ? actBtn("Trimite reamintire", "", async () => { refresh(await api(`/api/workflows/${wf.id}/remind`, { method: "POST" })); toast("Reamintirea a fost trimisă.", "ok"); }) : null,
          wf.status === "draft" || active ? actBtn("Anulează fluxul", "danger", async () => { if (!window.confirm("Sigur anulați acest flux de semnare?")) return; refresh(await api(`/api/workflows/${wf.id}/cancel`, { method: "POST" })); toast("Fluxul a fost anulat.", "ok"); }) : null,
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
          h("div", { class: "when" }, fmtDate(e.ts), e.kind ? " · " + (EVENT_KIND[e.kind] || e.kind) : ""),
          h("div", { style: e.kind === "error" || e.kind === "rejected" ? { color: "var(--err)" } : e.kind === "warning" ? { color: "var(--warn)" } : null }, e.message))))
        : h("p", { class: "muted" }, "Niciun eveniment.")));

    v.replaceChildren(...blocks);
  }

  // =================================================================== SETĂRI (ecran dedicat)
  const PRESETS = {
    gmail: { smtp_host: "smtp.gmail.com", smtp_port: 465, smtp_tls: "ssl", imap_host: "imap.gmail.com", imap_port: 993 },
    outlook: { smtp_host: "smtp.office365.com", smtp_port: 587, smtp_tls: "starttls", imap_host: "outlook.office365.com", imap_port: 993 },
    yahoo: { smtp_host: "smtp.mail.yahoo.com", smtp_port: 465, smtp_tls: "ssl", imap_host: "imap.mail.yahoo.com", imap_port: 993 },
  };
  let setariInited = false;
  function initSetari() {
    if (setariInited) return;
    setariInited = true;
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
      if (user) { if (!el("imap_user").value) el("imap_user").value = user; if (!el("from_email").value) el("from_email").value = user; }
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
    $("#settings-save").addEventListener("click", (e) => busy(e.currentTarget, async () => { await save(); toast("Setările au fost salvate.", "ok"); }));
    const test = (btn, url) => busy(btn, async () => { await save(); const r = await api(url, { method: "POST" }); toast(r.message || (r.ok ? "Conexiune reușită." : "Conexiunea a eșuat."), r.ok ? "ok" : "err"); });
    $("#test-smtp").addEventListener("click", (e) => test(e.currentTarget, "/api/settings/test-smtp"));
    $("#test-imap").addEventListener("click", (e) => test(e.currentTarget, "/api/settings/test-imap"));
  }

  // =================================================================== deschidere document
  const pdfPicker = h("input", { type: "file", accept: ".pdf,application/pdf", style: { display: "none" } });
  document.body.append(pdfPicker);
  pdfPicker.addEventListener("change", () => {
    const f = pdfPicker.files[0];
    pdfPicker.value = "";
    if (f && isPdf(f)) openDocument(f);
    else if (f) toast("Selectați un fișier PDF.", "warn");
  });

  async function openDocument(file) {
    try {
      closeScreens();
      D.ops = [];
      viewer.resetSig();
      clearTextEditOverlay();
      await viewer.setFile(file);
      toast("Document deschis.", "ok");
      if (D.tool) openTool(D.tool); // re-randează panoul curent pentru noul document
    } catch (e) { toast(e.message, "err"); }
  }

  // =================================================================== pornire
  buildRail();

  dropZone($("#empty-drop"), { validate: isPdf, title: "Trageți aici PDF-ul", sub: "sau faceți clic pentru a alege", onChange: (files) => { if (files[0]) openDocument(files[0]); } });

  // dialog certificat de test (partajat de panoul E-Sign)
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
      if (esignSetPfx && esignSetPfx(file, data.password)) {
        toast("Certificatul de test a fost descărcat și selectat în formularul de semnare.", "ok");
      } else {
        toast("Certificatul de test a fost descărcat.", "ok");
      }
      $("#testcert-dialog").close();
    });
  });

  $("#open-btn").addEventListener("click", () => pdfPicker.click());
  $("#download-btn").addEventListener("click", () => { if (D.file) saveBlob(D.file, D.file.name); });

  $("#rail-toggle").addEventListener("click", () => { document.body.classList.toggle("rail-collapsed"); });
  $("#rp-close").addEventListener("click", closePanel);
  $("#app-home").addEventListener("click", (e) => { e.preventDefault(); closePanel(); closeScreens(); setTab("all"); });

  $$(".menutab", $("#menutabs")).forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
  $("#tool-search").addEventListener("input", filterRail);

  // vizualizator – bară de instrumente
  $("#vw-prev").addEventListener("click", () => viewer.goPage(D.page - 1));
  $("#vw-next").addEventListener("click", () => viewer.goPage(D.page + 1));
  $("#vw-pagenum").addEventListener("change", (e) => viewer.goPage(Number(e.target.value) - 1));
  $("#vw-zoom").addEventListener("change", (e) => viewer.setZoom(e.target.value).catch((err) => toast(err.message, "err")));
  $("#vw-zoomin").addEventListener("click", () => viewer.zoomStep(1).catch(() => {}));
  $("#vw-zoomout").addEventListener("click", () => viewer.zoomStep(-1).catch(() => {}));
  $("#thumbs-toggle").addEventListener("click", () => { document.body.classList.toggle("thumbs-hidden"); setTimeout(() => viewer.render().catch(() => {}), 60); });

  // navigare la taste în vizualizator
  document.addEventListener("keydown", (e) => {
    if (!D.info || !document.body.classList.contains("panel-open") && D.tool) { /* permite oricum */ }
    if (!D.info) return;
    const a = document.activeElement;
    if (a && (/INPUT|TEXTAREA|SELECT/.test(a.tagName) || a.isContentEditable)) return;
    if (!$("#viewer-doc").hidden && $$(".screen").every((s) => s.hidden)) {
      if (e.key === "ArrowRight" || e.key === "PageDown") viewer.goPage(D.page + 1);
      if (e.key === "ArrowLeft" || e.key === "PageUp") viewer.goPage(D.page - 1);
      if (e.key === "Escape" && D.editTool) setEditTool(D.editTool);
    }
  });

  // previne deschiderea fișierelor plasate în afara zonelor de încărcare
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());

  setTab("all");
})();
