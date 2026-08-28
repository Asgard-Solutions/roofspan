// Resources / articles. Original, truthful buyer-education content. Each article links to the relevant
// RoofSpan product pages via `related`. No invented stats, customers, or quotes.

export const ARTICLES = {
  "roofing-crm-software-buyers-guide": {
    title: "Roofing CRM Software Buyer's Guide",
    description: "What to look for in roofing CRM software — from property intelligence and canvassing to jobs and material purchasing — and the questions to ask before you buy.",
    dek: "A practical guide to choosing roofing CRM software that fits how roofing companies actually sell and build.",
    datePublished: "2026-06-01",
    sections: [
      { h2: "Start with the whole workflow, not just contacts", p: ["Most CRMs were built for generic B2B sales. Roofing runs differently: you find properties, organize territories, knock doors, inspect roofs, quote work, order materials, and run the job. A roofing CRM should connect those stages instead of forcing your team to stitch tools together.", "When you evaluate a roofing CRM, map it against your real process end to end. If a step lives in a spreadsheet or a second app, that's where data gets lost."] },
      { h2: "Look for property intelligence and canvassing", p: ["The strongest roofing systems begin before the lead exists — on the map. Look for property records with owner and occupancy context, the ability to draw territories and canvass sections, and a field app that lets salespeople work their assigned area and create leads on site."] },
      { h2: "Check the material and job side", p: ["Roofing is a materials business. Ask whether the system connects purchasing to the job, and whether it integrates with a supplier so pricing and ordering happen in one place. RoofSpan connects ABC Supply purchasing directly to the job."] },
      { h2: "Questions to ask before you buy", p: ["Where does my data live? Who can see what? What happens in the field with no signal? How are territories assigned? Can a rep create a lead from a property without re-keying it in the office? Clear answers to these separate a roofing CRM from a repurposed generic one."] },
    ],
    related: ["roofing-crm-software", "roofing-canvassing-software", "roofing-job-management-software"],
  },

  "roofing-canvassing-software-buyers-guide": {
    title: "Roofing Canvassing Software Buyer's Guide",
    description: "How to evaluate roofing canvassing software: property mapping, territory sections, Do-Not-Knock, rep assignments, visit outcomes, and office/field synchronization.",
    dek: "What separates real roofing canvassing software from a pin-drop map.",
    datePublished: "2026-06-01",
    sections: [
      { h2: "Canvassing is planning plus fieldwork", p: ["Good canvassing software does two jobs: it helps the office plan where to knock, and it helps reps work the doors. If a tool only does one, your team pays for it with manual handoffs."] },
      { h2: "What the office needs", p: ["Look for real property data on the map, the ability to draw canvass sections, a count of properties inside each section, overlap detection so two reps don't work the same street, and Do-Not-Knock handling that carries into the field."] },
      { h2: "What the rep needs", p: ["Reps need their assigned area on a property map, owner and occupancy context, a fast way to record visit outcomes, photo and inspection capture, and lead creation — all working when connectivity is poor, then syncing back to the office."] },
      { h2: "Synchronization is the hidden requirement", p: ["The field and the office must share one record. RoofSpan keeps field data locally cached and queued, then synchronizes to Office when a connection is available, so canvassing becomes a pipeline you can manage."] },
    ],
    related: ["roofing-canvassing-software", "roofing-territory-management", "roofing-field-sales-software"],
  },

  "how-to-organize-roofing-sales-territories": {
    title: "How to Organize Roofing Sales Territories",
    description: "A step-by-step approach to organizing roofing sales territories: map your market, draw canvass sections, resolve overlaps, and assign areas to salespeople.",
    dek: "Turn a whole market into sections a rep can actually finish.",
    datePublished: "2026-06-01",
    sections: [
      { h2: "1. Put the market on one map", p: ["Start with the properties in your market on a single map. Property context — type, ownership, and where available year built and square footage — helps you decide which areas are worth working first."] },
      { h2: "2. Draw territories, then smaller sections", p: ["Divide the market into territories, then break each into canvass sections small enough for one rep to complete. Because sections are drawn on real property data, you always know how many doors are inside."] },
      { h2: "3. Resolve overlaps before assigning", p: ["Overlapping assignments waste effort and annoy homeowners. Catch overlaps while planning, and respect Do-Not-Knock properties across the whole plan."] },
      { h2: "4. Assign to salespeople", p: ["Assign each section to a specific rep who then sees the area in RoofSpan Mobile. As they work, outcomes and leads sync back so your plan reflects reality."] },
    ],
    related: ["roofing-territory-management", "roofing-canvassing-software", "roofing-field-sales-software"],
  },

  "roofing-crm-vs-general-crm": {
    title: "Roofing CRM vs General CRM",
    description: "The practical differences between a roofing-specific CRM and a general CRM — property intelligence, canvassing, field sales, and material purchasing built for roofing.",
    dek: "Why roofing teams outgrow generic CRMs.",
    datePublished: "2026-06-01",
    sections: [
      { h2: "General CRMs start at the lead", p: ["A general CRM assumes you already have a lead and a contact. Roofing sales usually start earlier — on the map, at the property, at the door. That gap is where a general CRM makes roofing teams improvise."] },
      { h2: "Roofing CRMs start at the property", p: ["A roofing CRM brings property intelligence and canvassing into the system, so leads are created from real properties and carry their context forward into inspections, quotes, and jobs."] },
      { h2: "Materials are part of the job", p: ["General CRMs rarely touch purchasing. Roofing runs on materials, so connecting supplier pricing and ordering to the job — as RoofSpan does with ABC Supply — removes a whole layer of duplicate work."] },
      { h2: "Field reality", p: ["Roofing happens outside, often with poor signal. A roofing CRM's field app has to keep working offline and sync later; a bolt-on mobile view usually doesn't."] },
    ],
    related: ["roofing-crm-software", "roofing-property-intelligence", "abc-supply-integration"],
  },

  "manage-roofing-leads-first-visit-to-completed-job": {
    title: "How to Manage Roofing Leads From First Visit to Completed Job",
    description: "Follow a roofing lead from the first door knock through inspection, quote, job, and materials — and see how to keep it on one record the whole way.",
    dek: "One record from the first knock to the closed-out job.",
    datePublished: "2026-06-01",
    sections: [
      { h2: "First visit: capture it where it happens", p: ["A rep working a canvass section records the visit outcome at the property and, when there's interest, creates a lead on the spot — with photos and notes attached to the right property."] },
      { h2: "Inspection and estimate", p: ["The lead moves to inspection, where field photos and notes are captured against the job, then to an estimate and quote — all on the same record the office and field share."] },
      { h2: "Quote accepted becomes a job", p: ["An accepted quote becomes an organized job with its own number, scope, status, and value, so nothing is retyped and nothing is lost between sales and production."] },
      { h2: "Materials and completion", p: ["Purchasing connects to the job through the ABC Supply integration — pricing, purchase orders, ordering, and receiving — so the job runs to completion from the same set of records it started on."] },
    ],
    related: ["roofing-crm-software", "roofing-job-management-software", "abc-supply-integration"],
  },

  "abc-supply-integration-for-roofing-contractors": {
    title: "ABC Supply Integration for Roofing Contractors",
    description: "How RoofSpan's ABC Supply integration works for roofing contractors: connect your account, search the catalog, pull customer-specific pricing, order, and receive against the job.",
    dek: "Bring ABC Supply purchasing into the roofing job.",
    datePublished: "2026-06-01",
    sections: [
      { h2: "Connect your own ABC Supply account", p: ["RoofSpan uses your company's own ABC Supply account and branch, so catalog search, pricing, and ordering reflect your relationship — not generic list prices."] },
      { h2: "Customer-specific pricing and purchase orders", p: ["Pull account-specific pricing, refresh it before you order, and build purchase orders you can review. Add delivery details, place the order, and retrieve order details without leaving the job."] },
      { h2: "Track, receive, and reuse", p: ["Follow order history and templates, track orders, and receive materials into the job's material workflow so purchasing and production stay aligned."] },
      { h2: "An honest note on scope", p: ["Account-specific pricing reflects your ABC Supply pricing and does not by itself confirm product availability. RoofSpan connects to ABC Supply using your account and does not claim to be an official or certified ABC Supply partner."] },
    ],
    related: ["abc-supply-integration", "roofing-job-management-software", "roofing-software-pricing"],
  },
};

export const ARTICLE_SLUGS = Object.keys(ARTICLES);
