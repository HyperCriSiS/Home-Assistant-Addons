(() => {
  "use strict";
  // Only the Home Assistant Ingress route may offer this administrative link.
  // Do not expose it from the native LAN or the public tunnel origin.
  const match = location.pathname.match(/^(.*\/api\/hassio_ingress\/[^/]+)(?:\/|$)/);
  if (!match) return;
  const destination = match[1] + "/_mcphub_tunnels/";

  const mount = () => {
    const topbar = document.querySelector(".hub-topbar");
    if (!topbar || topbar.querySelector("#mcphub-ha-tunnel-link")) return;
    const link = document.createElement("a");
    link.id = "mcphub-ha-tunnel-link";
    link.href = destination;
    link.textContent = "Tunnelverwaltung";
    link.setAttribute("aria-label", "Tunnelverwaltung öffnen");
    link.style.cssText =
      "display:inline-flex;align-items:center;flex-shrink:0;padding:6px 11px;" +
      "border-radius:7px;border:1px solid var(--hub-line);" +
      "background:var(--hub-surface);color:var(--hub-ink);" +
      "text-decoration:none;font-size:12px;font-weight:600";
    const controls = topbar.querySelector(".ml-auto");
    if (controls) controls.prepend(link);
    else topbar.append(link);
  };

  document.addEventListener("DOMContentLoaded", () => {
    mount();
    new MutationObserver(mount).observe(document.getElementById("root") || document.body, {
      childList: true, subtree: true
    });
  });
})();
