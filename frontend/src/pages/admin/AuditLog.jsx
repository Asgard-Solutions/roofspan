import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

export default function AuditLog() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get("/audit", { params: { limit: 100 } })
      .then((r) => {
        setRows(r.data.items);
        setTotal(r.data.total);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <PageHeader
        title="Audit Log"
        description={`${total} recorded action${total === 1 ? "" : "s"}`}
        testid="page-audit"
        actions={
          <Button variant="outline" size="sm" onClick={load} data-testid="audit-refresh">
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />
      <div className="p-6 sm:p-8">
        <div className="overflow-x-auto rounded-md border border-border bg-white">
          <Table data-testid="audit-table">
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Entity</TableHead>
                <TableHead>IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-sm text-slate-400">No entries.</TableCell>
                </TableRow>
              )}
              {rows.map((r) => (
                <TableRow key={r.id} data-testid={`audit-row-${r.id}`}>
                  <TableCell className="whitespace-nowrap text-sm text-slate-500">{new Date(r.timestamp).toLocaleString()}</TableCell>
                  <TableCell className="text-sm text-slate-700">{r.user_email || "—"}</TableCell>
                  <TableCell className="text-sm font-medium text-slate-900">{r.action}</TableCell>
                  <TableCell className="text-sm text-slate-500">{r.entity_type ? `${r.entity_type}${r.entity_id ? ` · ${r.entity_id.slice(0, 8)}` : ""}` : "—"}</TableCell>
                  <TableCell className="text-sm text-slate-400">{r.ip_address || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
