# FlintPlate Frontend

Next.js, React und TypeScript mit Node.js 24. Den dedizierten Backend-Stack gemäß
[Root-Schnellstart](../README.md#quick-start) starten. Anschließend:

```sh
npm ci
npm run build -- --webpack
npm run start -- --hostname 127.0.0.1 --port 3012
```

Die UI verwendet den `/api`-Proxy zum Backend unter `http://127.0.0.1:8012`.
`FLINTPLATE_API_URL` überschreibt das Proxy-Ziel. `LEGAL_*`-Werte in der Umgebung
oder einer ignorierten `.env.local` hinterlegen. Entwicklung: `npm run dev -- --port 3012`.

## Prüfungen

```bash
npm ci
npm run lint
npm run build
npm run typecheck
npm run test:e2e
```

Der Build erzeugt auch die Next.js-Routentypen für einen frischen Checkout.
Die Browserprüfung nutzt den laufenden Compose-Stack und synthetische Konten aus
`../TEST_USERS.md`. Sie darf nur lokal ausgeführt werden. Ein vorhandenes Chromium
wird automatisch genutzt; alternativ `npx playwright install chromium` ausführen
oder `PLAYWRIGHT_CHROMIUM_EXECUTABLE` setzen.

JSON-Bericht, Fehlerscreenshots und die gezielt aufgenommenen Ansichten liegen
unter `../.artifacts/browser/`. `e2e/portal.spec.ts` prüft Portale und mobile
Navigation; `e2e/workflows.spec.ts` prüft Registrierung, Stellenpflege und
Mitarbeiteransichten sowie ausgewählte WCAG-Regeln der Anmeldung.

CI führt Lint, Produktionsbuild und Typprüfung aus. Der aktuelle technische
Freigabestand steht in `../docs/RELEASE_READINESS_2026-09-06.md`.
