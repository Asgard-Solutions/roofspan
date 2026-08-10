import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { ProtectedRoute, RequireSensitive } from "@/components/ProtectedRoute";
import { Toaster } from "@/components/ui/sonner";
import AppShell from "@/components/AppShell";
import MarketingSite from "@/site/MarketingSite";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import MapView from "@/pages/MapView";
import Leads from "@/pages/Leads";
import LeadDetail from "@/pages/LeadDetail";
import Customers from "@/pages/Customers";
import Jobs from "@/pages/Jobs";
import JobDetail from "@/pages/JobDetail";
import Inventory from "@/pages/Inventory";
import Finance from "@/pages/Finance";
import Placeholder from "@/pages/Placeholder";
import Users from "@/pages/admin/Users";
import Roles from "@/pages/admin/Roles";
import AuditLog from "@/pages/admin/AuditLog";
import BackupStatus from "@/pages/admin/BackupStatus";
import Subscription from "@/pages/admin/Subscription";
import Settings from "@/pages/admin/Settings";

// Build-time surface selector. ONE codebase, two surfaces that are NEVER served together:
//  - "office" (default): the local RoofSpan Office UI bundled inside the Windows installer. Root "/"
//    is the local application (login -> dashboard). No public marketing/download page is shown.
//  - "site": the public roofspan.io marketing/download website. Root "/" is the marketing homepage.
// There is NO centrally hosted RoofSpan operational web application — the Office UI always runs locally.
const SURFACE = process.env.REACT_APP_SURFACE || "office";
const isSite = SURFACE === "site";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {isSite && <Route path="/" element={<MarketingSite />} />}
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <ProtectedRoute>
                <AppShell />
              </ProtectedRoute>
            }
          >
            {!isSite && <Route path="/" element={<Dashboard />} />}
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/map" element={<MapView />} />
            <Route path="/leads" element={<Leads />} />
            <Route path="/leads/:id" element={<LeadDetail />} />
            <Route path="/customers" element={<Customers />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
            <Route path="/inventory" element={<Inventory />} />
            <Route path="/finance" element={<Finance />} />
            <Route path="/reports" element={<Placeholder title="Reports" />} />
            <Route path="/admin/users" element={<RequireSensitive><Users /></RequireSensitive>} />
            <Route path="/admin/roles" element={<RequireSensitive><Roles /></RequireSensitive>} />
            <Route path="/admin/audit" element={<RequireSensitive><AuditLog /></RequireSensitive>} />
            <Route path="/admin/backups" element={<RequireSensitive><BackupStatus /></RequireSensitive>} />
            <Route path="/admin/subscription" element={<RequireSensitive><Subscription /></RequireSensitive>} />
            <Route path="/admin/settings" element={<RequireSensitive><Settings /></RequireSensitive>} />
          </Route>
          <Route path="*" element={<Navigate to={isSite ? "/" : "/login"} replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </AuthProvider>
  );
}

export default App;
