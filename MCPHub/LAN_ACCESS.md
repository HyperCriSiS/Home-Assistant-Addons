# MCPHub im lokalen Netzwerk

MCPHub bleibt im Container auf Port **3000**. Der direkte Netzwerkzugang ist standardmäßig ausgeschaltet. Home Assistant Ingress und bestehende Tunnel funktionieren unabhängig davon.

## Aktivieren

1. In Home Assistant **Einstellungen → Apps → MCPHub → Netzwerk** öffnen.
2. Bei **MCPHub im lokalen Netzwerk** einen freien Host-Port setzen, zum Beispiel **3000**. Ist der Port leer, bleibt die Freigabe deaktiviert.
3. MCPHub bei Bedarf neu starten.
4. Die Oberfläche über `http://<HA-IP>:3000` öffnen. Für diesen direkten Zugang gilt **MCPHubs eigene Benutzeranmeldung**, nicht die Home-Assistant-Anmeldung.
5. In MCPHub unter **Keys** einen eigenen Bearer-Key erstellen und den MCP-Client auf `http://<HA-IP>:3000/mcp` mit `Authorization: Bearer <KEY>` einrichten.

Der direkte Port stellt MCPHubs normale Oberfläche, Verwaltungs-API und MCP-Endpunkte bereit. Es gibt keine zusätzliche Gruppenverwaltung oder eigene LAN-Authentifizierung. **Enable Bearer Authentication** muss aktiviert bleiben.

## Sicherheit

HTTP verschlüsselt keine Passwörter oder Bearer-Keys. Für nicht vertrauenswürdige Netze HTTPS oder einen verschlüsselten Zugang verwenden. Einmalige Ingress-Anmeldung in Home Assistant gilt **nicht** für den direkten LAN-Port.

Wenn Tailscale bereits Zugriff auf die Home-Assistant-Hostadresse und den freigegebenen Port ermöglicht, sind weder Tailscale Serve noch Funnel nötig. Serve ist nur eine optionale private HTTPS-Adresse im Tailnet; Funnel ist öffentlich zugänglich.

Bei deaktiviertem Host-Port bleiben MCPHub intern auf Port 3000 sowie Home Assistant Ingress und bestehende Tunnel unverändert aktiv.
