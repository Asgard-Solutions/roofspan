import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { useLocation, useNavigate } from "react-router-dom";
import { API_BASE } from "@/lib/api";
import { Loader2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  SETUP_STATUS_PATH,
  targetForStatus,
  STARTUP_RETRY_INTERVAL_MS,
  STARTUP_MAX_ATTEMPTS,
} from "@/lib/setupStatus";

// SetupGate — gates ALL routing until the LOCAL backend reports first-run state. A brand-new
// (uninitialized) RoofSpan Office install must never flash the login page: children (the router) are not
// rendered until the authoritative /api/setup/status decision is made. While the local backend/services +
// PostgreSQL are still starting, requests are retried (bounded) behind the loading UI; if they never
// succeed, a clear, retryable startup-error screen is shown instead of silently falling through to /login.
export default function SetupGate({
  children,
  retryIntervalMs = STARTUP_RETRY_INTERVAL_MS,
  maxAttempts = STARTUP_MAX_ATTEMPTS,
}) {
  const [phase, setPhase] = useState("checking"); // "checking" | "error" | "ready"
  const location = useLocation();
  const navigate = useNavigate();
  const attemptRef = useRef(0);
  const timerRef = useRef(null);
  const activeRef = useRef(true);

  useEffect(() => {
    activeRef.current = true;
    runCheck();
    return () => {
      activeRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runCheck = () => {
    if (!activeRef.current) return;
    setPhase("checking");
    axios
      .get(`${API_BASE}${SETUP_STATUS_PATH}`)
      .then(({ data }) => {
        if (!activeRef.current) return;
        const target = targetForStatus(data && data.state, location.pathname);
        if (target) navigate(target, { replace: true });
        setPhase("ready"); // only now do we render the router (never before the decision)
      })
      .catch(() => {
        if (!activeRef.current) return;
        attemptRef.current += 1;
        if (attemptRef.current < maxAttempts) {
          timerRef.current = setTimeout(runCheck, retryIntervalMs); // stay in "checking" (loading UI)
        } else {
          setPhase("error"); // bounded timeout exhausted — surface a retryable startup error
        }
      });
  };

  const retry = () => {
    attemptRef.current = 0;
    if (timerRef.current) clearTimeout(timerRef.current);
    runCheck();
  };

  if (phase === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background" data-testid="setup-gate-loading">
        <div className="flex flex-col items-center gap-3 text-slate-400">
          <Loader2 className="h-6 w-6 animate-spin" />
          <p className="text-sm" data-testid="setup-gate-loading-text">Starting RoofSpan Office…</p>
        </div>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-6" data-testid="setup-gate-error">
        <div className="flex max-w-md flex-col items-center gap-4 text-center">
          <AlertTriangle className="h-8 w-8 text-amber-500" />
          <div>
            <h1 className="text-lg font-semibold text-slate-800" data-testid="setup-gate-error-title">
              Can’t reach RoofSpan Office
            </h1>
            <p className="mt-1 text-sm text-slate-500" data-testid="setup-gate-error-message">
              The local RoofSpan service isn’t responding yet. It may still be starting. Please wait a
              moment and try again.
            </p>
          </div>
          <Button onClick={retry} data-testid="setup-gate-retry-button">Retry</Button>
        </div>
      </div>
    );
  }

  return children;
}
