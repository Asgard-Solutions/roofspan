import { ClipboardList, Users2, Camera, MapPin, ShieldCheck, Server } from "lucide-react";

// Pricing (public, approved): one product, per-seat, 5-seat minimum.
export const PRICE_PER_SEAT = 49;
export const MIN_SEATS = 5;
export const STARTING_PRICE = PRICE_PER_SEAT * MIN_SEATS; // 245

export const SITE_NAV = [
  { href: "#features", label: "Features", testid: "site-nav-features" },
  { href: "#how-it-works", label: "How It Works", testid: "site-nav-how" },
  { href: "#pricing", label: "Pricing", testid: "site-nav-pricing" },
  { href: "#download", label: "Download", testid: "site-nav-download" },
  { href: "#mobile", label: "Mobile", testid: "site-nav-mobile" },
];

export const FEATURES = [
  { icon: ClipboardList, title: "Leads & Jobs", body: "Manage roofing opportunities and active jobs from one system.", testid: "feature-leads-jobs" },
  { icon: Users2, title: "Office + Field", body: "Keep office staff and field teams connected to the same company's RoofSpan system.", testid: "feature-office-field" },
  { icon: Camera, title: "Inspections & Photos", body: "Capture inspections, field information, and photos against the right records.", testid: "feature-inspections" },
  { icon: MapPin, title: "Properties & Maps", body: "Organize property and geographic information used by roofing teams.", testid: "feature-properties" },
  { icon: ShieldCheck, title: "Team Access", body: "Manage users, roles, permissions, and licensed seats.", testid: "feature-team-access" },
  { icon: Server, title: "Local Company Data", body: "RoofSpan Office runs on your company's Windows system, keeping your operational roofing database with your RoofSpan installation.", testid: "feature-local-data" },
];

export const STEPS = [
  { n: "1", title: "Download RoofSpan Office", body: "Download RoofSpan for Windows from roofspan.io." },
  { n: "2", title: "Install it on your RoofSpan Office computer", body: "RoofSpan Office runs on your company's Windows machine and opens through a local browser interface." },
  { n: "3", title: "Add your team", body: "Create users, assign roles, and manage licensed seats." },
  { n: "4", title: "Connect RoofSpan Mobile", body: "Field users pair the free Mobile app with your RoofSpan Office installation and securely connect while away from the office." },
];

export const INCLUSIONS = [
  "Leads, jobs & customer management",
  "Inspections, photos & properties",
  "Office and field team access",
  "User roles, permissions & licensed seats",
  "Free RoofSpan Mobile companion apps",
  "Runs on your company's own Windows system",
];
