import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Copy, KeyRound, Loader2, RefreshCw } from "lucide-react";

export const RecoveryCodeCard = ({ intro }) => {
  const [code, setCode] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .get("/recovery-code")
      .then((r) => setCode(r.data.recovery_code))
      .catch((e) => setError(apiError(e)))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const copy = () => navigator.clipboard?.writeText(code).then(() => toast.success("Recovery code copied"));

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-5" data-testid="recovery-code-card">
      <div className="flex items-center gap-2 font-heading text-base font-semibold text-slate-900">
        <KeyRound className="h-4 w-4 text-amber-600" /> Company recovery code
      </div>
      <p className="mt-1 text-sm text-slate-600">
        {intro ||
          "Keep this somewhere safe (not on this computer). You need it to restore your company on a new or reinstalled computer."}
      </p>
      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-slate-500" data-testid="recovery-code-loading">
          <Loader2 className="h-4 w-4 animate-spin" /> Connecting to RoofSpan…
        </div>
      ) : code ? (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <code
            className="rounded-md border border-amber-300 bg-white px-4 py-2 font-mono text-lg tracking-widest text-slate-900"
            data-testid="recovery-code-value"
          >
            {code}
          </code>
          <Button type="button" variant="outline" size="sm" onClick={copy} data-testid="recovery-code-copy">
            <Copy className="mr-1 h-4 w-4" /> Copy
          </Button>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-600" data-testid="recovery-code-error">
          <span>{error ? `${error.replace(/\.$/, "")}.` : "Not available yet."} You can also view it later in Admin → Settings → Company.</span>
          <Button type="button" variant="outline" size="sm" onClick={load} data-testid="recovery-code-retry">
            <RefreshCw className="mr-1 h-4 w-4" /> Try again
          </Button>
        </div>
      )}
    </div>
  );
};
