# Roof Measurement Completion Design

**Date:** 2026-08-27
**Status:** Approved for implementation

## Goal

Finish the existing RoofSpan Roof Measurement subsystem so the originally approved measurement workflow is complete end-to-end across RoofSpan Field and RoofSpan Office:

**Property → Inspection → Measurement Revision → Takeoff → Estimate → Quote → Job → Material Order**

The implementation extends the existing Increment A/B/C architecture. It must not replace the estimate, inventory, purchasing, ABC Supply, Relay, or mobile offline architectures.

## Architectural boundaries

### Measurement facts

A measurement revision remains the immutable physical record. It owns structures, facets, edges, penetrations, conditions, source metadata, photos, status, and revision history.

Physical totals remain truthful even when a structure is excluded from pricing. RoofSpan therefore keeps both:

- **Measured totals** — everything captured on the property.
- **Takeoff-scoped totals** — only structures currently marked for estimate/takeoff inclusion.

Changing scope is a measurement revision change and therefore follows the existing revision/verification rules.

### Estimating rules

Takeoff templates remain the translation layer from measurement facts to estimate lines. They may consume scoped roof area/squares, pitch bands, edge lengths, penetrations, decking, stories/height, and condition flags. No estimating assumption is written back into physical measurement geometry.

## Data model completion

### Structures

Add an `included_in_scope` Boolean, defaulting to true. A structure can remain fully measured while being excluded from takeoff/pricing.

Existing structure fields remain authoritative for stories and approximate height. Takeoff derives maximum included stories/height from included structures rather than requiring duplicate summary values.

### Summary / conditions

Add structured fields for:

- `existing_condition`
- `drip_edge_lf`

The existing covering, layers, underlayment, tear-off, decking, ventilation, gutter, access, and notes fields remain intact.

### Derived totals

Preserve existing measured totals for backward compatibility. Add takeoff-scoped equivalents:

- takeoff area and squares
- takeoff area by pitch
- takeoff edge totals
- takeoff penetration counts/total
- maximum included stories
- maximum included height

Unassigned facets/edges/penetrations remain included by default so existing records do not unexpectedly lose quantities.

## Takeoff completion

### Pitch-driven labor

Support pitch-threshold metrics from measured facet pitch distribution, including common 7/12+, 9/12+, and 12/12+ square metrics. Template rules can therefore drive steep-charge labor from actual geometry instead of a manual steep-access flag.

### Stories and height

`stories` resolves from included structures, falling back to the legacy summary value only when needed. Add a `height_ft` metric from the maximum included structure height.

### Drip edge

Resolve drip edge in this order:

1. explicit estimate/takeoff override
2. measurement-level `drip_edge_lf`
3. calculated eave + rake

### Product-driven package quantity

Package conversion must use real product coverage when available. Resolution order:

1. explicit Takeoff Rule coverage override
2. selected `Material.coverage_amount` / `coverage_unit`, normalized to the estimate-line unit
3. existing SupplierMaterial conversion factor

Never hard-code three bundles per square. Preview must show package/order quantity and the source of coverage when it is known.

### Waste change visibility

A newly applied takeoff stores its effective roof waste percent. When previewing a later takeoff, return the prior effective waste percentage and the delta in waste-driven roof squares when available. Office surfaces the change before recalculation. Recalculation remains explicit and never silently changes an estimate.

## Field completion

RoofSpan Field remains touch-first and offline-first while exposing the full useful measurement record:

- structure type/name, include/exclude, stories, height, notes
- facet label, structure, pitch, area, width, length, roof material, notes
- eave/rake/ridge/hip/valley/sidewall/headwall/transition
- all penetration types used by Office plus quantity and optional dimensions/notes
- existing covering, condition, layers, underlayment
- decking type, damaged SF, replacement sheets, full re-deck
- measured drip edge and ridge vent
- steep/high/restricted/long-carry/landscaping conditions
- general/facet photos and notes

Existing synced measurements must reopen from scoped cache while Office/Relay is unavailable. Online reads refresh the cache. Offline edits update the cached snapshot immediately and remain queued until acknowledged.

For a brand-new unsynced measurement, Field maintains one local scope draft so reopening the screen does not start from a blank document or create duplicate measurement POSTs.

## Office completion

The Office worksheet exposes the same data model, optimized for desktop review:

- structure include/exclude, stories, height, attachment, notes
- facet width/length/material/notes
- complete conditions including existing condition and measured drip edge
- measured totals vs takeoff-scoped totals when exclusions exist
- existing photos, validation, status, revision history

The Takeoff workspace adds the new pitch/height metrics, product coverage/package preview, and waste-change comparison.

## Validation

Warnings stay soft. Existing warnings remain, and scope/measurement validation must additionally surface obviously incomplete scoped geometry where appropriate without blocking field completion.

Accepted quotes and completed downstream records retain the exact measurement revision and takeoff provenance already implemented.

## Import readiness

Keep source/provider/report identifiers and facet geometry unchanged. No aerial provider integration or 2D/3D roof sketch is introduced in this completion. Those remain future consumers of the same measurement model.

## Compatibility and safety

- Local PostgreSQL remains authoritative.
- Mobile continues through Relay; no direct cloud database is introduced.
- Existing measurement revisions default all structures to included.
- Existing totals/API consumers keep their original measured-total semantics.
- Existing Estimate line-item architecture is not replaced.
- Existing ABC Supply, job-material, and purchasing flows remain unchanged except that takeoff-generated quantities become more accurate.
- All schema changes are additive and migrated through Alembic.
