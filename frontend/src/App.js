import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { ProtectedRoute, RequireSensitive } from "@/components/ProtectedRoute";
import { Toaster } from "@/components/ui/sonner";
import AppShell from "@/components/AppShell";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import MapView from "@/pages/MapView";
import Leads from "@/pages/Leads";
import LeadDetail from "@/pages/LeadDetail";
import Customers from "@/pages/Customers";
import Jobs from "@/pages/Jobs";
import JobDetail from "@/pages/JobDetail";
import Inventory from "@/pages/Inventory";
import ProductCatalog from "@/pages/ProductCatalog";
import MaterialDetail from "@/pages/MaterialDetail";
import PurchaseOrderDetail from "@/pages/PurchaseOrderDetail";
import InventoryLocations from "@/pages/InventoryLocations";
import EstimateEditor from "@/pages/EstimateEditor";
import Assemblies from "@/pages/Assemblies";
import PriceBooks from "@/pages/PriceBooks";
import Suppliers from "@/pages/Suppliers";
import Finance from "@/pages/Finance";
import Placeholder from "@/pages/Placeholder";
import Users from "@/pages/admin/Users";
import Roles from "@/pages/admin/Roles";
import AuditLog from "@/pages/admin/AuditLog";
import BackupStatus from "@/pages/admin/BackupStatus";
import Subscription from "@/pages/admin/Subscription";
import Settings from "@/pages/admin/Settings";
import AbcSupply from "@/pages/admin/AbcSupply";

// RoofSpan Office — the LOCAL browser UI packaged with the Windows installation. This is NOT a hosted
// SaaS app and NOT the public roofspan.io website (that is a separate app at /app/roofspan-website).
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
            <Route path="/leads/:id" element={<LeadDetail />} />
            <Route path="/customers" element={<Customers />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
            <Route path="/inventory" element={<Inventory />} />
            <Route path="/inventory/catalog" element={<ProductCatalog />} />
            <Route path="/inventory/locations" element={<InventoryLocations />} />            <Route path="/inventory/abc-catalog" element={<Navigate to="/inventory/catalog" replace />} />
            <Route path="/inventory/materials/:id" element={<MaterialDetail />} />
            <Route path="/suppliers" element={<Suppliers />} />
            <Route path="/purchase-orders/:id" element={<PurchaseOrderDetail />} />
            <Route path="/estimates/:id" element={<EstimateEditor />} />
            <Route path="/estimating/assemblies" element={<Assemblies />} />
            <Route path="/estimating/price-books" element={<PriceBooks />} />
            <Route path="/finance" element={<Finance />} />
            <Route path="/reports" element={<Placeholder title="Reports" />} />
            <Route path="/admin/users" element={<RequireSensitive><Users /></RequireSensitive>} />
            <Route path="/admin/roles" element={<RequireSensitive><Roles /></RequireSensitive>} />
            <Route path="/admin/audit" element={<RequireSensitive><AuditLog /></RequireSensitive>} />
            <Route path="/admin/backups" element={<RequireSensitive><BackupStatus /></RequireSensitive>} />
            <Route path="/admin/subscription" element={<RequireSensitive><Subscription /></RequireSensitive>} />
            <Route path="/admin/settings" element={<RequireSensitive><Settings /></RequireSensitive>} />
            <Route path="/admin/settings/abc" element={<RequireSensitive><AbcSupply /></RequireSensitive>} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </AuthProvider>
  );
}

export default App;
