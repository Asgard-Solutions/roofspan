import { WINDOWS_INSTALLER_AVAILABLE, WINDOWS_INSTALLER_URL } from "@/lib/config";
import { Button } from "@/components/ui/button";
import { MonitorDown, Clock } from "lucide-react";

// RoofSpan Desktop (Windows) download. Direct CloudFront link (downloads.roofspan.io) — never proxied
// through the backend. Shows a graceful "coming soon" when the installer isn't published yet.
export function WindowsDownload({ className = "" }) {
  return (
    <div className={`rounded-md border border-border bg-white p-4 ${className}`} data-testid="windows-download-card">
      <div className="flex items-start gap-3">
        <div className="rounded-md bg-orange-50 p-2 text-orange-600">
          <MonitorDown className="h-5 w-5" />
        </div>
        <div className="flex-1">
          <div className="text-sm font-semibold text-slate-900">RoofSpan Desktop for Windows</div>
          <p className="mt-1 text-xs text-slate-500">
            Install RoofSpan Office on another Windows machine. The installer downloads directly from
            downloads.roofspan.io.
          </p>
          <div className="mt-3">
            {WINDOWS_INSTALLER_AVAILABLE ? (
              <Button asChild className="gap-2 bg-orange-600 hover:bg-orange-700">
                <a href={WINDOWS_INSTALLER_URL} data-testid="windows-download-button">
                  <MonitorDown className="h-4 w-4" /> Download for Windows
                </a>
              </Button>
            ) : (
              <div className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500" data-testid="windows-download-coming-soon">
                <Clock className="h-4 w-4" /> Windows installer coming soon
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
