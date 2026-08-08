import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import {
  LayoutDashboard, Users2, Map, Contact, Hammer, Boxes, Wallet, BarChart3,
  Settings2, LogOut, Menu, HardHat, ShieldCheck, ScrollText, KeyRound,
} from "lucide-react";

const MAIN_NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true, testid: "nav-dashboard" },
  { to: "/leads", label: "Leads", icon: Contact, testid: "nav-leads" },
  { to: "/map", label: "Map", icon: Map, testid: "nav-map" },
  { to: "/customers", label: "Customers", icon: Users2, testid: "nav-customers" },
  { to: "/jobs", label: "Jobs", icon: Hammer, testid: "nav-jobs" },
  { to: "/inventory", label: "Inventory", icon: Boxes, testid: "nav-inventory" },
  { to: "/finance", label: "Finance", icon: Wallet, testid: "nav-finance" },
  { to: "/reports", label: "Reports", icon: BarChart3, testid: "nav-reports" },
];

const ADMIN_NAV = [
  { to: "/admin/users", label: "Users", icon: Users2, testid: "nav-admin-users" },
  { to: "/admin/roles", label: "Roles", icon: ShieldCheck, testid: "nav-admin-roles" },
  { to: "/admin/audit", label: "Audit Log", icon: ScrollText, testid: "nav-admin-audit" },
  { to: "/admin/settings", label: "Settings", icon: Settings2, testid: "nav-admin-settings" },
];

const linkClass = ({ isActive }) =>
  cn(
    "flex items-center gap-3 border-l-4 px-4 py-2.5 text-sm font-medium transition-colors",
    isActive
      ? "border-orange-600 bg-slate-100 text-slate-900"
      : "border-transparent text-slate-600 hover:bg-slate-50 hover:text-slate-900"
  );

function NavContent({ onNavigate, isSensitive }) {
  return (
    <nav className="flex flex-col gap-0.5 py-2" data-testid="sidebar-nav">
      {MAIN_NAV.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end} className={linkClass} onClick={onNavigate} data-testid={item.testid}>
          <item.icon className="h-4 w-4" />
          {item.label}
        </NavLink>
      ))}
      {isSensitive && (
        <>
          <div className="mt-4 px-4 pb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
            Administration
          </div>
          {ADMIN_NAV.map((item) => (
            <NavLink key={item.to} to={item.to} className={linkClass} onClick={onNavigate} data-testid={item.testid}>
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}
        </>
      )}
    </nav>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5 border-b border-border px-5 py-4">
      <div className="flex h-9 w-9 items-center justify-center rounded-md bg-slate-900">
        <HardHat className="h-5 w-5 text-orange-500" />
      </div>
      <div>
        <div className="font-heading text-base font-bold leading-none text-slate-900">RoofSpan</div>
        <div className="text-[11px] text-slate-400">Office</div>
      </div>
    </div>
  );
}

export default function AppShell() {
  const { user, logout, isSensitive } = useAuth();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const roleLabel = user?.role ? user.role.charAt(0).toUpperCase() + user.role.slice(1) : "";

  const UserFooter = () => (
    <div className="border-t border-border p-4">
      <div className="mb-3">
        <div className="truncate text-sm font-semibold text-slate-900" data-testid="current-user-name">
          {user?.full_name || user?.email}
        </div>
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          <KeyRound className="h-3 w-3" />
          <span data-testid="current-user-role">{roleLabel}</span>
        </div>
      </div>
      <Button variant="outline" size="sm" className="w-full justify-start gap-2" onClick={handleLogout} data-testid="logout-button">
        <LogOut className="h-4 w-4" />
        Sign out
      </Button>
    </div>
  );

  return (
    <div className="App flex min-h-screen bg-background">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r border-border bg-white md:flex" data-testid="desktop-sidebar">
        <Brand />
        <div className="flex-1 overflow-y-auto">
          <NavContent isSensitive={isSensitive} />
        </div>
        <UserFooter />
      </aside>

      {/* Mobile top bar */}
      <div className="fixed inset-x-0 top-0 z-20 flex items-center justify-between border-b border-border bg-white px-4 py-3 md:hidden">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-900">
            <HardHat className="h-4 w-4 text-orange-500" />
          </div>
          <span className="font-heading font-bold text-slate-900">RoofSpan</span>
        </div>
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" data-testid="mobile-menu-button">
              <Menu className="h-5 w-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 p-0">
            <Brand />
            <div className="flex-1 overflow-y-auto">
              <NavContent isSensitive={isSensitive} onNavigate={() => setOpen(false)} />
            </div>
            <UserFooter />
          </SheetContent>
        </Sheet>
      </div>

      {/* Main content */}
      <main className="flex-1 pt-14 md:ml-64 md:pt-0">
        <Outlet />
      </main>
    </div>
  );
}
