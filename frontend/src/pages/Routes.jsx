import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Route as RouteIcon } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];

const statusColor = {
  assigned: "bg-blue-50 text-blue-700",
  in_progress: "bg-amber-50 text-amber-700",
  completed: "bg-green-50 text-green-700",
};

export default function RoutesPage() {
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const [routes, setRoutes] = useState([]);
  const [reps, setReps] = useState([]);

  const load = useCallback(() => {
    api.get("/routes").then((r) => setRoutes(r.data)).catch((e) => toast.error(apiError(e)));
  }, []);

  useEffect(() => {
    load();
    if (canManage) api.get("/users/assignable").then((r) => setReps(r.data)).catch(() => {});
  }, [load, canManage]);

  const reassign = async (id, userId) => {
    try {
      await api.put(`/routes/${id}/assign`, { user_id: userId || null });
      toast.success("Route reassigned");
      load();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  return (
    <div>
      <PageHeader title="Routes" description={`${routes.length} canvassing route${routes.length === 1 ? "" : "s"}`} testid="page-routes" />
      <div className="p-6 sm:p-8">
        {routes.length === 0 ? (
          <div className="flex max-w-xl items-start gap-4 rounded-md border border-dashed border-border bg-white p-8" data-testid="routes-empty">
            <RouteIcon className="mt-0.5 h-6 w-6 text-orange-500" />
            <div>
              <h3 className="font-heading text-lg font-semibold text-slate-900">No routes yet</h3>
              <p className="mt-1 text-sm text-slate-500">Build a walking route on the Map, then assign it to a rep to see it here.</p>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-md border border-border bg-white">
            <Table data-testid="routes-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Route</TableHead>
                  <TableHead>Assigned to</TableHead>
                  <TableHead>Stops</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {routes.map((r) => (
                  <TableRow key={r.id} data-testid={`route-row-${r.id}`}>
                    <TableCell className="font-medium text-slate-900">
                      <Link to={`/routes/${r.id}`} className="hover:text-orange-600 hover:underline" data-testid={`route-link-${r.id}`}>{r.name}</Link>
                      {r.est_miles > 0 && <span className="ml-2 text-xs text-slate-400">~{r.est_miles} mi</span>}
                    </TableCell>
                    <TableCell className="text-slate-600">
                      {canManage ? (
                        <select
                          value={r.assigned_user_id || ""}
                          onChange={(e) => reassign(r.id, e.target.value)}
                          className="h-8 rounded-md border border-input bg-white px-2 text-sm"
                          data-testid={`route-assign-${r.id}`}
                        >
                          <option value="">Unassigned</option>
                          {reps.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.email}</option>)}
                        </select>
                      ) : (r.assigned_user_name || "—")}
                    </TableCell>
                    <TableCell className="text-slate-600">{r.stop_count}</TableCell>
                    <TableCell className="text-slate-600">
                      <span className="text-green-700">{r.knocked} knocked</span>
                      <span className="mx-1 text-slate-300">·</span>
                      <span className="text-slate-500">{r.skipped} skipped</span>
                      <span className="mx-1 text-slate-300">·</span>
                      <span className="text-blue-700">{r.pending} left</span>
                    </TableCell>
                    <TableCell>
                      <Badge className={statusColor[r.status] || ""} variant="secondary" data-testid={`route-status-${r.id}`}>
                        {r.status.replace("_", " ")}
                      </Badge>
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
