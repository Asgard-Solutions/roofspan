import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { ProtectedRoute, RequireSensitive } from "@/components/ProtectedRoute";
import { Toaster } from "@/components/ui/sonner";
import AppShell from "@/components/AppShell";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import MapView from "@/pages/MapView";
import Leads from "@/pages/Leads";
import Placeholder from "@/pages/Placeholder";
import Users from "@/pages/admin/Users";
import Roles from "@/pages/admin/Roles";
import AuditLog from "@/pages/admin/AuditLog";
import Settings from "@/pages/admin/Settings";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
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
            <Route path="/customers" element={<Placeholder title="Customers" />} />
            <Route path="/jobs" element={<Placeholder title="Jobs" />} />
            <Route path="/inventory" element={<Placeholder title="Inventory" />} />
            <Route path="/finance" element={<Placeholder title="Finance" />} />
            <Route path="/reports" element={<Placeholder title="Reports" />} />
            <Route path="/admin/users" element={<RequireSensitive><Users /></RequireSensitive>} />
            <Route path="/admin/roles" element={<RequireSensitive><Roles /></RequireSensitive>} />
            <Route path="/admin/audit" element={<RequireSensitive><AuditLog /></RequireSensitive>} />
            <Route path="/admin/settings" element={<RequireSensitive><Settings /></RequireSensitive>} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </AuthProvider>
  );
}

export default App;
