"use strict";
const modes = ["openai", "cloudflare", "tailscale"];
const stateNames = {
  gateway_ready: ["Gateway bereit", "success", "Das MCP-Gateway ist bereit; der Funnel wird separat verwaltet."],
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
  if (mode === "tailscale") {
    text(card.querySelector('[data-field="gateway"]'),
      s.gateway_ready ? "Lokal bereit" : s.configured ? "Nicht bereit" : "Deaktiviert");
    text(card.querySelector('[data-field="funnel"]'), "Externes Add-on · manuell");
    text(card.querySelector('[data-field="route"]'), s.route || "–");
    text(card.querySelector('[data-field="https"]'),
      s.public_check === "gateway_answered" ? "Gateway antwortet" :
      s.public_check === "not_verified" ? "Nicht bestätigt" : "Nicht geprüft");
    text(card.querySelector('[data-field="public-url"]'),
      s.public_url || (s.public_url_invalid ? "Ungültige Adresse" : "Noch nicht eingetragen"));
  } else {
    text(card.querySelector('[data-field="configured"]'),
      typeof s.configured === "boolean" ? (s.configured ? "Ja" : "Nein") : "Unbekannt");
  text(card.querySelector('[data-field="connection"]'),
    s.transport_ready ? "Lokal bereit" : "Nicht bereit");
  text(card.querySelector('[data-field="route"]'), s.route || "–");
  text(card.querySelector('[data-field="age"]'),
    typeof s.health_age_seconds === "number" ? "vor " + s.health_age_seconds + " s" : "–");
  }
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
    if (mode === "tailscale") {
      message(target, report.note || "Tailscale-Diagnose nur im Tailscale-Add-on verfügbar.");
      return;
    }
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
      feedback(mode, mode === "tailscale"
        ? (action === "stop" ? "Lokaler MCP-Zugang gestoppt. Funnel unverändert." :
          "Lokaler MCP-Zugang gestartet. Funnel unverändert.")
        : action === "stop" ? "Tunnel gestoppt." :
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

const funnelCommand = "/opt/tailscale funnel --bg --https=443 http://127.0.0.1:3002";
async function copyToClipboard(value) {
  if (!navigator.clipboard || !navigator.clipboard.writeText) return false;
  try { await navigator.clipboard.writeText(value); return true; }
  catch { return false; }
}
document.getElementById("copy-tailscale-command").addEventListener("click", async () => {
  const done = await copyToClipboard(funnelCommand);
  feedback("tailscale", done ? "CLI-Befehl kopiert." :
    "Zwischenablage nicht verfügbar. Befehl oben manuell kopieren.", !done);
});
document.getElementById("tailscale-check").addEventListener("click", async () => {
  const button = document.getElementById("tailscale-check");
  button.disabled = true;
  feedback("tailscale", "HTTPS-Verbindung wird ohne Zugangsdaten geprüft …");
  try {
    const report = await api("api/tailscale/https-check", {
      headers: {"X-MCPHub-Tunnel-Control": "1"}
    });
    feedback("tailscale", report.result === "gateway_answered" ?
      "HTTPS-Gateway antwortet. Öffentliche Erreichbarkeit aus fremdem Netz noch nicht bewiesen." :
      "Keine bestätigte HTTPS-Antwort vom MCP-Gateway.", report.result !== "gateway_answered");
    await refresh();
  } catch {
    feedback("tailscale", "Bitte zuerst eine gültige Funnel-URL in der App-Konfiguration eintragen.", true);
  } finally { button.disabled = false; }
});
document.getElementById("tailscale-copy-key").addEventListener("click", async () => {
  const button = document.getElementById("tailscale-copy-key");
  button.disabled = true;
  const target = document.getElementById("tailscale-key-message");
  try {
    const data = await api("api/tailscale/client-key", {
      headers: {"X-MCPHub-Tunnel-Control": "1"}
    });
    if (!data.key) throw Error("Missing key");
    if (await copyToClipboard(data.key)) {
      text(target, "Client-Key kopiert.");
    } else {
      let field = document.getElementById("tailscale-key-fallback");
      if (!field) {
        field = document.createElement("textarea");
        field.id = "tailscale-key-fallback"; field.readOnly = true; field.rows = 2;
        field.style.width = "100%";
        button.parentElement.after(field);
      }
      field.value = data.key; field.select();
      text(target, "Schlüssel markieren und manuell kopieren.");
    }
  } catch { text(target, "Client-Key konnte nicht geladen werden."); }
  finally { button.disabled = false; }
});
document.getElementById("tailscale-rotate-key").addEventListener("click", async () => {
  if (!confirm("Tailscale Client-Key erneuern? Der bisherige Key wird sofort ungültig.")) return;
  const button = document.getElementById("tailscale-rotate-key");
  button.disabled = true;
  try {
    await api("api/tailscale/client-key/rotate", {
      method: "POST", headers: {
        "Content-Type": "application/json", "X-MCPHub-Tunnel-Control": "1"
      }, body: "{}"
    });
    const field = document.getElementById("tailscale-key-fallback");
    if (field) field.remove();
    text(document.getElementById("tailscale-key-message"),
      "Key erneuert. Bitte neu kopieren und in Claude ersetzen.");
  } catch {
    text(document.getElementById("tailscale-key-message"), "Schlüssel-Erneuerung fehlgeschlagen.");
  } finally { button.disabled = false; }
});

refresh();
setInterval(refresh, 10000);
