import { Download, MonitorDown, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WINDOWS_INSTALLER_AVAILABLE, WINDOWS_INSTALLER_URL } from "@/lib/config";

// Windows installer download action. Points DIRECTLY at the CloudFront installer URL — never proxied
// through the backend, never fetched into JS memory. Falls back to a graceful "coming soon" state.
export function WindowsDownload({ variant = "card" }) {
  const available = WINDOWS_INSTALLER_AVAILABLE;

  if (variant === "public") {
    return (
      <div className="mt-6 text-center" data-testid="windows-download-public">
        {available ? (
          <a
            href={WINDOWS_INSTALLER_URL}
            rel="noopener"
            className="inline-flex items-center gap-2 text-sm font-semibold text-white/90 transition-colors hover:text-white"
            data-testid="windows-download-public-link"
          >
            <Download className="h-4 w-4" /> Download RoofSpan for Windows
          </a>
        ) : (
          <span className="inline-flex items-center gap-2 text-sm text-white/60" data-testid="windows-download-public-soon">
            <Clock className="h-4 w-4" /> Windows installer coming soon
          </span>
        )}
        <p className="mx-auto mt-1 max-w-sm text-xs text-white/50">
          Install RoofSpan Office on your Windows computer. A RoofSpan subscription and organization account are required to activate and use the application.
        </p>
      </div>
    );
  }

  // "card" — authenticated Owner/Admin dashboard section
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6" data-testid="windows-download-card">
      <div className="flex items-start gap-4">
        <div className="rounded-md bg-orange-50 p-3">
          <MonitorDown className="h-6 w-6 text-orange-600" />
        </div>
        <div className="flex-1">
          <h3 className="font-heading text-lg font-bold text-slate-900">RoofSpan Desktop</h3>
          <p className="mt-1 text-sm text-slate-500">
            Download the RoofSpan installer for Windows. After installation, connect and activate RoofSpan for your organization.
          </p>
          <div className="mt-4">
            {available ? (
              <Button asChild className="gap-2 bg-orange-600 hover:bg-orange-700">
                <a href={WINDOWS_INSTALLER_URL} rel="noopener" data-testid="windows-download-card-link">
                  <Download className="h-4 w-4" /> Download for Windows
                </a>
              </Button>
            ) : (
              <Button disabled variant="secondary" className="gap-2" data-testid="windows-download-card-soon">
                <Clock className="h-4 w-4" /> Windows installer coming soon
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
