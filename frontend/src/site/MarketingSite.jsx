import {
  ClipboardList, Users2, Camera, MapPin, ShieldCheck, Server,
  Download, MonitorDown, Smartphone, Check, ArrowRight, Clock,
} from "lucide-react";
import { SiteHeader } from "@/site/SiteHeader";
import { SiteFooter } from "@/site/SiteFooter";
import { WINDOWS_INSTALLER_AVAILABLE, WINDOWS_INSTALLER_URL } from "@/lib/config";

const HERO_BG = "/brand/roofspan-login-bg.png";
const FIELD_IMG =
  "https://images.unsplash.com/photo-1659353586512-bcc4c7182d01?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200";

const FEATURES = [
  { icon: ClipboardList, title: "Leads & Jobs", body: "Manage roofing opportunities and active jobs from one system.", testid: "feature-leads-jobs" },
  { icon: Users2, title: "Office + Field", body: "Keep office staff and field teams connected to the same company's RoofSpan system.", testid: "feature-office-field" },
  { icon: Camera, title: "Inspections & Photos", body: "Capture inspections, field information, and photos against the right records.", testid: "feature-inspections" },
  { icon: MapPin, title: "Properties & Maps", body: "Organize property and geographic information used by roofing teams.", testid: "feature-properties" },
  { icon: ShieldCheck, title: "Team Access", body: "Manage users, roles, permissions, and licensed seats.", testid: "feature-team-access" },
  { icon: Server, title: "Local Company Data", body: "RoofSpan Office runs on your company's Windows system, keeping your operational roofing database with your RoofSpan installation.", testid: "feature-local-data" },
];

const STEPS = [
  { n: "1", title: "Download RoofSpan Office", body: "Download RoofSpan for Windows from roofspan.io." },
  { n: "2", title: "Install it on your RoofSpan Office computer", body: "RoofSpan Office runs on your company's Windows machine and opens through a local browser interface." },
  { n: "3", title: "Add your team", body: "Create users, assign roles, and manage licensed seats." },
  { n: "4", title: "Connect RoofSpan Mobile", body: "Field users pair the free Mobile app with your RoofSpan Office installation and securely connect while away from the office." },
];

const INCLUSIONS = [
  "Leads, jobs & customer management",
  "Inspections, photos & properties",
  "Office and field team access",
  "User roles, permissions & licensed seats",
  "Free RoofSpan Mobile companion apps",
  "Runs on your company's own Windows system",
];

function Hero() {
  return (
    <section id="top" className="relative overflow-hidden bg-slate-950" data-testid="site-hero">
      <div className="absolute inset-0 bg-cover bg-center opacity-40" style={{ backgroundImage: `url(${HERO_BG})` }} />
      <div className="absolute inset-0 bg-gradient-to-b from-slate-950/80 via-slate-950/70 to-slate-950" />
      <div className="relative mx-auto max-w-6xl px-5 py-24 sm:py-32">
        <span className="inline-flex items-center gap-2 rounded-full border border-orange-500/40 bg-orange-500/10 px-3.5 py-1 text-xs font-bold uppercase tracking-widest text-orange-400" data-testid="hero-coming-soon">
          <Clock className="h-3.5 w-3.5" /> Coming Soon
        </span>
        <h1 className="mt-6 max-w-3xl font-heading text-4xl font-extrabold leading-[1.05] tracking-tight text-white sm:text-5xl lg:text-6xl">
          Roofing operations,<br className="hidden sm:block" /> connected from office to field.
        </h1>
        <p className="mt-6 max-w-2xl text-base leading-relaxed text-slate-300 sm:text-lg">
          RoofSpan gives roofing companies one connected system for managing leads, jobs, inspections,
          photos, field teams, and day-to-day operations — while keeping company business data on their
          own RoofSpan system.
        </p>
        <div className="mt-9 flex flex-wrap items-center gap-4">
          <a href="#features" className="inline-flex items-center gap-2 rounded-md bg-orange-600 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-orange-700" data-testid="hero-see-features">
            See Features <ArrowRight className="h-4 w-4" />
          </a>
          <a href="#how-it-works" className="inline-flex items-center gap-2 rounded-md border border-white/25 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-white/10" data-testid="hero-how-it-works">
            How RoofSpan Works
          </a>
        </div>
      </div>
    </section>
  );
}

function Features() {
  return (
    <section id="features" className="border-b border-slate-200 bg-white py-20 sm:py-24" data-testid="site-features">
      <div className="mx-auto max-w-6xl px-5">
        <p className="text-sm font-semibold uppercase tracking-widest text-orange-600">Features</p>
        <h2 className="mt-2 max-w-2xl font-heading text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          One system for the whole roofing operation
        </h2>
        <div className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-lg border border-slate-200 bg-white p-6 transition-colors hover:border-orange-300" data-testid={f.testid}>
              <div className="inline-flex rounded-md bg-orange-50 p-3">
                <f.icon className="h-6 w-6 text-orange-600" />
              </div>
              <h3 className="mt-4 font-heading text-lg font-bold text-slate-900">{f.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-500">{f.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function HowItWorks() {
  return (
    <section id="how-it-works" className="border-b border-slate-200 bg-slate-50 py-20 sm:py-24" data-testid="site-how-it-works">
      <div className="mx-auto max-w-6xl px-5">
        <p className="text-sm font-semibold uppercase tracking-widest text-orange-600">How It Works</p>
        <h2 className="mt-2 max-w-2xl font-heading text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          Installed on your system. Not in someone else's cloud.
        </h2>
        <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s) => (
            <div key={s.n} className="rounded-lg border border-slate-200 bg-white p-6" data-testid={`step-${s.n}`}>
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-slate-900 font-heading text-lg font-bold text-white">{s.n}</div>
              <h3 className="mt-4 font-heading text-base font-bold text-slate-900">{s.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-500">{s.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ArchitectureStrip() {
  return (
    <section className="bg-slate-950 py-20 sm:py-24" data-testid="site-architecture">
      <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-10 px-5 lg:grid-cols-2">
        <div>
          <h2 className="font-heading text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Your RoofSpan system. Your company's operation.
          </h2>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-slate-300">
            RoofSpan Office runs on your company's Windows system while RoofSpan Mobile securely connects
            field users back to it. Your operational roofing data stays with your own RoofSpan installation.
          </p>
        </div>
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <img src={FIELD_IMG} alt="Roofing field team using RoofSpan" className="h-64 w-full object-cover sm:h-80" loading="lazy" />
        </div>
      </div>
    </section>
  );
}

function Pricing() {
  return (
    <section id="pricing" className="border-b border-slate-200 bg-white py-20 sm:py-24" data-testid="site-pricing">
      <div className="mx-auto max-w-6xl px-5">
        <p className="text-sm font-semibold uppercase tracking-widest text-orange-600">Pricing</p>
        <h2 className="mt-2 font-heading text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          Simple, per-user pricing
        </h2>
        <div className="mt-12 max-w-md">
          <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm" data-testid="pricing-card">
            <h3 className="font-heading text-xl font-bold text-slate-900">RoofSpan</h3>
            <div className="mt-4 flex items-end gap-1">
              <span className="font-heading text-5xl font-extrabold tracking-tight text-slate-900" data-testid="pricing-amount">$49</span>
              <span className="mb-1 text-sm font-medium text-slate-500">per user / month</span>
            </div>
            <p className="mt-2 text-sm text-slate-500" data-testid="pricing-minimum">5-user minimum</p>
            <p className="mt-1 text-sm font-semibold text-slate-900" data-testid="pricing-starting">Starting at $245/month</p>
            <ul className="mt-6 space-y-2.5">
              {INCLUSIONS.map((i) => (
                <li key={i} className="flex items-start gap-2.5 text-sm text-slate-600">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-orange-600" /> {i}
                </li>
              ))}
            </ul>
            <div className="mt-8">
              <span className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-slate-900 px-6 py-3 text-sm font-semibold text-white" data-testid="pricing-cta">
                <Clock className="h-4 w-4" /> Coming Soon
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function DownloadSection() {
  return (
    <section id="download" className="border-b border-slate-200 bg-slate-50 py-20 sm:py-24" data-testid="site-download">
      <div className="mx-auto max-w-6xl px-5">
        <div className="flex flex-col items-start gap-6 rounded-xl border border-slate-200 bg-white p-8 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-4">
            <div className="rounded-md bg-orange-50 p-3">
              <MonitorDown className="h-7 w-7 text-orange-600" />
            </div>
            <div>
              <h2 className="font-heading text-xl font-bold text-slate-900 sm:text-2xl">RoofSpan Office for Windows</h2>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate-500">
                Install RoofSpan Office on your company's Windows computer to run your RoofSpan system
                locally and connect your office and field teams.
              </p>
            </div>
          </div>
          <div className="shrink-0">
            {WINDOWS_INSTALLER_AVAILABLE ? (
              <a
                href={WINDOWS_INSTALLER_URL}
                rel="noopener"
                className="inline-flex items-center gap-2 rounded-md bg-orange-600 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-orange-700"
                data-testid="download-windows-link"
              >
                <Download className="h-4 w-4" /> Download RoofSpan for Windows
              </a>
            ) : (
              <span className="inline-flex items-center gap-2 rounded-md bg-slate-200 px-6 py-3 text-sm font-semibold text-slate-500" data-testid="download-windows-soon">
                <Clock className="h-4 w-4" /> Coming Soon
              </span>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function MobileSection() {
  return (
    <section id="mobile" className="bg-white py-20 sm:py-24" data-testid="site-mobile">
      <div className="mx-auto max-w-6xl px-5">
        <div className="inline-flex rounded-md bg-orange-50 p-3">
          <Smartphone className="h-6 w-6 text-orange-600" />
        </div>
        <h2 className="mt-4 font-heading text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">RoofSpan Mobile</h2>
        <p className="mt-4 max-w-xl text-base leading-relaxed text-slate-500">
          Keep your field team connected to your company's RoofSpan Office system from iPhone and Android.
          The Mobile apps are free companion apps.
        </p>
        <div className="mt-8 flex flex-wrap gap-4">
          <span className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-5 py-3 text-sm font-semibold text-slate-500" data-testid="mobile-ios-soon">
            <Clock className="h-4 w-4" /> Coming Soon for iPhone
          </span>
          <span className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-5 py-3 text-sm font-semibold text-slate-500" data-testid="mobile-android-soon">
            <Clock className="h-4 w-4" /> Coming Soon for Android
          </span>
        </div>
      </div>
    </section>
  );
}

export default function MarketingSite() {
  return (
    <div className="min-h-screen bg-white" data-testid="marketing-site">
      <SiteHeader />
      <main>
        <Hero />
        <Features />
        <HowItWorks />
        <ArchitectureStrip />
        <Pricing />
        <DownloadSection />
        <MobileSection />
      </main>
      <SiteFooter />
    </div>
  );
}
