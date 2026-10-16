// Funcții comune pentru pagina dispecerului și aplicația mecanicului.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function hm(t) {
  if (!t) return "–";
  return new Date(t * 1000).toLocaleTimeString("ro-RO", { hour: "2-digit", minute: "2-digit" });
}

function dhm(t) {
  if (!t) return "–";
  const d = new Date(t * 1000);
  return d.toLocaleDateString("ro-RO", { day: "2-digit", month: "2-digit" }) + " " + hm(t);
}

function hours(h) {
  if (h == null) return "–";
  const neg = h < 0; h = Math.abs(h);
  const H = Math.floor(h), M = Math.round((h - H) * 60);
  return (neg ? "-" : "") + H + "h" + String(M === 60 ? 0 : M).padStart(2, "0");
}

const STATUS = {
  disponibil: "disponibil", indisponibil: "indisponibil", in_deplasare: "în deplasare",
  pe_tren: "pe tren", odihna: "odihnă", cautare: "caută", oferta: "ofertă trimisă",
  acceptat: "acceptat", finalizat: "finalizat", anulat: "anulat",
};

function badge(status, label) {
  return `<span class="badge b-${esc(status)}">${esc(label || STATUS[status] || status)}</span>`;
}

function toast(msg) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

const api = {
  token: null,
  key: "token",
  async call(method, url, body) {
    const r = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json", ...(this.token ? { Authorization: "Bearer " + this.token } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (r.status === 401 && this.token) { this.logout(); throw new Error("Sesiune expirată"); }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || "Eroare " + r.status);
    return data;
  },
  get(url) { return this.call("GET", url); },
  post(url, body) { return this.call("POST", url, body || {}); },
  load() { try { this.token = localStorage.getItem(this.key); } catch (e) { this.token = null; } return this.token; },
  save(t) { this.token = t; try { localStorage.setItem(this.key, t); } catch (e) {} },
  logout() { this.token = null; try { localStorage.removeItem(this.key); } catch (e) {} location.reload(); },
};
