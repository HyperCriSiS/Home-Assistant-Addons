"use strict";
const modes = ["openai", "cloudflare"];
const stateNames = {
  ready: ["Bereit", "success", "Der lokale Tunnel ist verbunden."],
  starting: ["Startet", "warning", "Verbindung wird aufgebaut …"],
  retrying: ["Erneuter Versuch", "warning", "Verbindung wird wiederhergestellt …"],
  degraded: ["Eingeschränkt", "warning", "Die lokale Verbindung ist derzeit nicht bereit."],
  stale: ["Prüfung veraltet", "warning", "Der letzte Status ist nicht mehr aktuell."],
  stopped: ["Gestoppt", "neutral", "Der Tunnel ist gestoppt."],
  unavailable: ["Nicht erreichbar", "error", "Der Tunnel-Dienst antwortet nicht."],
  error: ["Fehler", "error", "Der Tunnel konnte nicht gestartet werden."]
};
const title = {mcp:"MCP-Endpunkt", "control-plane":"Steuerverbindung",
  "response-delivery":"Antwortübertragung", queue:"Warteschlange",
  proxy:"Proxy"};
let refreshing = false;
const busy = new Set();

async function api(path, opts) {
  const response = await fetch(path, {cache:"no-store", ...opts});
  if (!response.ok) throw Error("HTTP " + response.status);
  return response.json();
}
function label(s) {
  return stateNames[s] || ["Unbekannt", "neutral", "Kein eindeutiger Status verfügbar."];
}
function text(el, value) {
  el.textContent = String(value === undefined || value === null ? "–" : value);
}
function feedback(mode, message, error=false) {
  const el = document.querySelector("#t-" + mode + " .feedback");
  text(el, message);
  el.dataset.error = error ? "true" : "false";
}
function render(mode, state) {
  const card = document.getElementById("t-" + mode);
  const s = state || {};
  const [name, tone, summary] = label(s.state);
  const badge = card.querySelector(".badge");
  badge.dataset.tone = tone;
  text(badge, name);
  text(card.querySelector(".summary"), s.last_error || summary);
  text(card.querySelector('[data-field="configured"]'),
    typeof s.configured === "boolean" ? (s.configured ? "Ja" : "Nein") : "Unbekannt");
  text(card.querySelector('[data-field="connection"]'),
    s.transport_ready ? "Lokal bereit" : "Nicht bereit");
  text(card.querySelector('[data-field="route"]'), s.route || "–");
  text(card.querySelector('[data-field="age"]'),
    typeof s.health_age_seconds === "number" ? "vor " + s.health_age_seconds + " s" : "–");
  for (const button of card.querySelectorAll("button[data-action]")) {
    const action = button.dataset.action;
    button.disabled = busy.has(mode) ||
      (action === "start" && (!s.configured || s.requested)) ||
      (action === "stop" && !s.requested) ||
      (action === "reload" && s.state === "unavailable");
  }
}
function message(container, str) {
  container.replaceChildren(document.createTextNode(str));
}
function detailLine(name, detail, container) {
  const item = document.createElement("li");
  const strong = document.createElement("b");
  text(strong, name);
  const sub = document.createElement("span");
  text(sub, detail);
  item.append(strong, sub);
  container.append(item);
}
async function loadDetails(mode, kind) {
  const card = document.getElementById("t-" + mode);
  const section = card.querySelector('details[data-panel="' + kind + '"]');
  if (!section.open) return;
  const target = section.querySelector(kind === "diagnostics" ? "[data-diagnostics]" : "[data-logs]");
  try {
    const report = await api("api/" + (kind === "logs" ? "logs/" : "diagnostics/") + mode);
    if (!section.open) return;
    if (kind === "logs") {
      text(target, Array.isArray(report.lines) && report.lines.length ?
        report.lines.join("\n") : "Noch keine Protokolle vorhanden.");
      return;
    }
    if (report.note) { message(target, report.note); return; }
    const list = document.createElement("ul");
    list.className = "diag-lines";
    if (mode === "openai") {
      for (const [name, item] of Object.entries(report.components || {})) {
        if (!item || typeof item !== "object") continue;
        const status = [item.status, item.state, item.reason_code].filter(Boolean).join(" · ");
        detailLine(title[name] || name, status || "Keine Details", list);
      }
      if (!list.children.length) {
        message(target, "Noch keine Komponentendaten verfügbar.");
        return;
      }
    } else {
      for (const item of report.prechecks || []) {
        if (!item || typeof item !== "object") continue;
        const detail = [item.status, item.details, item.action].filter(Boolean).join(" · ");
        detailLine(item.component || "Netzwerkprüfung", detail || "Keine Details", list);
      }
      if (!list.children.length) {
        message(target, "Noch keine Netzwerkprüfung verfügbar.");
        return;
      }
    }
    target.replaceChildren(list);
  } catch {
    message(target, "Details sind momentan nicht erreichbar.");
  }
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const all = await api("api/status");
    for (const mode of modes) render(mode, all[mode]);
  } catch {
    for (const mode of modes) render(mode, {state:"unavailable"});
  } finally { refreshing = false; }
}
for (const button of document.querySelectorAll("button[data-action]")) {
  button.addEventListener("click", async () => {
    const {mode, action} = button.dataset;
    if (busy.has(mode)) return;
    busy.add(mode);
    for (const control of document.querySelectorAll("#t-" + mode + " button[data-action]"))
      control.disabled = true;
    feedback(mode, "Aktion wird ausgeführt …");
    try {
      await api("api/control/" + mode + "/" + action, {
        method:"POST",
        headers:{"Content-Type":"application/json", "X-MCPHub-Tunnel-Control":"1"},
        body:"{}"
      });
      feedback(mode, action === "stop" ? "Tunnel gestoppt." :
        action === "reload" ? "Einstellungen neu geladen." : "Start angefordert.");
    } catch (error) {
      feedback(mode, "Aktion fehlgeschlagen: " + error.message, true);
    } finally {
      busy.delete(mode);
      await refresh();
    }
  });
}
for (const section of document.querySelectorAll('details[data-panel="logs"], details[data-panel="diagnostics"]')) {
  section.addEventListener("toggle", () => {
    if (section.open) loadDetails(section.dataset.mode, section.dataset.panel);
  });
}
function keyMessage(message) {
  text(document.getElementById("key-message"), message);
}
async function keyRequest(path, method) {
  return api("api/client-key" + path, {
    method:method || "GET",
    headers:{"X-MCPHub-Tunnel-Control":"1",
      ...(method ? {"Content-Type":"application/json"} : {})},
    ...(method ? {body:"{}"} : {})
  });
}
document.getElementById("copy-key").addEventListener("click", async () => {
  const button = document.getElementById("copy-key");
  button.disabled = true;
  try {
    const data = await keyRequest("");
    if (!data.key) throw Error("Key nicht verfügbar");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(data.key);
        keyMessage("Key in die Zwischenablage kopiert.");
        return;
      } catch { /* Clipboard unavailable in non-secure contexts. */ }
    }
    let field = document.getElementById("key-fallback");
    if (!field) {
      field = document.createElement("textarea");
      field.id = "key-fallback"; field.readOnly = true; field.rows = 2;
      button.parentElement.after(field);
    }
    field.value = data.key;
    field.select();
    keyMessage("Key markieren und manuell kopieren.");
  } catch {
    keyMessage("Client-Key derzeit nicht verfügbar.");
  } finally { button.disabled = false; }
});
document.getElementById("rotate-key").addEventListener("click", async () => {
  if (!confirm("Client-Key erneuern? Der bisherige Key wird sofort ungültig.")) return;
  const button = document.getElementById("rotate-key");
  button.disabled = true;
  try {
    await keyRequest("/rotate", "POST");
    const field = document.getElementById("key-fallback");
    if (field) field.remove();
    keyMessage("Neuer Key erstellt. Bitte erneut kopieren und in MCP-Clients aktualisieren.");
  } catch {
    keyMessage("Key konnte nicht erneuert werden.");
  } finally { button.disabled = false; }
});
refresh();
setInterval(refresh, 10000);
