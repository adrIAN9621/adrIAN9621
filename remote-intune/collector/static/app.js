"use strict";

// Colector RustDesk – interfață tehnician. Fără dependențe externe (CSP self).

let devices = [];

function fmtTimestamp(epoch) {
  if (!epoch) return "—";
  const d = new Date(epoch * 1000);
  return d.toLocaleString("ro-RO", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit"
  });
}

function ageBadge(epoch) {
  if (!epoch) return '<span class="age-badge age-old">necunoscut</span>';
  const mins = Math.floor((Date.now() / 1000 - epoch) / 60);
  let label, cls;
  if (mins < 60) { label = mins + " min"; cls = "age-fresh"; }
  else if (mins < 60 * 24) { label = Math.floor(mins / 60) + " h"; cls = "age-fresh"; }
  else {
    const days = Math.floor(mins / (60 * 24));
    label = days + (days === 1 ? " zi" : " zile");
    cls = days <= 7 ? "age-stale" : "age-old";
  }
  return '<span class="age-badge ' + cls + '">' + label + '</span>';
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function renderDevices() {
  const q = document.getElementById("search").value.trim().toLowerCase();
  const body = document.getElementById("devices-body");
  const empty = document.getElementById("devices-empty");
  body.innerHTML = "";
  const filtered = devices.filter(function (dev) {
    if (!q) return true;
    return (dev.hostname + " " + dev.id + " " + dev.id_formatat + " " + (dev.user || ""))
      .toLowerCase().includes(q);
  });
  empty.hidden = filtered.length !== 0;
  for (const dev of filtered) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      "<td>" + esc(dev.hostname || "—") + "</td>" +
      '<td class="mono">' + esc(dev.id_formatat) + "</td>" +
      "<td>" + esc(dev.user || "—") + "</td>" +
      "<td>" + esc(fmtTimestamp(dev.last_reported)) + "</td>" +
      "<td>" + ageBadge(dev.last_reported) + "</td>" +
      '<td class="pw-cell"></td>';
    const cell = tr.querySelector(".pw-cell");
    const reveal = document.createElement("button");
    reveal.type = "button";
    reveal.className = "btn-reveal";
    reveal.textContent = "Arată parola";
    reveal.addEventListener("click", function () { revealPassword(dev.id, cell); });
    cell.appendChild(reveal);
    body.appendChild(tr);
  }
}

async function revealPassword(id, cell) {
  try {
    const resp = await fetch("/api/devices/" + encodeURIComponent(id) + "/password", {
      headers: { "Accept": "application/json" }
    });
    if (resp.status === 401) { window.location.href = "/"; return; }
    if (!resp.ok) { cell.textContent = "Eroare la obținerea parolei"; return; }
    const data = await resp.json();
    cell.innerHTML = "";
    const span = document.createElement("span");
    span.className = "pw-value";
    span.textContent = data.password || "(gol)";
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "btn-copy";
    copy.textContent = "Copiază";
    copy.addEventListener("click", function () {
      navigator.clipboard.writeText(data.password || "").then(function () {
        copy.textContent = "Copiat!";
        setTimeout(function () { copy.textContent = "Copiază"; }, 1500);
      }).catch(function () { copy.textContent = "Eșuat"; });
    });
    cell.appendChild(span);
    cell.appendChild(document.createTextNode(" "));
    cell.appendChild(copy);
  } catch (e) {
    cell.textContent = "Eroare de rețea";
  }
}

async function loadDevices() {
  const resp = await fetch("/api/devices", { headers: { "Accept": "application/json" } });
  if (resp.status === 401) { window.location.href = "/"; return; }
  const data = await resp.json();
  devices = data.devices || [];
  renderDevices();
}

async function loadAudit() {
  const resp = await fetch("/api/audit", { headers: { "Accept": "application/json" } });
  if (resp.status === 401) { window.location.href = "/"; return; }
  const data = await resp.json();
  const body = document.getElementById("audit-body");
  const empty = document.getElementById("audit-empty");
  body.innerHTML = "";
  const rows = data.audit || [];
  empty.hidden = rows.length !== 0;
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      "<td>" + esc(fmtTimestamp(r.ts)) + "</td>" +
      "<td>" + esc(r.username) + "</td>" +
      '<td class="mono">' + esc(r.id_formatat) + "</td>" +
      "<td>" + esc(r.hostname || "—") + "</td>" +
      "<td>" + esc(r.ip) + "</td>";
    body.appendChild(tr);
  }
}

function switchTab(tab) {
  document.querySelectorAll(".nav-item").forEach(function (b) {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
  document.getElementById("tab-devices").classList.toggle("active", tab === "devices");
  document.getElementById("tab-audit").classList.toggle("active", tab === "audit");
  document.getElementById("page-title").textContent =
    tab === "audit" ? "Jurnal audit – dezvăluiri de parolă" : "Dispozitive RustDesk";
  if (tab === "audit") loadAudit();
}

document.addEventListener("DOMContentLoaded", function () {
  document.getElementById("search").addEventListener("input", renderDevices);
  document.getElementById("refresh").addEventListener("click", loadDevices);
  document.querySelectorAll(".nav-item").forEach(function (b) {
    b.addEventListener("click", function () { switchTab(b.dataset.tab); });
  });
  loadDevices();
});
