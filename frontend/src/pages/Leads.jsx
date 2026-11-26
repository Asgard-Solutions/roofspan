import { useEffect, useState, useCallback } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { LEAD_STATUSES, LEAD_STATUS_COLOR, OPEN_STATUSES, WHEN_STYLE, WHEN_LABEL, dateTime, tz } from "@/lib/followups";
import { Contact } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];
const VIEWS = [
  { key: "open", label: "Open", test: (l) => OPEN_STATUSES.includes(l.status) },
  { key: "mine", label: "Mine", test: (l, me) => OPEN_STATUSES.includes(l.status) && l.assigned_user_id === me, manage: true },
  { key: "unassigned", label: "Unassigned", test: (l) => OPEN_STATUSES.includes(l.status) && !l.assigned_user_id, manage: true },
  { key: "overdue", label: "Overdue", test: (l) => l.next_action?.when === "overdue" },
  { key: "today", label: "Due today", test: (l) => l.next_action?.when === "today" },
  { key: "none", label: "No follow-up", test: (l) => l.next_action?.when === "none" },
  { key: "won", label: "Won", test: (l) => l.status === "won" },
  { key: "lost", label: "Lost", test: (l) => l.status === "lost" },
  { key: "all", label: "All", test: () => true },
];
const RANK = { overdue: 0, today: 1, upcoming: 2, none: 3 };

function NextActionCell({ a }) {
  if (!a) return <span className="text-slate-400">—</span>;
  return (
    <div className="min-w-0">
      <div className="truncate text-slate-800">{a.text}</div>
      {a.due_at && <Badge variant="secondary" className={`mt-0.5 ${WHEN_STYLE[a.when] || ""}`}>{WHEN_LABEL[a.when]} · {dateTime(a.due_at)}</Badge>}
    </div>
  );
}

export default function Leads() {
  const { user } = useAuth();
  const isManage = MANAGE.includes(user?.role);
  const [params, setParams] = useSearchParams();
  const view = params.get("view") || "open";
  const [leads, setLeads] = useState([]);

  const load = useCallback(() => {
    api.get("/leads", { params: { tz: tz() } }).then((r) => setLeads(r.data)).catch((e) => toast.error(apiError(e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  const updateStatus = async (id, status) => {
    try { await api.patch(`/leads/${id}`, { status }); toast.success("Lead updated"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };

  const views = VIEWS.filter((v) => !v.manage || isManage);
  const cur = views.find((v) => v.key === view) || views[0];
  const shown = leads.filter((l) => cur.test(l, user?.id))
    .sort((a, b) => (RANK[a.next_action?.when] ?? 4) - (RANK[b.next_action?.when] ?? 4)
      || new Date(a.next_action?.due_at || 8.64e15) - new Date(b.next_action?.due_at || 8.64e15));
  const count = (v) => leads.filter((l) => v.test(l, user?.id)).length;

  return (
    <div>
      <PageHeader title="Leads" description={`${shown.length} of ${leads.length} lead${leads.length === 1 ? "" : "s"}`} testid="page-leads" />
      <div className="space-y-4 p-6 sm:p-8">
        <div className="flex flex-wrap gap-2" data-testid="leads-views">
          {views.map((v) => (
            <button key={v.key} type="button" onClick={() => setParams(v.key === "open" ? {} : { view: v.key })}
              className={`rounded-full border px-3 py-1 text-sm font-medium transition-colors ${cur.key === v.key ? "border-orange-500 bg-orange-50 text-orange-800" : "border-border bg-white text-slate-600 hover:border-slate-300"}`}
              data-testid={`leads-view-${v.key}`}>
              {v.label} <span className="ml-1 text-xs text-slate-400" data-testid={`leads-view-count-${v.key}`}>{count(v)}</span>
            </button>
          ))}
        </div>
        {shown.length === 0 ? (
          <div className="flex max-w-xl items-start gap-4 rounded-md border border-dashed border-border bg-white p-8" data-testid="leads-empty">
            <Contact className="mt-0.5 h-6 w-6 text-orange-500" />
            <div>
              <h3 className="font-heading text-lg font-semibold text-slate-900">{leads.length ? "Nothing here" : "No leads yet"}</h3>
              <p className="mt-1 text-sm text-slate-500">{leads.length ? "No leads match this view." : "Convert a property or visit into a lead from the Map to see it here."}</p>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-md border border-border bg-white">
            <Table data-testid="leads-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Property</TableHead>
                  <TableHead>Assigned</TableHead>
                  <TableHead className="min-w-[240px]">Next action</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.map((l) => (
                  <TableRow key={l.id} data-testid={`lead-row-${l.id}`}>
                    <TableCell className="font-medium text-slate-900"><Link to={`/leads/${l.id}`} className="hover:text-orange-600 hover:underline" data-testid={`lead-link-${l.id}`}>{l.name}</Link>
                      {l.phone && <div className="text-xs font-normal text-slate-500">{l.phone}</div>}</TableCell>
                    <TableCell className="text-slate-600">{l.property_address || l.address || "—"}</TableCell>
                    <TableCell className="text-slate-600" data-testid={`lead-assigned-${l.id}`}>{l.assigned_user_name || <span className="text-amber-700">Unassigned</span>}</TableCell>
                    <TableCell data-testid={`lead-next-${l.id}`}><NextActionCell a={l.next_action} /></TableCell>
                    <TableCell>
                      <Select value={l.status} onValueChange={(v) => updateStatus(l.id, v)}>
                        <SelectTrigger className="h-8 w-[130px]" data-testid={`lead-status-${l.id}`}>
                          <Badge className={LEAD_STATUS_COLOR[l.status] || ""} variant="secondary">{l.status}</Badge>
                        </SelectTrigger>
                        <SelectContent>
                          {LEAD_STATUSES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}
