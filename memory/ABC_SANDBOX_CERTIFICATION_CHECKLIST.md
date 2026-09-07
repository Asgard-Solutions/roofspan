# ABC Supply Sandbox Certification Checklist (Item #10 — pre-production go-live)

Purpose: exercise the RoofSpan ↔ ABC integration against the **real ABC Sandbox** (not the mock) to
certify the electronic ordering path before production go-live.

> **CREDENTIAL POLICY — READ FIRST**
> - NEVER put ABC client_id / client_secret / tokens / Ship-To / branch numbers in source code,
>   fixtures, tests, git, or chat.
> - Enter sandbox credentials ONLY through **Settings → ABC Supply** (stored encrypted) and/or the
>   deployment environment. Turn the mock OFF (unset `ABC_MOCK_ENABLED`) so calls hit ABC Sandbox.
> - Use ONLY ABC-provided sandbox test accounts and sandbox item numbers. No real customer data.

## 0. Pre-flight setup (once)
- [ ] `ABC_MOCK_ENABLED` is unset/false in the target environment (real ABC calls).
- [ ] ABC Sandbox OAuth completed in Settings → ABC Supply (user consent; scopes present:
      `pricing.read`, `order.read`, `order.write`, `account.read`).
- [ ] Default **Ship-To** and a **valid associated branch** set in Settings → ABC Supply.
- [ ] At least one RoofSpan Material mapped to a **real sandbox ABC item** (item number + UOM), and one
      **dimensional** sandbox item mapped (has length/variation).
- [ ] Confirm connection health endpoint reports ready + not-mock.

## 1. Account / catalog sanity (account.read, pricing.read)
- [ ] Ship-To search returns only non-retired accounts (empty-branch accounts filtered).
- [ ] Selected branch appears for the Ship-To; branch status active/open.
- [ ] Live pricing returns for the mapped sandbox item at the branch (batches ≤ 50 lines, purpose=ordering).
- [ ] A $0.00 price is shown as **pricing unavailable**, never as free.

## 2. Certification order matrix (each = one ABC Sandbox order via Review & Submit)
Record for each: RoofSpan PO #, ABC confirmation #, ABC order # (post-accept), and screenshots.

- [ ] **C1 — Normal ground delivery** (`deliveryService=OTG`), 1–3 mapped items, no comments.
- [ ] **C2 — Rooftop delivery** (`deliveryService=OTR`).
- [ ] **C3 — Customer pickup** (`deliveryService=CPU`).
- [ ] **C4 — Dimensional item** (line carries length value + UOM in `dimensions`).
- [ ] **C5 — Large order 50+ lines** (verify ≤99-line enforcement; multi-batch pricing; single order array).
- [ ] **C6 — Comments**: order header comment (`orderComments` code H) + one line comment
      (object `{code:"D", description}`). Verify ABC accepts the shapes.
- [ ] **C7 — Delivery appointment**: `deliveryAppointment` type `TR` with `fromTime`/`toTime`
      (+ optional `timeZoneCode`); date under `dates.deliveryRequestedFor`. Also spot-check `ST` (fromTime only)
      and `AT` (no times). Long instructions (>255 chars) overflow into an `orderComments` D entry.
- [ ] **C8 — Price change**: cause/observe a live price change at review; confirm Submit is blocked until the
      explicit acceptance checkbox is ticked; then submit with `accept_price_changes=true`.
- [ ] **C9 — Timeout / unknown reconciliation**: simulate a lost/ambiguous response (network interruption or
      ABC 502/503/504). Confirm RoofSpan records **unknown** (never auto-resubmits) and the **Verify ABC order**
      reconcile path resolves it to the true state.
- [ ] **C10 — Account/branch rejection**: attempt submit with a Ship-To on **credit hold** (`isSellable=false`)
      and/or an **inactive** Ship-To and/or a **branch no longer associated** → preflight blocks with a clear
      message; nothing is sent; no stuck pending submission (same submission_key can retry after fix).

## 3. Idempotency & lifecycle
- [ ] Re-submitting the **same** submission_key returns the same confirmation (no duplicate ABC order).
- [ ] Post-submit status refresh maps ABC status → RoofSpan normalized status; Order Status webhook (if enabled)
      updates without duplicate status events.
- [ ] Confirmed ABC PO **cannot** be locally cancelled (UI shows "Contact ABC branch to cancel/change";
      backend returns 409); ABC status stays authoritative.

## 4. Sign-off
- [ ] All C1–C10 pass with captured confirmation numbers + screenshots.
- [ ] Idempotency/lifecycle checks pass.
- [ ] No credentials committed anywhere. Mock re-enabled (or environment restored) for non-prod after certification.
- [ ] Product owner sign-off recorded (name/date).

Notes:
- Contract source of truth: `backend/integrations/abc_supply/place_order_contract.py` (CONTRACT_VERSION).
- The automated mock-backed equivalents of most rows live in `backend/tests/test_abc_*` (see the
  creation-path E2E suite). Sandbox certification is the manual real-API confirmation of the same behaviors.
