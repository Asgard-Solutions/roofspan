import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Building2, Users2, ShieldCheck, Calculator, Layers, BookOpen, PackageSearch, Map, DatabaseBackup, CreditCard, ScrollText, Wrench, ChevronRight } from "lucide-react";

const GROUPS = [
  { title: "Company", need: "sensitive", items: [
    { to: "/admin/settings?tab=company", label: "Company profile", hint: "Name, contact details, proposal branding, margin warning", icon: Building2, testid: "settings-company" },
  ] },
  { title: "Team & Access", need: "sensitive", items: [
    { to: "/admin/users", label: "Users & mobile access", hint: "Add employees, reset passwords, pair phones", icon: Users2, testid: "settings-users" },
    { to: "/admin/roles", label: "Roles & permissions", hint: "What each role can see and do", icon: ShieldCheck, testid: "settings-roles" },
  ] },
  { title: "Estimating Setup", need: "manage", items: [
    { to: "/estimating/takeoff", label: "Roof takeoff", hint: "Turn measurements into estimate quantities", icon: Calculator, testid: "settings-takeoff" },
    { to: "/estimating/assemblies", label: "Assemblies", hint: "Reusable bundles of materials and labor", icon: Layers, testid: "settings-assemblies" },
    { to: "/estimating/price-books", label: "Price books", hint: "Your default selling prices", icon: BookOpen, testid: "settings-price-books" },
  ] },
  { title: "Integrations", need: "sensitive", items: [
    { to: "/admin/settings/abc", label: "ABC Supply", hint: "Pricing and ordering from your ABC account", icon: PackageSearch, testid: "settings-abc" },
    { to: "/admin/settings?tab=integrations", label: "Maps & property data", hint: "Satellite imagery, address lookup, property import", icon: Map, testid: "settings-integrations" },
  ] },
  { title: "Backup & Plan", need: "sensitive", items: [
    { to: "/admin/backups", label: "Backup & recovery", hint: "Backup health, schedule, restore", icon: DatabaseBackup, testid: "settings-backups" },
    { to: "/admin/subscription", label: "Plan & subscription", hint: "Your RoofSpan plan and billing", icon: CreditCard, testid: "settings-subscription" },
  ] },
  { title: "System", need: "sensitive", items: [
    { to: "/admin/audit", label: "Audit log", hint: "Who changed what, and when", icon: ScrollText, testid: "settings-audit" },
    { to: "/admin/settings?tab=advanced", label: "Advanced", hint: "Technical provider settings and software version, for support", icon: Wrench, testid: "settings-advanced" },
  ] },
];

export default function SettingsHub() {
  const { user, isSensitive } = useAuth();
  const isManage = ["owner", "administrator", "office"].includes(user?.role);
  const allowed = (g) => (g.need === "sensitive" ? isSensitive : isManage);
  return (
    <div>
      <PageHeader title="Settings" description="Set up your business once. RoofSpan handles the rest." testid="page-settings-hub" />
      <div className="grid max-w-5xl grid-cols-1 gap-8 p-6 sm:p-8 lg:grid-cols-2">
        {GROUPS.filter(allowed).map((g) => (
          <section key={g.title} data-testid={`settings-group-${g.title.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">{g.title}</h2>
            <div className="divide-y divide-border rounded-md border border-border bg-white">
              {g.items.map((it) => (
                <Link key={it.to} to={it.to} className="group flex items-center gap-3 px-4 py-3 transition-colors hover:bg-slate-50" data-testid={it.testid}>
                  <it.icon className="h-5 w-5 shrink-0 text-orange-600" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-slate-900">{it.label}</div>
                    <div className="truncate text-xs text-slate-500">{it.hint}</div>
                  </div>
                  <ChevronRight className="h-4 w-4 text-slate-300 transition-transform group-hover:translate-x-0.5" />
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
