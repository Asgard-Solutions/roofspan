import { useState, useEffect } from "react";
import { Link, Outlet, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import ChangePasswordDialog from "@/components/ChangePasswordDialog";

import { SubscriptionBanner } from "@/components/SubscriptionBanner";
import {
  Home, Map, Contact, Hammer, Boxes, Wallet, BarChart3, Settings2, LogOut, Menu, KeyRound,
} from "lucide-react";

const APPICON = "/brand/roofspan-appicon.png";
const WORDMARK_LIGHT = "/brand/roofspan-wordmark-light.webp";

const MAIN_NAV = [
  { to: "/", label: "Home", icon: Home, testid: "nav-dashboard", match: ["/"] },
  { to: "/leads", label: "Sales", icon: Contact, testid: "nav-sales", match: ["/leads", "/customers", "/sales", "/estimates", "/quotes"] },
  { to: "/map", label: "Map", icon: Map, testid: "nav-map", match: ["/map"] },
  { to: "/jobs", label: "Jobs", icon: Hammer, testid: "nav-jobs", match: ["/jobs"] },
  { to: "/inventory", label: "Materials", icon: Boxes, testid: "nav-materials", match: ["/inventory", "/suppliers", "/purchase-orders"] },
  { to: "/billing", label: "Billing", icon: Wallet, testid: "nav-billing", match: ["/billing"], manage: true },
  { to: "/reports", label: "Reports", icon: BarChart3, testid: "nav-reports", match: ["/reports"] },
];

const SETTINGS_MATCH = ["/settings", "/admin", "/estimating"];

const isOn = (path, prefixes) => prefixes.some((p) => (p === "/" ? path === "/" : path === p || path.startsWith(`${p}/`)));

const linkClass = (active) =>
  cn(
    "flex items-center gap-3 border-l-4 px-4 py-2.5 text-sm font-medium transition-colors",
    active
      ? "border-orange-600 bg-slate-100 text-slate-900"
      : "border-transparent text-slate-600 hover:bg-slate-50 hover:text-slate-900"
  );

function NavContent({ onNavigate, isManage }) {
  const { pathname } = useLocation();
  return (
    <nav className="flex flex-col gap-0.5 py-2" data-testid="sidebar-nav">
      {MAIN_NAV.filter((i) => !i.manage || isManage).map((item) => (
        <Link key={item.to} to={item.to} className={linkClass(isOn(pathname, item.match))} onClick={onNavigate} data-testid={item.testid}>
          <item.icon className="h-4 w-4" />
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

function SettingsLink({ onNavigate, isManage }) {
  const { pathname } = useLocation();
  if (!isManage) return null;
  return (
    <div className="border-t border-border">
      <Link to="/settings" className={linkClass(isOn(pathname, SETTINGS_MATCH))} onClick={onNavigate} data-testid="nav-settings">
        <Settings2 className="h-4 w-4" /> Settings
      </Link>
    </div>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5 border-b border-border px-5 py-4">
      <img src={APPICON} alt="RoofSpan" className="h-9 w-9 rounded-md" />
      <div>
        <div className="font-heading text-base font-bold leading-none text-slate-900">RoofSpan</div>
        <div className="text-[11px] text-slate-400">Office</div>
      </div>
    </div>
  );
}

export default function AppShell() {
  const { user, logout } = useAuth();
  const isManage = ["owner", "administrator", "office"].includes(user?.role);
  const [open, setOpen] = useState(false);
  const [appVersion, setAppVersion] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    api.get("/version").then(({ data }) => setAppVersion(data.display_version || data.version || "")).catch(() => {});
  }, []);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const roleLabel = user?.role ? user.role.charAt(0).toUpperCase() + user.role.slice(1) : "";

  const UserFooter = () => (
    <div className="border-t border-border p-4">
      <div className="mb-2">
        <div className="truncate text-sm font-semibold text-slate-900" data-testid="current-user-name">{user?.full_name || user?.email}</div>
        <div className="flex items-center gap-1.5 text-xs text-slate-500">
          <KeyRound className="h-3 w-3" />
          <span data-testid="current-user-role">{roleLabel}</span>
        </div>
      </div>
      <ChangePasswordDialog />
      <Button variant="outline" size="sm" className="mt-1 w-full justify-start gap-2" onClick={handleLogout} data-testid="logout-button">
        <LogOut className="h-4 w-4" /> Sign out
      </Button>
      {appVersion && (
        <div className="mt-3 text-[11px] text-slate-400" data-testid="app-version" title="RoofSpan Office version (for support)">
          RoofSpan Office v{appVersion}
        </div>
      )}
    </div>
  );

  return (
    <div className="App flex min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r border-border bg-white md:flex" data-testid="desktop-sidebar">
        <Brand />
        <div className="flex-1 overflow-y-auto"><NavContent isManage={isManage} /></div>
        <SettingsLink isManage={isManage} />
        <UserFooter />
      </aside>

      <div className="fixed inset-x-0 top-0 z-20 flex items-center justify-between border-b border-border bg-white px-4 py-2.5 md:hidden">
        <img src={WORDMARK_LIGHT} alt="RoofSpan" className="h-8 rounded" />
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" data-testid="mobile-menu-button"><Menu className="h-5 w-5" /></Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 p-0">
            <Brand />
            <div className="flex-1 overflow-y-auto"><NavContent isManage={isManage} onNavigate={() => setOpen(false)} /></div>
            <SettingsLink isManage={isManage} onNavigate={() => setOpen(false)} />
            <UserFooter />
          </SheetContent>
        </Sheet>
      </div>

      <main className="flex-1 pt-14 md:ml-64 md:pt-0">
        <SubscriptionBanner />
        <Outlet />
      </main>
    </div>
  );
}