// Aplicația de telefon pentru mecanici / ajutori: disponibil → ofertă → accept → pontaj automat.
api.key = "mecanic-token";
let me = null, lastOffer = null, timer = null;

async function login() {
  try {
    const r = await api.post("/api/login", { id: $("#pid").value, pin: $("#pin").value });
    api.save(r.token);
    start();
  } catch (e) { $("#login-err").textContent = e.message; }
}

function start() {
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  refresh();
  timer = setInterval(refresh, 3000);
}

function alertOffer() {
  try { navigator.vibrate && navigator.vibrate([400, 200, 400, 200, 400]); } catch (e) {}
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [0, .35, .7].forEach(d => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 880; o.connect(g); g.connect(ctx.destination);
      g.gain.setValueAtTime(.2, ctx.currentTime + d);
      o.start(ctx.currentTime + d); o.stop(ctx.currentTime + d + .2);
    });
  } catch (e) {}
}

function renderOffer(o) {
  const box = $("#offer");
  if (!o) { box.classList.add("hidden"); lastOffer = null; return; }
  if (lastOffer !== o.id) { alertOffer(); lastOffer = o.id; }
  box.classList.remove("hidden");
  $("#offer-body").innerHTML = `
    <div class="title">Comandă nouă</div>
    <div class="train">Tren ${esc(o.train)}</div>
    <div class="countdown">Răspunde în ${o.expira_sec} s</div>
    <div class="card">
      <div class="kv">
        <span>Preiei în</span><span>${esc(o.station)}</span>
        <span>Trenul ajunge</span><span>${hm(o.eta)}${o.delay ? ` (întârziere ${o.delay} min)` : ""}</span>
        <span>Distanță de acasă</span><span>${Math.round(o.km)} km · ~${Math.round(o.travel_min)} min</span>
        <span>Pleci de acasă</span><span>${o.plecare_acasa < me.now ? "ACUM" : "până la " + hm(o.plecare_acasa)}</span>
        <span>Destinație tren</span><span>${esc(o.dest || "–")}</span>
      </div>
    </div>
    <div class="buttons">
      <button class="btn big" id="refuz">Refuz</button>
      <button class="btn big ok" id="accept">Accept</button>
    </div>`;
  $("#accept").onclick = () => answer(o.id, "accept");
  $("#refuz").onclick = () => answer(o.id, "refuz");
}

async function answer(id, what) {
  try { await api.post(`/api/oferte/${id}/${what}`); toast(what === "accept" ? "Comandă acceptată" : "Ai refuzat comanda"); }
  catch (e) { toast(e.message); }
  refresh();
}

function render() {
  const p = me.eu;
  $("#me-name").textContent = p.name;
  $("#me-sub").textContent = `${p.id} · ${p.role === "mecanic" ? "mecanic" : "ajutor mecanic"} · ${p.home_city}`;

  const t = $("#toggle"), locked = ["pe_tren", "in_deplasare"].includes(p.status) || (p.status === "odihna");
  t.classList.toggle("on", p.status === "disponibil" || p.status === "pauza");
  t.disabled = ["pe_tren", "in_deplasare"].includes(p.status);
  $("#avail-label").textContent = p.status === "disponibil" ? "Disponibil" : STATUS[p.status] ? STATUS[p.status][0].toUpperCase() + STATUS[p.status].slice(1) : p.status;
  $("#avail-sub").textContent = p.status === "disponibil" ? "Primești comenzi pentru trenurile din zonă"
    : p.status === "pauza" ? `Poți prelua a 2-a tură între ${hm(p.pauza_de_la + 2 * 3600)} și ${hm(p.status_until)}`
    : p.status === "odihna" ? `Odihnă până la ${dhm(p.status_until)}`
    : locked ? "Ești comandat" : "Nu primești comenzi";

  const c = me.comanda, cb = $("#comanda");
  cb.classList.toggle("hidden", !c);
  if (c) {
    const s = c.pozitie ? `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent("Gara " + c.station)}` : "#";
    cb.innerHTML = `<h2>Comanda ta</h2>
      <div class="big-num">Tren ${esc(c.train)}</div>
      <div class="kv">
        <span>Prezentare în</span><span>${esc(c.station)}</span>
        <span>Trenul ajunge</span><span>${hm(c.eta)}</span>
        <span>Pleci de acasă</span><span>${c.plecare_acasa < me.now ? "ACUM" : hm(c.plecare_acasa)}</span>
        <span>Distanță</span><span>${Math.round(c.km)} km</span>
      </div>
      <a class="btn primary big" style="display:block;text-align:center;text-decoration:none" href="${s}" target="_blank">Navighează la gară</a>
      <p class="small muted">Pontajul pornește automat când trenul ajunge în stație (InfoRU).</p>`;
  }

  const u = me.tura, tb = $("#tura");
  tb.classList.toggle("hidden", !u);
  if (u) {
    tb.innerHTML = `<h2>Pe tren</h2>
      <div class="big-num">Tren ${esc(u.train)}</div>
      <div class="kv">
        <span>Lucrat</span><span>${hours(u.ore_lucrate)}</span>
        <span>Rămas din program</span><span>${hours(u.ore_ramase)} (până la ${hm(u.program_end)})</span>
        <span>Următoarea stație</span><span>${esc(u.next || "–")}</span>
        <span>Destinație</span><span>${esc(u.dest || "–")}</span>
        <span>Întârziere</span><span>${u.delay ? u.delay + " min" : "la timp"}</span>
      </div>
      <div class="bar ${u.nivel}"><span style="width:${Math.min(100, u.ore_lucrate / (u.ore_lucrate + Math.max(0, u.ore_ramase)) * 100)}%"></span></div>
      ${u.schimb ? `<p>Ești schimbat în <b>${esc(u.schimb.station)}</b> la ${hm(u.schimb.eta)} de <b>${esc(u.schimb.name)}</b>.</p>`
        : u.nivel !== "verde" ? '<p class="small muted">Se caută înlocuitor…</p>' : ""}`;
  }

  $("#pontaj").innerHTML = me.pontaj.length ? `<table><thead><tr><th>Tren</th><th>Traseu</th><th>Ore</th></tr></thead><tbody>
    ${me.pontaj.map(p => `<tr><td><b>${esc(p.tren)}</b><div class="muted">${esc((p.inceput || "").replace("T", " ").slice(5, 16))}</div></td>
      <td>${esc(p.statie_inceput)} → ${p.activ ? "în curs" : esc(p.statie_sfarsit)}</td><td>${hours(p.ore)}</td></tr>`).join("")}
    </tbody></table>` : '<p class="muted">Încă nu ai ture înregistrate.</p>';

  renderOffer(me.oferta);
}

async function refresh() {
  try { me = await api.get("/api/eu"); render(); } catch (e) { console.warn(e); }
}

$("#login-btn").onclick = login;
$("#pin").onkeydown = e => { if (e.key === "Enter") login(); };
$("#logout").onclick = () => api.logout();
$("#toggle").onclick = async () => {
  try { await api.post("/api/eu/disponibil", { disponibil: me.eu.status !== "disponibil" }); }
  catch (e) { toast(e.message); }
  refresh();
};

if (api.load()) start(); else $("#login").classList.remove("hidden");
