import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Loader2, ShieldAlert } from "lucide-react";

function Loading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background" data-testid="auth-loading">
      <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
    </div>
  );
}

export function ProtectedRoute({ children }) {
  const { user } = useAuth();
  if (user === undefined) return <Loading />;
  if (user === null) return <Navigate to="/login" replace />;
  return children;
}

export function RequireSensitive({ children }) {
  const { user, isSensitive } = useAuth();
  if (user === undefined) return <Loading />;
  if (user === null) return <Navigate to="/login" replace />;
  if (!isSensitive) {
    return (
      <div className="p-8" data-testid="no-permission">
        <div className="flex max-w-md items-start gap-3 rounded-md border border-border bg-white p-6">
          <ShieldAlert className="mt-0.5 h-5 w-5 text-destructive" />
          <div>
            <h3 className="font-heading text-lg font-semibold text-slate-900">Access restricted</h3>
            <p className="mt-1 text-sm text-slate-500">
              This area is limited to Owners and Administrators.
            </p>
          </div>
        </div>
      </div>
    );
  }
  return children;
}
