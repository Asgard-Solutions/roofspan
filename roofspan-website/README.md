# RoofSpan Public Website (roofspan.io)

Standalone marketing + download site for **RoofSpan** — roofing operations software.
Built with **Next.js (App Router) + static export**. It is fully independent of RoofSpan Office/Mobile/backend:
it imports **no** application code and adds **no** login, dashboard, or web-app links.

- **RoofSpan Office** installs on a company's own **Windows** system.
- **RoofSpan Mobile** securely connects field users to that installation.
- Windows installers are delivered **directly** from `downloads.roofspan.io` (CloudFront). The site never
  proxies installers through a backend and never exposes secrets. A build-time host check rejects any
  installer/release URL that isn't on `downloads.roofspan.io`.

## Develop
```bash
yarn install        # uses the committed yarn.lock
yarn dev            # http://localhost:3001
yarn lint
yarn test           # jest unit/component tests
yarn build          # static export -> ./out
yarn e2e            # Playwright conversion journey (serves ./out)
yarn start          # serve ./out locally
```
Deploy the generated `out/` directory to Railway/static hosting.

## Configuration (single source of truth: `src/config.js`)
All public config comes from `NEXT_PUBLIC_*` env vars (see `.env`). **Never put secrets here** — everything
in `NEXT_PUBLIC_*` ships to the browser.

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_SITE_URL` | `https://roofspan.io` | Canonical/OG/sitemap base URL |
| `NEXT_PUBLIC_CONTACT_EMAIL` | `sales@roofspan.io` | Footer/CTA/mailto fallback address |
| `NEXT_PUBLIC_WINDOWS_INSTALLER_AVAILABLE` | `false` | **Master availability switch.** `false` → primary CTA is "Join Early Access". Set `true` **only** after the installer is published → CTA becomes "Download for Windows". Drives header, hero, pricing, and download status consistently. |
| `NEXT_PUBLIC_WINDOWS_INSTALLER_URL` | `https://downloads.roofspan.io/latest/RoofSpanSetup.exe` | Installer download URL (must be on `downloads.roofspan.io`) |
| `NEXT_PUBLIC_WINDOWS_RELEASES_BASE_URL` | `https://downloads.roofspan.io/releases` | Versioned releases base (host-validated) |
| `NEXT_PUBLIC_WINDOWS_UPDATE_MANIFEST_URL` | `https://downloads.roofspan.io/update/windows/latest.json` | Update manifest |
| `NEXT_PUBLIC_LEAD_ENDPOINT` | _(empty)_ | Early-access form POST target. **When empty**, the form uses a transparent `mailto:` fallback to `NEXT_PUBLIC_CONTACT_EMAIL` — it never fakes success. |

## Early-access / lead form
`components/EarlyAccessForm.jsx`. Accessible (labels, `aria-invalid`, error/success/`mailto` states,
keyboard + screen-reader support, honeypot spam field). Behavior:
- If `NEXT_PUBLIC_LEAD_ENDPOINT` is set → JSON `POST`; shows a real success/error state from the response.
- If unset → opens a prefilled email to `NEXT_PUBLIC_CONTACT_EMAIL` and clearly says so. **No fake success.**

## ⚠️ Required before production launch (owner must supply)
1. **`sales@roofspan.io` mailbox** — must exist and be monitored/tested; it is the contact + mailto fallback.
2. **Lead endpoint** — set `NEXT_PUBLIC_LEAD_ENDPOINT` to a real form provider/webhook (Formspree, Getform,
   your own handler) if you don't want the mailto fallback in production.
3. **Legal pages** — Privacy Policy and Terms are intentionally **omitted** (no fabricated legal copy).
   Supply approved copy, then add `/privacy` and `/terms` pages + footer links before launch.
4. **Real product screenshots** — the Office/Mobile visuals in `components/ui.jsx` are polished, on-brand,
   **fictional-data** mockups representing only verified functionality. Replace with real **redacted**
   screenshots (fictional/redacted customer info) as independent optimized assets; the layout already
   reserves the space so no redesign is needed.
5. **Brand OG image** — `public/brand/og.png` is auto-generated from the app icon; swap for a designed
   1200×630 social card if desired. Large source PNGs live in `brand-source/` (not deployed).

## What is intentionally NOT here
No login/dashboard/web-app links, no invented testimonials/logos/metrics/awards/integrations/compliance
claims, no fabricated contracts/trials/discounts. Only capabilities verified in the repo are described.
