# Lokaler XRechnungsprüfdienst

Offizieller KoSIT-HTTP-Daemon, Validator 1.6.3 und XRechnung-Regelpaket vom
31.08.2026. Versions-URLs und SHA-256-Prüfung stehen im Dockerfile. Der Dienst
ist ausschließlich über das interne Compose-Netz vom Backend erreichbar.

```bash
docker compose up --build -d invoice-validator backend
docker compose ps
```

Keine Veröffentlichung von Port 8080 und keine direkte Browseranbindung.
Das Backend sendet selbst erzeugte Rechnungen an den Prüfdienst. Die vollständige
Abgrenzung, Betriebsanforderungen und Testnachweise stehen in
[Architecture](../../docs/ARCHITECTURE.md).
