# web — the Torehancast dashboard

React + TypeScript on Vite (PLAN.md F track).

```sh
npm ci
npm run dev        # http://localhost:5173
npm test           # Vitest, then Playwright (headless Chrome)
npm run build      # → dist/
```

Playwright uses the installed Google Chrome by default. In CI, run
`npx playwright install chromium` and set `PLAYWRIGHT_CHANNEL=chromium`.
