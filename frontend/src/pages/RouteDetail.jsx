import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DoorOpen, SkipForward, RotateCcw, ArrowLeft, MapPin, Loader2 } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];

const statusColor = {
  assigned: "bg-blue-50 text-blue-700",
  in_progress: "bg-amber-50 text-amber-700",
  completed: "bg-green-50 text-green-700",
};

const stopStyle = {
  pending: "border-border bg-white",
  knocked: "border-green-300 bg-green-50",
  skipped: "border-slate-300 bg-slate-50",
};

export default function RouteDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const [route, setRoute] = useState(null);
  const [reps, setReps] = useState([]);
  const [busy, setBusy] = useState(null);

  const load = useCallback(() => {
    api.get(`/routes/${id}`).then((r) => setRoute(r.data)).catch((e) => {
      toast.error(apiError(e));
      navigate("/routes");
    });
  }, [id, navigate]);

  useEffect(() => {
    load();
    if (canManage) api.get("/users/assignable").then((r) => setReps(r.data)).catch(() => {});
  }, [load, canManage]);

  const setStop = async (stopId, status) => {
    setBusy(stopId);
    try {
      const { data } = await api.put(`/routes/${id}/stops/${stopId}`, { status });
      setRoute(data);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(null);
    }
  };

  const reassign = async (userId) => {
    try {
      const { data } = await api.put(`/routes/${id}/assign`, { user_id: userId || null });
      setRoute(data);
      toast.success("Route reassigned");
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  if (!route) {
    return <div className="flex h-64 items-center justify-center text-slate-400"><Loader2 className="h-6 w-6 animate-spin" /></div>;
  }

  const done = route.knocked + route.skipped;
  const pct = route.stop_count ? Math.round((done / route.stop_count) * 100) : 0;

  return (
    <div>
      <PageHeader
        title={route.name}
        description={`${route.stop_count} stops${route.est_miles > 0 ? ` · ~${route.est_miles} mi walking` : ""}`}
        testid="page-route-detail"
        actions={
          <Button variant="outline" size="sm" onClick={() => navigate("/routes")} data-testid="route-back-button">
            <ArrowLeft className="h-4 w-4" /> All routes
          </Button>
        }
      />
      <div className="space-y-6 p-6 sm:p-8">
        <div className="flex flex-wrap items-center gap-4 rounded-md border border-border bg-white p-4">
          <Badge className={statusColor[route.status] || ""} variant="secondary" data-testid="route-detail-status">{route.status.replace("_", " ")}</Badge>
          <div className="min-w-[200px] flex-1">
            <div className="mb-1 flex justify-between text-xs text-slate-500">
              <span data-testid="route-progress-text">{route.knocked} knocked · {route.skipped} skipped · {route.pending} left</span>
              <span>{pct}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-orange-500 transition-all" style={{ width: `${pct}%` }} />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-500">Rep:</span>
            {canManage ? (
              <select
                value={route.assigned_user_id || ""}
                onChange={(e) => reassign(e.target.value)}
                className="h-9 rounded-md border border-input bg-white px-2 text-sm"
                data-testid="route-detail-assign"
              >
                <option value="">Unassigned</option>
                {reps.map((u) => <option key={u.id} value={u.id}>{u.full_name || u.email}</option>)}
              </select>
            ) : (
              <span className="text-sm font-medium text-slate-800">{route.assigned_user_name || "Unassigned"}</span>
            )}
          </div>
        </div>

        <div className="space-y-2" data-testid="route-stops">
          {route.stops.map((s, i) => (
            <div key={s.id} className={`flex items-center gap-3 rounded-md border px-4 py-3 ${stopStyle[s.status]}`} data-testid={`stop-row-${s.id}`}>
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">{i + 1}</div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 truncate text-sm font-medium text-slate-900">
                  <MapPin className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                  {s.address || "Unknown address"}
                </div>
                {s.status !== "pending" && (
                  <span className={`text-xs ${s.status === "knocked" ? "text-green-700" : "text-slate-500"}`} data-testid={`stop-status-${s.id}`}>
                    {s.status}
                  </span>
                )}
              </div>
              <div className="flex shrink-0 gap-1.5">
                {s.status === "pending" ? (
                  <>
                    <Button size="sm" variant="secondary" disabled={busy === s.id} onClick={() => setStop(s.id, "knocked")} data-testid={`stop-knock-${s.id}`}>
                      <DoorOpen className="h-4 w-4" /> Knocked
                    </Button>
                    <Button size="sm" variant="ghost" disabled={busy === s.id} onClick={() => setStop(s.id, "skipped")} data-testid={`stop-skip-${s.id}`}>
                      <SkipForward className="h-4 w-4" /> Skip
                    </Button>
                  </>
                ) : (
                  <Button size="sm" variant="ghost" disabled={busy === s.id} onClick={() => setStop(s.id, "pending")} data-testid={`stop-reset-${s.id}`}>
                    <RotateCcw className="h-4 w-4" /> Reset
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
