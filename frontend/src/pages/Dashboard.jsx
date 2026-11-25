import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Contact, UserX, BellRing, CalendarClock, FileSignature, Hammer, ArrowRight, Boxes, PackageOpen, ShoppingCart, Truck as TruckIcon, AlertTriangle, Warehouse, DatabaseBackup, Wallet, ChevronDown } from "lucide-react";
import { money, shortDate, shortDay } from "@/lib/format";
import { WHEN_STYLE, WHEN_LABEL, dateTime, tz } from "@/lib/followups";

function BackupAlert() {
  const [h, setH] = useState(null);
  useEffect(() => { api.get("/admin/backups/health").then((r) => setH(r.data)).catch(() => {}); }, []);
  if (!h || h.level === "ok") return null;
  const cls = h.level === "error" ? "border-red-200 bg-red-50 text-red-800" : "border-amber-200 bg-amber-50 text-amber-800";
  return (
    <Link to="/admin/backups" className={`flex items-center gap-2 rounded-md border px-4 py-3 text-sm font-medium ${cls}`} data-testid="dashboard-backup-badge">
      <DatabaseBackup className="h-4 w-4" /><span data-testid="dashboard-backup-badge-label">{h.label}</span><ArrowRight className="ml-auto h-4 w-4" />
    </Link>
  );
}

function AttentionCard({ title, icon: Icon, count, sub, items, empty, viewAll, testid, renderMeta }) {
  return (
    <div className="flex flex-col rounded-md border border-border bg-white" data-testid={testid}>
      <div className="flex items-start justify-between border-b border-border px-5 py-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700"><Icon className="h-4 w-4 text-orange-600" />{title}</div>
          {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
        </div>
        <span className="font-heading text-3xl font-bold leading-none text-slate-900" data-testid={`${testid}-count`}>{count}</span>
      </div>
      <div className="flex-1">
        {items.length === 0 && <div className="px-5 py-4 text-sm text-slate-400">{empty}</div>}
        {items.map((it, i) => (
          <Link key={it.id || i} to={it.link} className="flex items-center justify-between gap-3 border-b border-border px-5 py-2.5 last:border-0 hover:bg-slate-50" data-testid={`${testid}-item-${i}`}>
            <div className="min-w-0">
              <div className="truncate text-sm text-slate-800">{it.title}</div>
              {it.subtitle && <div className="truncate text-xs text-slate-400">{it.subtitle}</div>}
            </div>
            <div className="whitespace-nowrap text-xs text-slate-500">{renderMeta ? renderMeta(it) : shortDate(it.date)}</div>
          </Link>
        ))}
      </div>
      {viewAll && <Link to={viewAll} className="border-t border-border px-5 py-2.5 text-xs font-medium text-orange-700 hover:bg-orange-50/50" data-testid={`${testid}-view-all`}>View all</Link>}
    </div>
  );
}

function MaterialIssues({ d }) {
  const sevCls = { warn: "text-amber-600", info: "text-blue-600", error: "text-red-600" };
  const items = (d?.action_required || []).slice(0, 6);
  return (
    <div className="flex flex-col rounded-md border border-border bg-white" data-testid="attention-materials">
      <div className="flex items-start justify-between border-b border-border px-5 py-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700"><Boxes className="h-4 w-4 text-orange-600" />Material problems & deliveries</div>
          <div className="mt-0.5 text-xs text-slate-500">{d ? `${d.cards.incoming_this_week} deliveries due this week` : "…"}</div>
        </div>
        <span className="font-heading text-3xl font-bold leading-none text-slate-900" data-testid="attention-materials-count">{d ? (d.action_required || []).length : "—"}</span>
      </div>
      {items.length === 0 && <div className="px-5 py-4 text-sm text-slate-400">No material problems.</div>}
      {items.map((a, i) => (
        <Link key={i} to={a.link} className="flex items-center gap-2 border-b border-border px-5 py-2.5 last:border-0 hover:bg-slate-50" data-testid={`action-${a.type}-${i}`}>
          <AlertTriangle className={`h-4 w-4 shrink-0 ${sevCls[a.severity] || "text-slate-400"}`} /><span className="truncate text-sm text-slate-700">{a.message}</span>
        </Link>
      ))}
    </div>
  );
}

function PurchasingSnapshot({ d }) {
  const [open, setOpen] = useState(false);
  if (!d) return null;
  const c = d.cards;
  const card = (label, value, Icon, tid, sub) => (
    <div className="rounded-md border border-border bg-white p-4" data-testid={tid}>
      <div className="flex items-center justify-between"><span className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</span><Icon className="h-4 w-4 text-slate-400" /></div>
      <div className="mt-1.5 font-heading text-2xl font-bold text-slate-900">{value}</div>
      {sub ? <div className="text-xs text-slate-400">{sub}</div> : null}
    </div>
  );
  return (
    <Collapsible open={open} onOpenChange={setOpen} data-testid="purchasing-intelligence">
      <CollapsibleTrigger className="flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-900" data-testid="purchasing-toggle">
        <ChevronDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} /> Inventory & purchasing snapshot
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {d.cost_visible && card("Inventory Value", money(c.inventory_value), Warehouse, "card-inventory-value", "At average cost")}
        {card("Low Stock", c.low_stock_items, Boxes, "card-low-stock")}
        {card("Reserved", c.reserved_quantity, PackageOpen, "card-reserved", d.cost_visible ? money(c.reserved_value) : null)}
        {card("Open POs", c.open_purchase_orders, ShoppingCart, "card-open-pos", d.cost_visible ? `${money(c.open_po_committed_value)} committed` : null)}
        {card("Incoming (7d)", c.incoming_this_week, TruckIcon, "card-incoming")}
        {card("Jobs Short", c.jobs_needing_materials, Hammer, "card-jobs-short")}
        {card("Backordered", c.backordered_items, AlertTriangle, "card-backordered")}
      </CollapsibleContent>
    </Collapsible>
  );
}

export default function Dashboard() {
  const { user, isSensitive } = useAuth();
  const [a, setA] = useState(null);
  const [p, setP] = useState(null);
  useEffect(() => {
    api.get("/dashboard/attention", { params: { tz: tz() } }).then((r) => setA(r.data)).catch(() => {});
    api.get("/dashboard/purchasing").then((r) => setP(r.data)).catch(() => {});
  }, []);
  const firstName = (user?.full_name || user?.email || "").split(" ")[0];
  const s = (k) => a?.[k] || { count: "—", items: [] };

  return (
    <div>
      <PageHeader title={`Welcome, ${firstName}`} description="Here's what needs your attention." testid="page-dashboard" />
      <div className="space-y-6 p-6 sm:p-8">
        {isSensitive && <BackupAlert />}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <AttentionCard title="Follow-ups due" icon={BellRing} testid="attention-follow-ups" count={s("follow_ups").count} items={s("follow_ups").items}
            sub={a ? `${a.follow_ups.overdue_count} overdue · ${a.follow_ups.today_count} due today` : null} empty="No follow-ups due. Nice work." viewAll={a && !a.follow_ups.overdue_count && a.follow_ups.today_count ? "/leads?view=today" : "/leads?view=overdue"}
            renderMeta={(it) => <span className={`rounded px-1.5 py-0.5 ${WHEN_STYLE[it.when]}`}>{it.when === "today" ? dateTime(it.date).split(", ").pop() : `${WHEN_LABEL[it.when]} · ${shortDate(it.date)}`}</span>} />
          <AttentionCard title="Inspections booked" icon={CalendarClock} testid="attention-inspections" count={s("inspections").count} items={s("inspections").items}
            sub="Today and the next 7 days" empty="No inspections booked." viewAll="/leads"
            renderMeta={(it) => <span className={it.when === "overdue" ? "font-medium text-red-600" : ""}>{it.when === "overdue" ? "Results missing" : dateTime(it.date)}</span>} />
          <AttentionCard title="Proposals needing attention" icon={FileSignature} testid="attention-proposals" count={s("proposals").count} items={s("proposals").items}
            sub={a ? `Not sent or no answer for 3+ days · ${money(a.proposals.total)}` : null} empty="No proposals need attention." viewAll="/sales/quotes" renderMeta={(it) => money(it.amount)} />
          <AttentionCard title="Leads with no follow-up" icon={Contact} testid="attention-no-follow-up" count={s("no_follow_up").count} items={s("no_follow_up").items}
            sub="Open leads with nothing scheduled" empty="Every open lead has a next step." viewAll="/leads?view=none" renderMeta={(it) => it.status} />
          {a?.unassigned && (
            <AttentionCard title="Unassigned leads" icon={UserX} testid="attention-unassigned" count={a.unassigned.count} items={a.unassigned.items}
              sub={a.overdue_by_rep?.length ? `Overdue: ${a.overdue_by_rep.map((r) => `${r.name} ${r.count}`).join(" · ")}` : "No overdue follow-ups by rep"}
              empty="Every open lead has an owner." viewAll="/leads?view=unassigned" renderMeta={(it) => it.status} />
          )}
          <AttentionCard title="Jobs scheduled & in progress" icon={Hammer} testid="attention-jobs" count={s("jobs").count} items={s("jobs").items}
            empty="No jobs scheduled." viewAll="/jobs" renderMeta={(it) => (it.date ? shortDay(it.date) : it.status.replace("_", " "))} />
          <MaterialIssues d={p} />
          {a?.money && (
            <AttentionCard title="Money due" icon={Wallet} testid="attention-money" count={money(a.money.open_total)} items={a.money.items}
              sub={a.money.overdue_count ? `${a.money.overdue_count} overdue · ${money(a.money.overdue_total)}` : `${a.money.open_count} open invoice${a.money.open_count === 1 ? "" : "s"}`}
              empty="Nothing outstanding." viewAll="/billing" renderMeta={(it) => <span className={it.overdue ? "font-medium text-red-600" : ""}>{money(it.amount)}</span>} />
          )}
        </div>
        <PurchasingSnapshot d={p} />
      </div>
    </div>
  );
}
