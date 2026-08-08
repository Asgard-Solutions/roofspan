# RoofSpan Field (Mobile)

Expo / React Native field app. Architecture: **Mobile → RoofSpan FastAPI → PostgreSQL**. No direct DB/RentCast access; no provider secrets on device.

## Run
```
cd /app/mobile
yarn        # install
yarn web    # Expo web preview
yarn start  # Expo Go on a device/emulator
```
API base is in `app.json` → `extra.apiBase`.

## Key pieces
- `src/queue.js` — pure offline mutation queue + sync core (idempotency-key preserved on retry). Node-testable.
- `src/storage.js` — expo-sqlite: durable pending-mutation queue + read-through cache (NOT authoritative).
- `src/sync.js` — wires queue↔storage↔network (NetInfo). Only a server ack flips a mutation to `synced`.
- `src/api.js` — axios + token from `expo-secure-store`; `send()` applies Idempotency-Key + If-Match.
- Screens: Home / Leads / Map / Jobs / More (+ LeadDetail, Inspection, JobDetail).

## Offline sync test (runs against the live backend)
```
node src/tests/sync.node.test.js
```
Proves: create offline → persist → restart → retry same key → server accepts once → Office shows one record; plus visible conflict on stale update.

## Device-only behaviors (verify via Expo Go)
SecureStore, SQLite persistence across real app kill, camera/photo capture, native MapLibre rendering, background/offline transitions.
