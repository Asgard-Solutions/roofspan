// Content for the dedicated commercial SEO pages. Every claim maps to functionality that exists in
// RoofSpan today (mirrors src/content.js). No invented features, metrics, or partnerships.
// Screenshots reference real captures already in /public/screenshots.

export const PAGES = {
  "roofing-crm-software": {
    nav: "CRM",
    title: "Roofing CRM Software | RoofSpan",
    description:
      "RoofSpan is roofing CRM software that connects property intelligence, leads, inspections, quotes, and jobs in one system that runs on your company's own Windows machine.",
    eyebrow: "Roofing CRM",
    h1: "Roofing CRM software built around the whole operation",
    intro:
      "RoofSpan is a roofing CRM that starts before the lead exists. Instead of a contact list bolted onto job tracking, it connects property intelligence, canvassing, field sales, inspections, quotes, jobs, and ABC Supply purchasing so your customer record and your operation stay in one place.",
    sections: [
      { title: "From property to customer, without re-keying", body: "Create leads directly from the properties your teams work, then move each opportunity through inspection, estimate, accepted quote, and an organized roofing job — every step tied to the same property and customer record.", bullets: ["Leads created from mapped properties", "Inspections, field notes and photos on the right job", "Estimates, quotes and job records in one flow", "Customer and job history kept together"] },
      { title: "Office and field on the same records", body: "RoofSpan Office plans the work while salespeople and crews use the free RoofSpan Mobile app. Field changes — visits, leads, photos, inspections — sync back to Office so nobody works from a stale copy." },
      { title: "Your roles, your seats, your data", body: "Manage users, roles, permissions and licensed seats across the company. RoofSpan Office installs on your own Windows machine, so your operational roofing database lives with your installation." },
    ],
    screenshot: { src: "/screenshots/office-dashboard.png", label: "RoofSpan Office · Dashboard", alt: "RoofSpan Office dashboard showing active users, recent field activity and inventory metrics", w: 1600, h: 1000 },
    related: ["roofing-canvassing-software", "roofing-job-management-software", "roofing-property-intelligence"],
  },

  "roofing-canvassing-software": {
    nav: "Canvassing",
    title: "Roofing Canvassing Software | RoofSpan",
    description:
      "RoofSpan is roofing canvassing software: map properties, draw canvass sections, respect Do-Not-Knock, assign reps, record visit outcomes, and turn doors into leads from the field.",
    eyebrow: "Canvassing",
    h1: "Roofing canvassing software that starts on the map",
    intro:
      "RoofSpan turns neighborhoods into organized canvass work. Put real properties on the map, draw canvass sections, assign them to salespeople, and let reps work the doors in RoofSpan Mobile — recording outcomes, respecting Do-Not-Knock, and creating leads without leaving the field.",
    sections: [
      { title: "Plan the doors before you knock", body: "Draw territories and smaller canvass sections on the property map, see which properties fall inside each section, and catch assignment overlaps before two reps work the same street.", bullets: ["Property map with owner and occupancy context", "Draw canvass sections and territories", "See properties inside each section", "Do-Not-Knock properties respected in the field"] },
      { title: "Reps work their area in Mobile", body: "Each salesperson opens My Area to see their assigned canvass section on a property map, records visit outcomes, captures photos and inspections, and creates leads — all built for the field with locally cached data and queued updates that sync back to Office." },
      { title: "Every door becomes trackable activity", body: "Visit outcomes and new leads flow back into RoofSpan Office, so canvassing turns into a pipeline you can actually manage instead of scattered notes." },
    ],
    screenshot: { src: "/screenshots/office-map-pins.jpg", label: "RoofSpan Office · Property Pins", alt: "RoofSpan Office satellite view with owned, rented and unknown property pins for canvass planning", w: 1919, h: 1033 },
    related: ["roofing-territory-management", "roofing-field-sales-software", "roofing-property-intelligence"],
  },

  "roofing-territory-management": {
    nav: "Territory Management",
    title: "Roofing Territory Management Software | RoofSpan",
    description:
      "RoofSpan roofing territory management: draw territories and canvass sections, resolve assignment overlaps, and assign areas to salespeople who see them in RoofSpan Mobile.",
    eyebrow: "Territory management",
    h1: "Organize roofing sales territories on one map",
    intro:
      "Stop managing territories in spreadsheets and screenshots. In RoofSpan you draw territories and canvass sections directly on the property map, see exactly which properties fall inside each area, resolve overlaps, and assign sections to the right salespeople.",
    sections: [
      { title: "Draw and divide with real properties", body: "Build territories from the properties on your map, then split them into smaller canvass sections a rep can actually finish. Because sections are drawn on real property data, you always know what's inside them.", bullets: ["Territories and canvass sections on the map", "Properties counted inside each section", "Overlap detection between assignments", "Do-Not-Knock respected across the plan"] },
      { title: "Assign to the right salesperson", body: "Assign each section to a specific salesperson. They immediately see their area in RoofSpan Mobile — no exporting lists, no manual handoff." },
      { title: "Keep the plan and the field in sync", body: "As reps work their sections, outcomes and leads sync back to Office, so your territory plan reflects what's actually happening on the ground." },
    ],
    screenshot: { src: "/screenshots/office-map-satellite.jpg", label: "RoofSpan Office · Territory Map", alt: "RoofSpan Office satellite territory map with thousands of properties clustered into canvass sections", w: 1919, h: 1033 },
    related: ["roofing-canvassing-software", "roofing-field-sales-software", "roofing-property-intelligence"],
  },

  "roofing-field-sales-software": {
    nav: "Field Sales",
    title: "Roofing Field Sales Software | RoofSpan Mobile",
    description:
      "RoofSpan gives every roofing salesperson their own area in a mobile field app: property map, owner context, visit outcomes, photos, inspections, and leads that sync to the office.",
    eyebrow: "Field sales",
    h1: "Give every roofing salesperson their own area",
    intro:
      "RoofSpan Mobile is the field side of RoofSpan. Office assigns a canvass section; the salesperson opens My Area and works it — property map, owner and occupancy context, visit outcomes, photos, inspections, and new leads — with everything syncing back to the office.",
    sections: [
      { title: "My Area: the rep's whole day in one place", body: "Each salesperson sees their assigned canvass section on a property map, works door to door, and records what happened at each property.", bullets: ["Assigned canvass section on a property map", "Owner and occupancy context per property", "Record visit outcomes and Do-Not-Knock", "Capture photos and inspections in the field", "Create leads straight from properties"] },
      { title: "Built for the field", body: "RoofSpan Mobile keeps data locally cached and queues updates, so reps keep working when connectivity is poor; changes synchronize back to Office when a connection is available." },
      { title: "One record from door to job", body: "Leads, photos and inspections created in the field become part of the same job and customer records the office works from — no duplicate entry." },
    ],
    screenshot: { src: "/screenshots/mobile-area.webp", label: "RoofSpan Field · My Area", alt: "RoofSpan Mobile My Area showing a salesperson's assigned canvass section on satellite view with property pins", w: 923, h: 2000, phone: true },
    related: ["roofing-canvassing-software", "roofing-territory-management", "roofing-crm-software"],
  },

  "roofing-property-intelligence": {
    nav: "Property Intelligence",
    title: "Property Intelligence for Roofing Contractors | RoofSpan",
    description:
      "RoofSpan brings property records onto the map — owner information, property type, year built, square footage where available, and owner-occupied status — to target roofing canvassing.",
    eyebrow: "Property intelligence",
    h1: "Know the property before you knock",
    intro:
      "RoofSpan brings property records onto the map so your team can target the right homes. See owner information, address, property type, year built and square footage where available, and whether a property is owner-occupied or non-owner-occupied — tied directly into your canvassing and leads.",
    sections: [
      { title: "Property records on the map", body: "Instead of a blank map, RoofSpan shows the properties in your market with the context that helps you decide where to work.", bullets: ["Owner information and address", "Property type, year built and square footage where available", "Owner-occupied / non-owner-occupied status", "Property pins color-coded for quick reading"] },
      { title: "From intelligence to action", body: "Use property context to draw smarter canvass sections and assign the right areas to reps, then convert a property into a lead in one step when it's worth working." },
      { title: "Honest about coverage", body: "Available property and ownership information varies by source and location. RoofSpan surfaces what's available for a property rather than promising blanket coverage everywhere." },
    ],
    screenshot: { src: "/screenshots/office-property-detail.jpg", label: "RoofSpan Office · Property Detail", alt: "RoofSpan Office property detail panel with owner info, visit history, field photos and convert-to-lead", w: 1919, h: 1032 },
    related: ["roofing-canvassing-software", "roofing-territory-management", "roofing-crm-software"],
  },

  "abc-supply-integration": {
    nav: "ABC Supply Integration",
    title: "ABC Supply Integration for Roofing Software | RoofSpan",
    description:
      "Connect your ABC Supply account to RoofSpan to search the catalog, pull customer-specific pricing, build purchase orders, place orders, add delivery details, and track order history beside the job.",
    eyebrow: "RoofSpan + ABC Supply",
    h1: "ABC Supply purchasing, connected to the roofing job",
    intro:
      "RoofSpan connects your ABC Supply account to the roofing job so material selection, pricing, and ordering happen where the work lives. Search the catalog, pull your account-specific pricing, build and submit purchase orders, and follow orders through delivery and receiving — without rebuilding the job in another tool.",
    sections: [
      { title: "Connect your ABC Supply account", body: "Link your ABC Supply account and branch so pricing and ordering reflect your relationship, not generic list prices.", bullets: ["Connect your ABC Supply account", "Work with your ABC branches", "Search and browse the ABC catalog", "Link ABC products into RoofSpan inventory"] },
      { title: "Customer-specific pricing and purchase orders", body: "Pull account-specific pricing, refresh it when it changes, and build purchase orders you can review before anything is ordered.", bullets: ["Retrieve customer-specific ABC pricing", "Refresh pricing before ordering", "Prepare and review purchase orders", "Add delivery details to an order"] },
      { title: "Order, track, and receive against the job", body: "Place ABC orders from RoofSpan, retrieve order details, and follow order history and templates. Then run the job's material workflow — ordering through receiving — against the same job records.", bullets: ["Place ABC orders and retrieve order details", "Track orders and review order history", "Reuse order templates", "Receive materials into the job workflow"] },
    ],
    screenshot: { src: "/screenshots/office-jobs.png", label: "RoofSpan Office · Jobs", alt: "RoofSpan Office jobs list where ABC Supply purchasing is tied to each roofing job", w: 1600, h: 1000 },
    note: "RoofSpan connects to ABC Supply using your own ABC Supply account. Account-specific pricing reflects your ABC Supply pricing and does not by itself confirm product availability. RoofSpan does not claim to be an official or certified ABC Supply partner.",
    related: ["roofing-job-management-software", "roofing-crm-software", "roofing-software-pricing"],
    faq: [
      { q: "Do I need my own ABC Supply account?", a: "Yes. RoofSpan connects using your company's own ABC Supply account, so pricing and ordering reflect your relationship with ABC Supply." },
      { q: "Does RoofSpan show my account-specific ABC pricing?", a: "Yes. RoofSpan retrieves account-specific pricing and lets you refresh it, so purchase orders are built against your pricing. Pricing does not by itself confirm product availability." },
      { q: "Can I place ABC Supply orders from RoofSpan?", a: "Yes. You can build purchase orders, add delivery details, place orders, retrieve order details, and review order history and templates from inside RoofSpan." },
    ],
  },

  "roofing-job-management-software": {
    nav: "Job Management",
    title: "Roofing Job Management Software | RoofSpan",
    description:
      "RoofSpan roofing job management connects estimates, quotes, jobs, purchasing, inventory, receiving, and ABC Supply ordering so every job runs from one set of records.",
    eyebrow: "Job management",
    h1: "Run every roofing job from one set of records",
    intro:
      "Once a quote is accepted, RoofSpan turns it into an organized roofing job. Scope, status, materials, purchasing, receiving, and records live together — and connect to ABC Supply purchasing — so the office and the field never work from different copies.",
    sections: [
      { title: "From accepted quote to closed-out job", body: "Progress an opportunity from estimate to accepted quote to a job with its own number, scope, status and value, tracked from sold to closed out.", bullets: ["Estimates, quotes and job records in one flow", "Job number, scope, status and value tracked", "Photos, inspections and notes on the job", "Office and Mobile working the same job"] },
      { title: "Materials, purchasing and receiving", body: "Manage inventory and purchase orders, order materials through the connected ABC Supply integration, and receive materials against the job so purchasing and production stay aligned.", bullets: ["Inventory and purchase order management", "ABC Supply catalog, pricing and ordering", "Receiving and job material workflows"] },
      { title: "Your team, your data", body: "Roles, permissions and licensed seats keep the right people on the right work, and your operational roofing database lives with your own RoofSpan Office installation." },
    ],
    screenshot: { src: "/screenshots/office-jobs.png", label: "RoofSpan Office · Jobs", alt: "RoofSpan Office jobs list with job numbers, scope, status and value", w: 1600, h: 1000 },
    related: ["abc-supply-integration", "roofing-crm-software", "roofing-software-pricing"],
  },
};

export const PAGE_SLUGS = Object.keys(PAGES);

// Short, human labels used in the "Related" links and navigation.
export const PAGE_LABEL = {
  "roofing-crm-software": "Roofing CRM",
  "roofing-canvassing-software": "Roofing Canvassing",
  "roofing-territory-management": "Territory Management",
  "roofing-field-sales-software": "Field Sales",
  "roofing-property-intelligence": "Property Intelligence",
  "abc-supply-integration": "ABC Supply Integration",
  "roofing-job-management-software": "Job Management",
  "roofing-software-pricing": "Pricing",
};
