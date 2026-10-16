// Pagina dispecerului: hartă live, echipaje, cereri de înlocuire, personal, pontaj.
api.key = "dispecer-token";
let state = null, map = null, layers = {}, tab = "live", people = [], pontaj = [];
const COLORS = { verde: "#1f9d55", galben: "#e0a000", rosu: "#d33a2c", gri: "#7d8a9a" };

async function login() {
  try {
    const r = await api.post("/api/login", { parola: $("#pass").value });
    api.save(r.token);
    start();
  } catch (e) { $("#login-err").textContent = e.message; }
}

function start() {
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  initMap();
  refresh();
  setInterval(refresh, 2000);
}

// ------------------------------------------------------------------- hartă
function initMap() {
  if (!window.L) { $("#map").innerHTML = '<p class="muted" style="padding:16px">Harta nu se poate încărca (fără internet). Datele sunt în tabel.</p>'; return; }
  map = L.map("map", { zoomControl: true }).setView([45.9, 25.0], 7);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: "© OpenStreetMap",
  }).addTo(map);
  layers.stations = L.layerGroup().addTo(map);
  layers.routes = L.layerGroup().addTo(map);
  layers.trains = L.layerGroup().addTo(map);
}

function drawMap() {
  if (!map) return;
  const st = state.stations;
  if (!layers.stationsDrawn) {
    for (const s of Object.values(st)) {
      L.circleMarker([s.lat, s.lon], { radius: 3, color: "#5e6b7c", weight: 1, fillOpacity: .8 })
        .bindTooltip(s.name).addTo(layers.stations);
    }
    layers.stationsDrawn = true;
  }
  layers.routes.clearLayers();
  layers.trains.clearLayers();
  const handover = Object.fromEntries(state.requests.filter(r => r.station).map(r => [r.train, r]));
  for (const t of state.trains) {
    if (t.status === "sosit") continue;
    const color = COLORS[t.nivel];
    L.polyline(t.route.filter(c => st[c]).map(c => [st[c].lat, st[c].lon]), { color, weight: 2, opacity: .35, dashArray: "4 6" }).addTo(layers.routes);
    const icon = L.divIcon({
      className: "",
      html: `<div style="background:${color};color:#fff;font-weight:700;font-size:11px;padding:2px 6px;border-radius:6px;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);white-space:nowrap">${esc(t.train)}</div>`,
      iconAnchor: [22, 10],
    });
    const crew = t.crew.map(c => `${esc(c.role)}: ${esc(c.name)} – ${hours(c.ore_ramase)} rămase`).join("<br>");
    L.marker([t.lat, t.lon], { icon }).bindPopup(
      `<b>Tren ${esc(t.train)}</b> ${esc(t.from)} → ${esc(t.to)}<br>Următoarea: ${esc(t.next || "–")} · întârziere ${t.delay} min<br>${crew}`
    ).addTo(layers.trains);
    const h = handover[t.train];
    if (h) {
      const s = st[h.station];
      if (s) L.circleMarker([s.lat, s.lon], { radius: 9, color, weight: 3, fill: false })
        .bindTooltip(`Schimb tren ${esc(t.train)} în ${esc(s.name)} la ${hm(h.eta)}`).addTo(layers.routes);
    }
  }
}

// ------------------------------------------------------------- randare
function crewCell(c) {
  if (!c) return '<span class="muted">–</span>';
  const pct = Math.max(0, Math.min(100, c.ore_lucrate / (c.ore_lucrate + Math.max(c.ore_ramase, 0)) * 100));
  return `${esc(c.name)}<div class="small muted">lucrat ${hours(c.ore_lucrate)} · rămas <b>${hours(c.ore_ramase)}</b> (până la ${hm(c.program_end)})</div>
    <div class="bar ${c.nivel}"><span style="width:${pct}%"></span></div>`;
}

function renderTrains() {
  const rows = state.trains.slice().sort((a, b) => "rosugalbenverdegri".indexOf(a.nivel) - "rosugalbenverdegri".indexOf(b.nivel));
  $("#trains").innerHTML = rows.map(t => {
    const mec = t.crew.find(c => c.role === "mecanic"), aj = t.crew.find(c => c.role === "ajutor");
    const pos = t.status === "sosit" ? `sosit în ${esc(t.to)}` : t.status === "neplecat" ? "neplecat"
      : t.status === "in_statie" ? `în stația ${esc(t.last)}` : `${esc(t.last)} → ${esc(t.next)} · ${t.speed} km/h`;
    return `<tr class="clickable" data-train="${esc(t.train)}">
      <td><b>${esc(t.train)}</b><br>${badge(t.nivel, t.nivel === "gri" ? "fără echipaj" : t.nivel === "verde" ? "ok" : t.nivel === "galben" ? "alertă 3h" : "critic")}</td>
      <td>${esc(t.from)} → ${esc(t.to)}<div class="small muted">sosire estimată ${hm(t.eta_final)}</div></td>
      <td>${pos}</td>
      <td>${t.delay ? `+${t.delay} min` : "la timp"}</td>
      <td>${crewCell(mec)}</td><td>${crewCell(aj)}</td></tr>`;
  }).join("");
  $$("#trains tr").forEach(tr => tr.onclick = () => {
    const t = state.trains.find(x => x.train === tr.dataset.train);
    if (map && t) map.setView([t.lat, t.lon], 9);
  });
}

function renderRequests() {
  const reqs = state.requests;
  if (!reqs.length) { $("#requests").innerHTML = '<p class="muted">Nicio cerere activă. Toate echipajele sunt în program.</p>'; return; }
  $("#requests").innerHTML = reqs.map(r => {
    let body = "";
    if (r.status === "oferta" && r.offer) {
      body = `Ofertă la <b>${esc(r.offer.person)}</b> (${Math.round(r.offer.km)} km) · expiră în ${r.offer.expira_sec}s<br>
              Schimb propus: ${esc(r.station_name)} la ${hm(r.eta)}`;
    } else if (r.status === "acceptat") {
      body = `<b>${esc(r.person_name)}</b> vine în <b>${esc(r.station_name)}</b> · trenul ajunge la ${hm(r.eta)}`;
    } else if (r.note === "fara_statie") {
      body = `<span class="ev-critic">Trenul nu mai are stații de schimb până la destinație.</span>`;
    } else {
      body = `<span class="ev-critic">Niciun ${esc(r.role)} disponibil în rază.</span> Alege manual.`;
    }
    return `<div class="req ${esc(r.status)}">
      <div class="top"><b>Tren ${esc(r.train)} · ${esc(r.role)}</b>${badge(r.status)}</div>
      <div class="small muted">${esc(r.outgoing?.name)} termină la ${hm(r.outgoing?.program_end)} · încercări: ${r.incercari}</div>
      <div style="margin-top:6px">${body}</div>
      <div class="actions">
        ${r.status !== "acceptat" ? `<button class="btn" data-cand="${r.id}">Candidați</button>` : ""}
        <button class="btn danger" data-cancel="${r.id}">Anulează</button>
      </div></div>`;
  }).join("");
  $$("[data-cand]").forEach(b => b.onclick = () => showCandidates(+b.dataset.cand));
  $$("[data-cancel]").forEach(b => b.onclick = async () => {
    if (!confirm("Anulezi cererea de înlocuire?")) return;
    await api.post(`/api/cereri/${b.dataset.cancel}/anuleaza`); refresh();
  });
}

async function showCandidates(id) {
  const r = state.requests.find(x => x.id === id);
  const list = await api.get(`/api/cereri/${id}/candidati`);
  $("#modal-body").innerHTML = `<h2>Candidați – tren ${esc(r.train)} (${esc(r.role)})</h2>
    <p class="small muted">Sortați după distanța de la domiciliu la stația de schimb. Doar oamenii disponibili, care nu au refuzat deja.</p>
    ${list.length ? `<div class="table-wrap"><table><thead><tr><th>Nume</th><th>Stație schimb</th><th>Distanță</th><th>Deplasare</th><th>Rezervă</th><th></th></tr></thead><tbody>
    ${list.map(c => `<tr><td>${esc(c.name)}</td><td>${esc(c.station_name)}<div class="small muted">tren la ${hm(c.eta)}</div></td>
      <td>${c.km} km</td><td>${c.travel_min} min</td>
      <td>${c.slack_min >= 0 ? c.slack_min + " min" : `<span class="ev-critic">trenul așteaptă ${-c.slack_min} min</span>`}</td>
      <td><button class="btn primary" data-offer="${esc(c.person_id)}">Oferă</button></td></tr>`).join("")}
    </tbody></table></div>` : '<p>Nu există candidați disponibili.</p>'}
    <div class="actions" style="margin-top:12px"><button class="btn" id="close-modal">Închide</button></div>`;
  $("#modal").classList.remove("hidden");
  $("#close-modal").onclick = () => $("#modal").classList.add("hidden");
  $$("[data-offer]").forEach(b => b.onclick = async () => {
    try { await api.post(`/api/cereri/${id}/ofera`, { person_id: b.dataset.offer }); toast("Ofertă trimisă"); }
    catch (e) { toast(e.message); }
    $("#modal").classList.add("hidden"); refresh();
  });
}

function renderEvents() {
  $("#events").innerHTML = state.events.map(e => `<div class="ev-${esc(e.kind)}"><b>${hm(e.t)}</b>${esc(e.text)}</div>`).join("");
}

function renderHeader() {
  $("#clock").textContent = new Date(state.now * 1000).toLocaleString("ro-RO", { weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  $("#source").textContent = { simulator: "SIMULATOR", fisiere: "TEST · date reale, doar citire", cmdpers: "TEST · CmdPers, doar citire", cmdpers_live: "CmdPers LIVE · doar citire, în umbră", inforu: "TEST · InfoRU, doar citire", inforu_live: "InfoRU LIVE · doar citire, în umbră", http: "LIVE" }[state.sursa] || state.sursa;
  const sp = $("#speed");
  sp.classList.toggle("hidden", state.sursa === "http" || state.sursa.endsWith("_live"));
  if (document.activeElement !== sp) sp.value = String(state.viteza);
  const c = state.personal;
  $("#counts").innerHTML = ["disponibil", "in_deplasare", "pe_tren", "pauza", "odihna", "indisponibil"]
    .map(k => `<span class="chip">${STATUS[k]}: ${c[k] || 0}</span>`).join("");
}

function renderPeople() {
  const q = $("#p-search").value.toLowerCase(), role = $("#p-role").value, st = $("#p-status").value;
  $("#people").innerHTML = people.filter(p =>
    (!q || (p.name + p.home_city + p.id).toLowerCase().includes(q)) && (!role || p.role === role) && (!st || p.status === st)
  ).map(p => `<tr><td>${esc(p.id)}</td><td>${esc(p.name)}${p.online ? ' <span class="badge b-verde">în aplicație</span>' : ""}</td>
    <td>${esc(p.role)}</td><td>${esc(p.home_city)}</td><td>${esc(p.phone)}</td>
    <td>${badge(p.status)}${p.status_until ? `<div class="small muted">până la ${dhm(p.status_until)}</div>` : ""}</td></tr>`).join("");
}

function renderPontaj() {
  const q = $("#pj-search").value.toLowerCase();
  $("#pontaj").innerHTML = pontaj.filter(p => !q || (p.tren + p.nume).toLowerCase().includes(q)).map(p => `<tr>
    <td><b>${esc(p.tren)}</b></td><td>${esc(p.nume)}</td><td>${esc(p.rol)}</td>
    <td>${esc(fmtIso(p.inceput))}<div class="small muted">${esc(p.statie_inceput)}</div></td>
    <td>${p.activ ? badge("pe_tren", "în curs") : esc(fmtIso(p.sfarsit))}<div class="small muted">${esc(p.statie_sfarsit || "")}</div></td>
    <td>${hours(p.ore)}</td><td>${p.km_deplasare != null ? `${Math.round(p.km_deplasare)} km · ${Math.round(p.min_deplasare)} min` : "–"}</td>
    <td class="small muted">${esc(p.sursa)}</td></tr>`).join("");
}

function fmtIso(s) { return s ? s.replace("T", " ").slice(5, 16) : "–"; }

async function refresh() {
  try {
    state = await api.get("/api/stare");
    renderHeader();
    if (tab === "live") { renderTrains(); renderRequests(); renderEvents(); drawMap(); }
    if (tab === "personal") { people = await api.get("/api/personal"); renderPeople(); }
    if (tab === "pontaj") { pontaj = await api.get("/api/pontaj"); renderPontaj(); }
  } catch (e) { console.warn(e); }
}

// ---------------------------------------------------------------- legături
$("#login-btn").onclick = login;
$("#pass").onkeydown = e => { if (e.key === "Enter") login(); };
$$(".tab").forEach(b => b.onclick = () => {
  tab = b.dataset.tab;
  $$(".tab").forEach(x => x.classList.toggle("active", x === b));
  $$("[data-panel]").forEach(p => p.classList.toggle("hidden", p.dataset.panel !== tab));
  if (tab === "live" && map) setTimeout(() => map.invalidateSize(), 50);
  refresh();
});
$("#speed").onchange = e => api.post("/api/ceas", { viteza: +e.target.value }).then(refresh);
["#p-search", "#p-role", "#p-status"].forEach(s => $(s).oninput = renderPeople);
$("#pj-search").oninput = renderPontaj;
$("#csv").onclick = e => { e.preventDefault(); location.href = "/api/pontaj.csv?token=" + encodeURIComponent(api.token); };
$("#modal").onclick = e => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); };

if (api.load()) start(); else $("#login").classList.remove("hidden");
