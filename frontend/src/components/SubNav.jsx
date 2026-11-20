import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/lib/utils";

const tabClass = ({ isActive }) =>
  cn(
    "border-b-2 px-1 pb-2.5 pt-3 text-sm font-medium transition-colors",
    isActive ? "border-orange-600 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-900"
  );

export function SubNav({ items, testid }) {
  return (
    <div className="flex gap-6 border-b border-border bg-white px-6 sm:px-8" data-testid={testid}>
      {items.map((t) => (
        <NavLink key={t.to} to={t.to} end className={tabClass} data-testid={t.testid}>{t.label}</NavLink>
      ))}
    </div>
  );
}

const SALES_TABS = [
  { to: "/leads", label: "Leads", testid: "sales-tab-leads" },
  { to: "/customers", label: "Customers", testid: "sales-tab-customers" },
  { to: "/sales/quotes", label: "Quotes & Proposals", testid: "sales-tab-quotes" },
];

const MATERIALS_TABS = [
  { to: "/inventory", label: "Inventory & Purchasing", testid: "materials-tab-inventory" },
  { to: "/suppliers", label: "Suppliers", testid: "materials-tab-suppliers" },
];

export function SalesLayout() {
  return <><SubNav items={SALES_TABS} testid="sales-subnav" /><Outlet /></>;
}

export function MaterialsLayout() {
  return <><SubNav items={MATERIALS_TABS} testid="materials-subnav" /><Outlet /></>;
}
