import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Contact } from "lucide-react";

const STATUSES = [
  { value: "new", label: "New" },
  { value: "working", label: "Working" },
  { value: "qualified", label: "Qualified" },
  { value: "lost", label: "Lost" },
  { value: "converted", label: "Converted" },
];

const statusColor = {
  new: "bg-blue-50 text-blue-700",
  working: "bg-amber-50 text-amber-700",
  qualified: "bg-green-50 text-green-700",
  lost: "bg-slate-100 text-slate-500",
  converted: "bg-orange-50 text-orange-700",
};

export default function Leads() {
  const [leads, setLeads] = useState([]);

  const load = useCallback(() => {
    api.get("/leads").then((r) => setLeads(r.data)).catch((e) => toast.error(apiError(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const updateStatus = async (id, status) => {
    try {
      await api.patch(`/leads/${id}`, { status });
      toast.success("Lead updated");
      load();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  return (
    <div>
      <PageHeader title="Leads" description={`${leads.length} lead${leads.length === 1 ? "" : "s"} from property acquisition`} testid="page-leads" />
      <div className="p-6 sm:p-8">
        {leads.length === 0 ? (
          <div className="flex max-w-xl items-start gap-4 rounded-md border border-dashed border-border bg-white p-8">
            <Contact className="mt-0.5 h-6 w-6 text-orange-500" />
            <div>
              <h3 className="font-heading text-lg font-semibold text-slate-900">No leads yet</h3>
              <p className="mt-1 text-sm text-slate-500">Convert a property or visit into a lead from the Map to see it here.</p>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-md border border-border bg-white">
            <Table data-testid="leads-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Property</TableHead>
                  <TableHead>Phone</TableHead>
                  <TableHead>Created by</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {leads.map((l) => (
                  <TableRow key={l.id} data-testid={`lead-row-${l.id}`}>
                    <TableCell className="font-medium text-slate-900">{l.name}</TableCell>
                    <TableCell className="text-slate-600">{l.property_address || l.address || "—"}</TableCell>
                    <TableCell className="text-slate-600">{l.phone || "—"}</TableCell>
                    <TableCell className="text-slate-500">{l.created_by || "—"}</TableCell>
                    <TableCell>
                      <Select value={l.status} onValueChange={(v) => updateStatus(l.id, v)}>
                        <SelectTrigger className="h-8 w-[140px]" data-testid={`lead-status-${l.id}`}>
                          <Badge className={statusColor[l.status] || ""} variant="secondary">{l.status}</Badge>
                        </SelectTrigger>
                        <SelectContent>
                          {STATUSES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
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
