# MCPHub im lokalen Netzwerk

MCPHub ist standardmäßig direkt im lokalen Netzwerk über **Host-Port 3001** erreichbar:
`http://<HA-IP>:3001`. Intern läuft MCPHub weiterhin auf Port **3000**, und der separate LAN-Proxy verwendet den Containerport **3001/tcp**.

## Netzwerkport ändern

1. In Home Assistant **Einstellungen → Apps → MCPHub → Netzwerk** öffnen.
2. Falls der Port nicht angezeigt wird, **„Deaktivierte Ports einblenden“** aktivieren.
3. Links steht der Host-Port, standardmäßig **3001**. Bei einer Portkollision einen anderen freien Port wählen (zum Beispiel **3000**, falls frei), speichern und gegebenenfalls die App neu starten. `3001/tcp` rechts bezeichnet den festen internen Containerport, nicht die Eingabe.
4. Zum Deaktivieren das Host-Port-Feld leeren.

Für den direkten LAN-Zugang gilt **MCPHubs eigene Anmeldung**, nicht die Anmeldung über Home Assistant Ingress. In MCPHub unter **Keys** einen Bearer-Key erstellen und MCP-Clients mit `http://<HA-IP>:3001/mcp` und `Authorization: Bearer <KEY>` verbinden (bei geändertem Host-Port die URL entsprechend anpassen).

## Sicherheit

Der LAN-Port bietet Zugriff auf MCPHubs native Oberfläche, Verwaltungs-API und MCP-Endpunkte. Er wird im Host-Netzwerk veröffentlicht, aber nicht automatisch ins Internet weitergeleitet. MCPHubs native Authentifizierung bleibt aktiv; **Enable Bearer Authentication** muss aktiviert bleiben.

HTTP verschlüsselt weder Passwörter noch Bearer-Keys. Deshalb nur in vertrauenswürdigen lokalen Netzen verwenden und für ungeschützte Netze einen verschlüsselten Zugang einrichten. Die Ingress-Anmeldung von Home Assistant gilt nicht für den direkten LAN-Port.
