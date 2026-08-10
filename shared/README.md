# shared/ (reserved)

Intentionally (almost) empty. This is reserved for **genuinely shared, product-neutral** code that more
than one surface needs via a stable contract — e.g.:
- protocol/frame schemas, version schemas
- public cryptographic verification contracts (verify-only; never private keys)
- immutable shared brand metadata

**Rules**
- Do NOT put business logic here.
- Do NOT create shared modules just to satisfy a diagram or to share a logo (small immutable brand assets
  may simply be duplicated per app).
- Prefer stable interfaces over source-level coupling between Office / Mobile / Website / Central Services.

Nothing has been extracted yet, because doing so today would introduce cross-surface source coupling with
no current benefit. Candidates (e.g., the relay protocol schema in `/backend/relay/protocol.py`, the
installation request-signature contract, the Windows update-manifest schema) can be promoted here later
behind clearly versioned contracts if a second surface genuinely needs to depend on them.
