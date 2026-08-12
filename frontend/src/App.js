import "@/App.css";
import { useEffect, useState } from "react";
import axios from "axios";
import { BrowserRouter, Routes, Route, useLocation, useNavigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { ProtectedRoute, RequireSensitive } from "@/components/ProtectedRoute";
import { Toaster } from "@/components/ui/sonner";
import { API_BASE } from "@/lib/api";
import { Loader2 } from "lucide-react";
import AppShell from "@/components/AppShell";
import Login from "@/pages/Login";
import Setup from "@/pages/Setup";
import Dashboard from "@/pages/Dashboard";
import MapView from "@/pages/MapView";
import Leads from "@/pages/Leads";
import LeadDetail from "@/pages/LeadDetail";
import Customers from "@/pages/Customers";
import Jobs from "@/pages/Jobs";
import JobDetail from "@/pages/JobDetail";
import Inventory from "@/pages/Inventory";
import Finance from "@/pages/Finance";
import Reports from "@/pages/Reports";
import Users from "@/pages/admin/Users";
import Roles from "@/pages/admin/Roles";
import AuditLog from "@/pages/admin/AuditLog";
import BackupStatus from "@/pages/admin/BackupStatus";
import Subscription from "@/pages/admin/Subscription";
import Settings from "@/pages/admin/Settings";

// RoofSpan Office — the LOCAL browser UI packaged with the Windows installation. This is NOT a hosted
// SaaS app and NOT the public roofspan.io website (that is a separate app at /app/roofspan-website).

// Redirects a brand-new (uninitialized) installation into the first-run setup wizard, and keeps an
// already-initialized installation out of /setup. Server-side is authoritative; this is only UX routing.
function SetupGate({ children }) {
  const [ready, setReady] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    let active = true;
    axios
      .get(`${API_BASE}/setup/status`)
      .then(({ data }) => {
        if (!active) return;
        const initialized = data.state === "initialized";
        if (!initialized && location.pathname !== "/setup") navigate("/setup", { replace: true });
        else if (initialized && location.pathname === "/setup") navigate("/", { replace: true });
      })
      .catch(() => {})
      .finally(() => active && setReady(true));
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background" data-testid="setup-gate-loading">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }
  return children;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <SetupGate>
          <Routes>
            <Route path="/setup" element={<Setup />} />
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <ProtectedRoute>
                  <AppShell />
                </ProtectedRoute>
              }
            >
              <Route path="/" element={<Dashboard />} />
              <Route path="/map" element={<MapView />} />
              <Route path="/leads" element={<Leads />} />
              <Route path="/leads/:id" element={<LeadDetail />} />
              <Route path="/customers" element={<Customers />} />
              <Route path="/jobs" element={<Jobs />} />
              <Route path="/jobs/:id" element={<JobDetail />} />
              <Route path="/inventory" element={<Inventory />} />
              <Route path="/finance" element={<Finance />} />
              <Route path="/reports" element={<Reports />} />
              <Route path="/admin/users" element={<RequireSensitive><Users /></RequireSensitive>} />
              <Route path="/admin/roles" element={<RequireSensitive><Roles /></RequireSensitive>} />
              <Route path="/admin/audit" element={<RequireSensitive><AuditLog /></RequireSensitive>} />
              <Route path="/admin/backups" element={<RequireSensitive><BackupStatus /></RequireSensitive>} />
              <Route path="/admin/subscription" element={<RequireSensitive><Subscription /></RequireSensitive>} />
              <Route path="/admin/settings" element={<RequireSensitive><Settings /></RequireSensitive>} />
            </Route>
          </Routes>
        </SetupGate>
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </AuthProvider>
  );
}

export default App;
