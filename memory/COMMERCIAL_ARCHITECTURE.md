# RoofSpan Commercial Distribution, Licensing, Updates & Secure Connectivity — Implementation Proposal (v1, ARCHITECTURE ONLY)

> **ARCHITECTURE INVARIANT (2026-06, LOCKED).** RoofSpan Office is a **locally installed Windows
> application with a browser-based local UI**. There is **NO centrally hosted RoofSpan operational
> web application** — customers never log into a central website to run their roofing business.
> `roofspan.io` is the **public marketing/download website only**. `downloads.roofspan.io` (CloudFront →
> private S3) distributes the installer/updates. RoofSpan **Mobile** clients connect through the RoofSpan
> **Secure Relay** to the customer's **local RoofSpan Office installation** (local FastAPI → local
> PostgreSQL, which stays authoritative for all users, auth, roles, and business data). Central services
> (Control Plane / Relay / Billing sync / entitlements / pairing / version policy / distribution) hold
> commercial metadata only and are **never** the roofing-business database. When docs say "web app" they
> mean this **local browser UI** ("RoofSpan Office UI"), not a hosted SaaS app.


Status: **PROPOSAL — awaiting review/approval. No implementation started.**
Date: 2026-06
Governing principle: **K.I.S.S.** — local-first business data is unchanged; central services are a thin commercial layer.

---

## 0. What this changes and what it does NOT change

**Unchanged (locked):**
- Business-data architecture: `Office Browser → Local FastAPI → Local PostgreSQL` per installation.
- One roofing company per installation. No multi-tenant business DB, no tenant switching, no franchise mode.
- Local backend remains authoritative for users, passwords, roles, RBAC, assignments, and all roofing records.
- Existing Office/Mobile business workflows (Phases 1–5, Mobile Increments 1–2) stay as-is.
- RoofSpan branding (orange/slate, logo, favicon, login imagery) is reused everywhere, including installer, subscription, pairing, and update UI.
- Existing local + off-site backup architecture and `SECRETS_ENCRYPTION_KEY` recovery model remain.

**New (this phase — the commercial layer):**
- Windows installer + Windows services + automatic updates.
- A small central **RoofSpan Control Plane** (licensing, seats, pairing, versions, installation identity, relay routing).
- A **RoofSpan Relay** for secure outbound Mobile connectivity (no port-forwarding).
- **RevenueCat + Stripe** billing behind an internal `BillingProvider` abstraction.
- **Signed entitlements** validated locally; subscription state machine; seat enforcement.
- Mobile pairing (QR + numeric fallback), Mobile license-lock, Mobile min-version enforcement.

**Central services store NO roofing business data.** Properties, leads, customers, inspections, estimates, quotes, jobs, invoices, inventory, visits, photos, and notes never leave the customer's local PostgreSQL.

---

## 1. Service Boundaries (four logical services, deployable together)

Keep it small — one repo/deployment ("RoofSpan Cloud") may host all four behind one domain and process manager initially. Logical separation, not premature microservices.

| Service | Responsibility | Stores | Never stores |
|---|---|---|---|
| **Control Plane** | Licensing, activation, seat count, subscription status, installation identity registry, pairing-token issuance, version policy, entitlement signing, relay routing metadata | Company/installation/license identifiers, subscription status, seat count, public keys, pairing tokens, version policy, connection metadata | Any roofing business data; private keys; card data; provider secrets |
| **Billing Integration** | RevenueCat + Stripe adapter, webhook receiver, subscription-state normalization | Billing provider IDs, normalized subscription state, webhook event log (idempotency) | Raw card numbers (Stripe/RevenueCat hold these) |
| **Relay** | Secure request routing Mobile↔Installation via outbound tunnel from the customer server | Transient connection state, limited operational metadata | Request/response payloads (best-effort), business data, secrets, photos |
| **Update Service** | Signed Windows release manifests + package hosting | Release manifests, package metadata/hashes/signatures | Business data |

**Deployment note:** Emergent/host can run these as one FastAPI app ("control-plane") + object storage for update packages, + a relay component (WebSocket/gRPC tunnel). DECISION REQUIRED on final hosting (see §17).

---

## 2. Data Ownership Contract (authoritative table)

- **Local PostgreSQL (per installation):** ALL business data + users/auth/roles + local license cache + installation private key + pairing records + integration secrets (AES-GCM) + backups.
- **Control Plane DB (central, small):** `companies`, `installations`, `licenses`, `subscriptions`, `seats`, `entitlement_issuances`, `pairing_tokens`, `mobile_devices` (pairing metadata only — NOT the user directory), `version_policy`, `relay_sessions`, `webhook_events`.
- **Master employee directory stays local.** Control Plane only knows an installation exists and how many seats it is entitled to — never the employee list, emails, or passwords.

---

## 3. Installation Identity & Cryptography

**On first activation, the local Windows installation generates its own keypair locally.**
- Algorithm: **Ed25519** (installation identity signing) + **X25519/TLS** for transport. Use `cryptography` (already a dependency) — no custom crypto.
- Private key stored on the customer server only, in the persistent data dir, filesystem-ACL restricted to the RoofSpan service account. Optionally wrapped with a DPAPI-derived key (Windows) — DECISION REQUIRED (adds Windows-only dependency vs. plain file perms).
- Public key registered with Control Plane during activation → becomes the installation's `public_identity`.
- Credentials rotatable; Control Plane can **revoke** a compromised installation (revocation list checked on entitlement refresh + relay connect).

**Entitlement signing keys (Control Plane side):**
- Control Plane holds an **Ed25519 signing keypair**. Public verify key is **baked into every RoofSpan release** (and refreshable via signed version policy) so the local server validates entitlements offline.
- Support **key rotation with overlap**: entitlements carry a `kid` (key id); local server keeps a small set of trusted public keys.

---

## 4. Signed Entitlement — Format & Validation

**Transport:** compact signed token. Recommendation: **JWS (Ed25519 / EdDSA)** — standard, well-supported by PyJWT/`python-jose`, no custom primitives. (JWT is already used for auth.)

**Claims (entitlement payload):**
```
{
  "kid": "ctrl-2026-06",           // signing key id (rotation)
  "installation_id": "uuid",
  "company_id": "uuid",
  "license_id": "uuid",
  "subscription_state": "ACTIVE|GRACE|SUSPENDED|CANCELLED",
  "seats_licensed": 10,
  "product": "roofspan-office",
  "min_supported_version": "1.4.0",
  "issued_at": 1730000000,
  "expires_at": 1730604800,        // short: e.g. 7 days
  "grace_until": 1731209600,       // offline tolerance window
  "nonce": "…"                     // replay hardening
}
```

**Local validation on every startup + periodic refresh (default every 6–12h):**
1. Verify EdDSA signature against a trusted `kid` public key.
2. Check `installation_id` matches this install; check `expires_at`/`grace_until`.
3. Persist latest valid entitlement in local PostgreSQL (`license_cache`) — the **cached signed entitlement is the offline source of truth**.
4. Enforce `subscription_state` + `seats_licensed` locally.

**Offline tolerance (critical, §29):** if the Control Plane is unreachable, the last cached entitlement remains authoritative until `grace_until`. Distinguish:
- **"Cannot contact Licensing Service"** → keep operating on cached entitlement until `grace_until`; show subtle "last verified X ago" note only after a threshold.
- **"Licensing Service confirms SUSPENDED"** → apply SUSPENDED lock.
A Control-Plane outage must never take companies offline.

---

## 5. Subscription State Machine

States: **ACTIVE → GRACE → SUSPENDED → CANCELLED** (+ reactivation paths).

```
                 payment ok / renewal
        ┌────────────────────────────────────────┐
        ▼                                          │
   [ACTIVE] ── payment fails ──▶ [GRACE] ── grace expires ──▶ [SUSPENDED]
        ▲                          │                              │
        │   payment recovered      │  payment recovered           │ payment recovered
        └──────────────────────────┴──────────────────────────────┘
                                                                   │
                          explicit cancel / non-recovery           ▼
                                                              [CANCELLED]
                                                     (same lock as SUSPENDED,
                                                      data preserved, reactivatable)
```

| State | Office (Owner/Admin) | Office (Office/Sales) | Mobile | Data |
|---|---|---|---|---|
| ACTIVE | Full | Full | Full | intact |
| GRACE | Full + prominent warning banner | Full (banner shown to admins primarily) | Full | intact |
| SUSPENDED | Login + subscription/billing/recovery pages only; business workflows blocked | Blocked (see recovery page) | Blocked (license-lock screen) | intact |
| CANCELLED | Same as SUSPENDED; reactivation available | Blocked | Blocked | intact |

- Grace duration **configurable** (Control Plane sets `grace_until` in the entitlement; default e.g. 7–14 days — DECISION REQUIRED on default).
- Never delete users/data on SUSPENDED/CANCELLED. Never shut down on a single failed payment.

**Enforcement mechanism (Office):** a FastAPI dependency `require_active_subscription` wraps business routers (leads/properties/jobs/estimates/quotes/invoices/inventory writes + reads as configured). Auth, `/subscription`, `/billing`, `/license`, and recovery endpoints are always allowed. Read-only vs. full-block scope in SUSPENDED is DECISION REQUIRED (recommend: block business reads too except a safe summary, to make the lapse unambiguous — but Owner can always see data-safety messaging).

---

## 6. Seat Enforcement

- `seats_licensed` comes from the signed entitlement. Local server counts `is_active == true` users.
- Owner counts as a seat. Disabled/inactive users do NOT consume a seat. Never auto-disable or delete users to reclaim seats.
- Locked bounds: **min 5, max 50** licensed seats.
- On activate-user (create new active user OR reactivate a disabled user): if `active_count >= seats_licensed` → **422 business error**:
  > "Your RoofSpan subscription includes N active users. Add another licensed seat to activate this user."
- Owner/Admin UI shows `X of N seats used` + **Add Seats** → routes to hosted billing/seat-change flow.
- Seat changes flow: billing update → webhook → Control Plane updates `seats_licensed` → next entitlement refresh reflects new count. (Local may proactively refresh after returning from billing.)

---

## 7. Billing — RevenueCat + Stripe (behind `BillingProvider` abstraction)

**Confirmed capability (research):** RevenueCat **Web Billing + Stripe** supports Web Purchase Links, entitlements as source-of-truth, and webhooks (`INITIAL_PURCHASE`, `RENEWAL`, `CANCELLATION`, `EXPIRATION`, etc.). This fits a Windows-desktop-driven, browser-based checkout perfectly.

**Flow:**
```
RoofSpan Office (Owner)
  → "Activate / Manage Billing / Add Seats" opens system browser
  → RevenueCat Web Purchase Link / Stripe Checkout (hosted; card data never touches RoofSpan)
  → RevenueCat entitlement updates; Stripe processes payment
  → RevenueCat webhook → RoofSpan Billing Integration (verify signature, idempotent)
  → normalize → update Control Plane subscription state + seat count
  → Control Plane issues/refreshes signed entitlement
  → Local RoofSpan refreshes entitlement → unlocks
```

**`BillingProvider` internal abstraction (so Helcim can slot in later, §24):**
```python
class BillingProvider(Protocol):
    def start_checkout(company_id, seats) -> CheckoutSession        # returns hosted URL
    def manage_billing_url(company_id) -> str                        # customer portal
    def normalize_webhook(raw_event) -> NormalizedSubscriptionEvent  # provider-agnostic
    # NormalizedSubscriptionEvent: {company_id, state, seats, renewal_at, event_id}
```
Only the Billing Integration service knows Stripe/RevenueCat specifics. Control Plane, Office, Mobile, licensing, relay, installer, and seat enforcement consume only **normalized subscription state**. No Stripe-specific concepts leak into product code.

**Webhook safety:** verify RevenueCat/Stripe signatures; store `event_id` for **idempotency**; ignore stale/out-of-order events using event timestamps.

**Merchant of record / tax:** consider Stripe Managed Payments via RevenueCat — DECISION REQUIRED (tax handling).

**RoofSpan never stores card numbers.** No PAN persisted anywhere in the local app or Control Plane.

---

## 8. Payment-Lapse Recovery Flow (Office)

1. Webhook → GRACE, then (if unresolved) SUSPENDED.
2. Owner can always log in. Business UI replaced by a RoofSpan-branded page/banner:
   > **RoofSpan subscription requires attention** — Your subscription is past due. Your company data is safe, but normal RoofSpan functionality is temporarily unavailable. Update your billing information to restore access.
3. Button: **Update Billing / Reactivate RoofSpan** → opens hosted RevenueCat/Stripe portal.
4. On success: webhook → Control Plane ACTIVE → entitlement refresh → local unlock → Mobile resumes. **No reinstall required.**

---

## 9. Mobile License-Lock, Pairing, and Version Enforcement

**License-lock (§10):** If installation is SUSPENDED/CANCELLED, Mobile shows a dedicated RoofSpan-branded screen:
> **RoofSpan subscription inactive** — Your company's RoofSpan subscription needs to be updated before Mobile can be used. Please contact your RoofSpan administrator. **[Try Again]**
- No signup, no create-company, no payment entry for Sales users, no bypass into Leads/Jobs/Map.
- **Pending offline data (visits/notes/inspections/photos/queued updates) is preserved** — never deleted on lapse. On return to ACTIVE, Mobile rechecks entitlement and resumes sync.
- Mobile learns license state via the relay/installation on connect (local backend reports current entitlement state) — not from a Mobile-only cloud call.

**No public account creation (§11):** stores' Mobile app has NO Sign Up / Create Company / Start Trial. Flow: company installs Office → Owner activates → Owner creates users → employee downloads Mobile → pairs → signs in with the **locally-created** account. Control Plane is NOT the employee directory.

**QR / Pairing (§12):**
- Office: **Administration → Mobile Setup → Pair Device** → generates a **short-lived, single-use pairing token** (e.g., 5 min TTL). Shows QR + numeric fallback (e.g., `728 419`).
- Pairing payload contains ONLY: `installation_id`, one-time `pairing_token`, `expiry`, RoofSpan **relay/service endpoint metadata**, protocol/version. It does NOT contain passwords, PostgreSQL creds, RentCast/MapTiler keys, encryption master secret, or object-storage creds.
- Token issued/validated via Control Plane (so Mobile off-network can resolve which installation + relay route). After successful pair: token expires; Mobile stores installation binding in `expo-secure-store`; user still authenticates with the local account.
- **Pairing ≠ authentication.** After pairing, login still hits the local FastAPI (via relay) with email/password → local JWT.

**Mobile version compatibility (§21, §22):**
- Control Plane holds Mobile `latest`, `recommended`, `min_supported` versions.
- Mobile startup: current-but-not-latest → optional "update available", allow continue. Below min → hard "RoofSpan must be updated" + **Update App** deep link to App Store / Play Store; block connect.
- Explicit **version negotiation**: Mobile sends `X-RoofSpan-App-Version` + `X-RoofSpan-Protocol`; local backend + relay reject below-minimum protocol to prevent an outdated client corrupting data. Prefer backward-compatible APIs.

---

## 10. Secure Relay — Outbound Connectivity (§13–§15)

**Goal:** Mobile works off the office network with **no port-forwarding, no inbound firewall rules, no public FastAPI, no customer VPN.**

**Model:**
```
RoofSpan Mobile ──TLS──▶ RoofSpan Relay ◀──outbound authenticated tunnel── Customer Windows Server ──▶ local FastAPI ──▶ PostgreSQL
```
- The **Windows server initiates a persistent OUTBOUND** connection (recommend **WebSocket over TLS**, with auto-reconnect/backoff) to the Relay and registers its `installation_id` (authenticated via installation identity: mTLS or a short-lived Control-Plane-issued connection token signed to the installation's public key).
- Mobile connects to the Relay (TLS), presents its pairing binding + a local-auth session; Relay routes the request down the correct installation's tunnel. Response routes back.

**Per Mobile request the system verifies (defense in depth):**
1. Which installation is targeted? (relay routing by `installation_id`)
2. Is that installation licensed/entitled? (Control Plane / cached state — SUSPENDED blocks routing)
3. Is this Mobile device paired to that installation? (pairing binding)
4. Is the session/auth valid? (local JWT round-trips to local backend)
5. Does the local backend authorize the user/action? (**local RBAC is authoritative — Relay NEVER replaces RBAC**)

**Relay data handling (§15):** route, don't persist. Avoid storing payloads. Operational logs may include `installation_id`, timestamps, request timing, error codes, version, connectivity/health. **Never log** passwords, provider secrets, card data, raw photos, or full business payloads.

**Transport choice DECISION REQUIRED:** WebSocket-tunnel (simplest, HTTP-friendly) vs. a mature tunneling layer. Recommend building on a proven library rather than a bespoke protocol.

---

## 11. Windows Installer & Services (§2, §3, §31)

**Platform: Windows only** now. No macOS/Linux installers.

**Installer type DECISION REQUIRED:** recommend **Inno Setup** or **WiX/MSI**. Recommendation: **MSI via WiX** for enterprise-grade service registration + repair semantics + Group Policy friendliness. (Inno Setup is simpler if MSI is overkill.)

**Bundled/auto-configured (customer installs nothing manually):**
- Embedded **PostgreSQL** (bundled binaries; initialize cluster into a persistent data dir under ProgramData).
- Embedded **Python runtime** + FastAPI backend (packaged; no system Python).
- **Office frontend** static build served locally (by the backend or a lightweight local static server).
- **Windows Services** (auto-start): `RoofSpanDB` (PostgreSQL), `RoofSpanBackend` (FastAPI + relay client), `RoofSpanUpdater` (update agent). Use a service wrapper (e.g., NSSM or a native service host) — DECISION REQUIRED.
- Persistent data dirs (survive upgrades): `%ProgramData%\RoofSpan\{db, backups, keys, config, logs}`.
- Generates `.env`-equivalent local config: `JWT_SECRET`, `SECRETS_ENCRYPTION_KEY`, `DATABASE_URL`, installation keypair — all created on first run, never shipped in the package.
- Runs **initial Alembic migration** to head.
- Local firewall: allow loopback + LAN as appropriate for Office browser access; **no inbound public exposure** (Mobile uses outbound relay).

**Install modes (non-destructive):** fresh / upgrade / repair / restart / recovery. **Must not overwrite an existing RoofSpan install or business DB.** Detect existing data dir → upgrade path (backup-first). Uninstall must **not** delete business data by default (explicit opt-in only).

**First-run wizard (RoofSpan-branded):** Welcome → Company info → Activate (choose 5–50 seats → RevenueCat/Stripe checkout → confirm ACTIVE) → Create Owner → verify services/DB → Finish → Open Office. Hide DB/technical details unless troubleshooting.

---

## 12. Windows Automatic Updates (§17–§20)

**Update agent (`RoofSpanUpdater` service):**
```
Check (signed manifest from Update Service)
 → Download package
 → Verify signature + hash (reject on mismatch — never apply unverified)
 → Create pre-update DB backup (pg_dump -Fc) + verify backup succeeded
 → Preserve encryption keys/config
 → Stop services
 → Apply update
 → Run Alembic migration (never auto-downgrade schema)
 → Restart
 → Startup health check
 → Complete OR fail loudly + preserve recovery info (do not leave unknown schema state)
```
**Signed release manifest:** `latest_version`, `min_supported_version`, `mandatory|optional`, `download_url`, `package_hash`, `signature`, `migration_info`, `release_metadata`.

**Update UX (Administration → RoofSpan Updates):** Current Version, Latest Version, Last Update Check, Last Update Result, Automatic Updates On/Off, Maintenance Window. Default: **auto-install recommended updates ON**, simple maintenance window. Not an IT patch-management platform.

**Windows code signing (§18):** installers + update packages **Authenticode-signed**, timestamped. **HUMAN REQUIRED:** code-signing certificate (EV recommended for SmartScreen reputation). **Private signing keys never in the repo.**

---

## 13. Required Schema Additions

### 13a. Local PostgreSQL (per installation) — new tables (additive, non-destructive Alembic migration)
- `license_cache` — latest signed entitlement (raw JWS + decoded fields + fetched_at); singleton-ish.
- `installation_identity` — installation_id, public_key, private_key (perm-restricted / optionally DPAPI-wrapped), created_at, rotated_at.
- `mobile_pairings` — pairing_token_hash, created_by, expires_at, used_at, device_label (post-pair), status.
- `paired_devices` — device_id, label, paired_at, last_seen, revoked_at (pairing metadata only).
- (Optional) `subscription_events_local` — normalized events mirrored for admin visibility/audit.
- **No changes to existing business tables.** Seat enforcement reads existing `users`.

### 13b. Control Plane DB (central, new)
- `companies`, `installations` (+ `public_key`, `revoked`), `licenses`, `subscriptions` (normalized state, seats, renewal_at, provider refs), `entitlement_issuances`, `pairing_tokens`, `mobile_devices`, `version_policy` (office + mobile: latest/recommended/min), `relay_sessions`, `webhook_events` (idempotency), `signing_keys` (kid, public/private — private secured).

---

## 14. Required API Additions

### 14a. Local FastAPI (Office/Mobile-facing)
- `GET /api/subscription` — current state, seats_licensed, active_users, available, renewal, last_verified.
- `POST /api/subscription/refresh` — force entitlement refresh from Control Plane.
- `GET /api/billing/portal-url` — hosted billing/customer-portal URL (Owner/Admin).
- `POST /api/billing/checkout` — start activation/seat-change checkout (Owner).
- `GET /api/license/status` — signed-entitlement summary + offline/verified state.
- `POST /api/admin/mobile/pair` — issue short-lived pairing token (QR + numeric).  (Administration → Mobile Setup)
- `GET /api/admin/mobile/devices` / `DELETE …/{id}` — list/revoke paired devices.
- Middleware/dependency: `require_active_subscription` on business routers; `require_min_mobile_version` on `/api/mobile/*`.
- Version negotiation headers on `/api/mobile/*`.

### 14b. Control Plane API
- `POST /activation/activate` — installation registers public key + pairing to company/license → returns first signed entitlement.
- `GET /entitlement/{installation_id}` — issue/refresh signed entitlement (rate-limited, authenticated by installation identity).
- `POST /billing/webhook` — RevenueCat/Stripe webhook (signature-verified, idempotent).
- `POST /pairing/resolve` — Mobile resolves pairing token → installation + relay endpoint (no secrets).
- `GET /version-policy` — office + mobile version policy (signed).
- `GET /updates/manifest` — signed Windows release manifest.
- Relay control endpoints — installation tunnel registration/auth; revocation checks.

---

## 15. Security Threats & Mitigations

| Threat | Mitigation |
|---|---|
| Forged entitlement / seat inflation | EdDSA-signed entitlements; local verify; `kid` rotation; short expiry + nonce |
| Replaying old ACTIVE entitlement after cancel | Short `expires_at` + `grace_until`; state re-check on refresh; nonce |
| Stolen installation identity | Revocation list; short-lived relay tokens/mTLS; key rotation |
| Pairing token theft | Single-use, short TTL, no secrets in payload, hash-at-rest, bind to installation |
| Relay as data honeypot | Route-only, no payload persistence, metadata-only logs, local RBAC authoritative |
| Webhook spoofing/replay | Signature verification + `event_id` idempotency + timestamp ordering |
| Card data exposure | Hosted Stripe/RevenueCat only; RoofSpan stores no PAN |
| Malicious update package | Authenticode + manifest signature + hash verify; backup-before-apply; loud-fail |
| Outdated Mobile corrupts data | Version negotiation; min-version hard block; backward-compatible APIs |
| Control Plane outage disabling everyone | Cached signed entitlement valid until `grace_until`; outage ≠ suspension |
| Brute force / abuse | Existing lockout + rate limiting extended to new endpoints; TLS everywhere |
| Secret sprawl | Local secrets stay local; central holds no provider secrets; keys off-repo |

No custom cryptographic primitives — EdDSA/JWS/TLS/AES-GCM via `cryptography`/PyJWT only.

---

## 16. Offline Licensing & Recovery Behavior (§29, §30)

- Cached signed entitlement authoritative offline until `grace_until`; Control-Plane unreachable ≠ suspended.
- Business data recoverable independently of subscription state; backups always usable; **PostgreSQL is NOT encrypted in a way that requires the cloud licensing service to recover it**. `SECRETS_ENCRYPTION_KEY` only protects integration provider secrets, not the whole DB. Company owns its data.

---

## 17. Migration Impact on Existing RoofSpan

- **Additive only.** New Alembic migration for local tables; existing 5-phase schema untouched → non-destructive, matches current migration discipline (`create_all` removed; Alembic authoritative).
- Existing Office/Mobile flows unchanged except: (a) a subscription banner/guard wrapper, (b) new Administration pages (Subscription, Mobile Setup, Updates), (c) Mobile gains pairing + license-lock + version-check screens before existing tabs.
- Dev/preview (Emergent) note: this container is Linux; the **Windows installer/services/update agent cannot be built or tested here** — they are produced/tested on Windows (HUMAN REQUIRED). Control Plane / Billing / Relay CAN be developed and tested in-container.

---

## 18. Testing Strategy

- **Backend (in-container):** pytest for entitlement sign/verify, state machine transitions, seat enforcement (5/50 bounds, disabled≠seat), `require_active_subscription` gating, webhook idempotency/signature, pairing token TTL/single-use, version negotiation. Keep the existing serial-run discipline (`-o addopts=""` to avoid xdist lockout flakiness).
- **Control Plane:** pytest for activation, entitlement issuance/rotation, revocation, version policy, relay auth.
- **Billing:** simulated RevenueCat/Stripe webhook fixtures (signed) → normalized state assertions; no live keys in CI.
- **Relay:** integration test with a mock installation tunnel + mock Mobile client (in-container).
- **Mobile:** Node/unit tests for pairing binding, license-lock gating, version-check; existing offline sync lifecycle (11/11) must still pass; **native device verification HUMAN REQUIRED**.
- **Windows installer/update:** **HUMAN REQUIRED** on Windows VM — fresh/upgrade/repair, backup-before-update, migration, rollback/loud-fail.

---

## 19. Rollout / Development Sequence (phased, gated)

Each phase is independently testable; stop points marked. Nothing starts until this proposal is approved.

- **Phase C0 — Foundations (in-container):** entitlement format + EdDSA sign/verify lib, local `license_cache`, subscription state machine + `require_active_subscription`, seat enforcement. Tests. *(No cloud calls yet — entitlement injected/signed by a dev key.)*
- **Phase C1 — Control Plane MVP (in-container):** companies/installations/licenses/subscriptions, activation, entitlement issuance/rotation/revocation, version policy. Tests.
- **Phase C2 — Billing Integration:** `BillingProvider` abstraction + RevenueCat/Stripe adapter + webhook receiver (signed, idempotent) → Control Plane state. Simulated-webhook tests. **HUMAN REQUIRED:** RevenueCat account + Stripe connection + product/entitlement setup.
- **Phase C3 — Office Commercial UI:** Administration → Subscription (seats/status/Manage Billing/Add Seats), lapse banner/recovery page, refresh. Frontend tests.
- **Phase C4 — Pairing + Relay:** pairing token issuance + QR/numeric UI; relay outbound tunnel (installation side) + routing; Mobile pairing/resolve; verify 5-check chain. In-container relay test.
- **Phase C5 — Mobile Commercial UX:** first-run connect (scan/enter code), license-lock screen, version enforcement, preserve pending queue on lapse. Node tests + **HUMAN device verification**.
- **Phase C6 — Windows Installer + Services:** bundle PG/Python/frontend, services, data dirs, first-run wizard, non-destructive install/upgrade/repair. **HUMAN REQUIRED (Windows).**
- **Phase C7 — Update Service + Signing:** signed manifests, update agent (backup→verify→migrate→healthcheck→rollback), Administration → Updates. **HUMAN REQUIRED:** code-signing cert.

---

## 20. DECISION REQUIRED (need your call before/within relevant phase)

1. **Central hosting**: where do Control Plane / Billing / Relay / Update Service run? (Emergent-hosted single app? A cloud VM/managed host you own?)
2. **Installer tech**: WiX/MSI (recommended, enterprise) vs. Inno Setup (simpler).
3. **Windows service host**: NSSM vs. native service wrapper vs. WiX-built services.
4. **Relay transport**: WebSocket-over-TLS tunnel (recommended) vs. an existing tunneling framework.
5. **Grace period default** (e.g., 7 vs. 14 days) and **entitlement refresh interval** (e.g., 6–12h) + **offline `grace_until`** window (e.g., 7 days).
6. **SUSPENDED scope**: block business reads too (recommended, unambiguous) vs. read-only allowed.
7. **Private key protection on Windows**: plain ACL-restricted file vs. DPAPI-wrapped (Windows-only).
8. **Stripe Managed Payments (via RevenueCat)** for tax/merchant-of-record — yes/no.
9. **Embedded PostgreSQL version/packaging** for Windows (PG 15 bundle) confirmation.

## 21. HUMAN REQUIRED (credentials / accounts / external actions)

- **RevenueCat account** + project; connect your **existing Stripe account**; import products; configure entitlements + Web Purchase Links + webhook secret.
- **Stripe** products/prices for the seat-based subscription (pricing amounts deferred — not hardcoded).
- **Windows code-signing certificate** (EV recommended), timestamping — private key stays off-repo.
- **Central hosting** provisioning + TLS domain(s) for Control Plane / Relay / Update Service.
- **Windows test VM** for installer/service/update verification (cannot be done in this Linux container).
- **Apple App Store / Google Play** developer accounts for Mobile distribution + EAS signing (already deferred).
- Ensure `EMERGENT_LLM_KEY` + `SECRETS_ENCRYPTION_KEY` remain in production env (existing requirement).

## 22. Explicitly Deferred (not in this phase unless separately approved)

Helcim, pricing amounts, coupons/discounts, annual plans, reseller/franchise/multi-company, self-service data migration, public signup, trials, complex tiers, enterprise SSO, reseller/affiliate portals, advanced billing analytics.

---

## 23. Summary Recommendation

Adopt: **EdDSA-signed JWS entitlements** validated locally with an offline grace window; a **small central Control Plane** (licensing/seats/pairing/versions/identity/relay-routing only, zero business data); **RevenueCat Web Billing + Stripe** behind a `BillingProvider` abstraction (Helcim-ready); an **outbound WebSocket-TLS Relay** with local RBAC authoritative; a **WiX/MSI Windows installer** bundling PG/Python/frontend + services + first-run wizard; and a **signed auto-update agent** with backup-before-migrate and loud-fail rollback. Additive-only local schema; existing business workflows untouched. Windows installer/service/update + all signing/billing accounts are HUMAN REQUIRED; central services + local licensing logic are buildable and testable in-container.

**Awaiting approval + answers to §20 DECISION REQUIRED before Phase C0.**
