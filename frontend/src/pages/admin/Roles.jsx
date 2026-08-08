import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { ShieldCheck, User } from "lucide-react";

export default function Roles() {
  const [roles, setRoles] = useState([]);

  useEffect(() => {
    api.get("/users/roles").then((r) => setRoles(r.data)).catch(() => {});
  }, []);

  return (
    <div>
      <PageHeader
        title="Roles"
        description="RoofSpan uses four simple roles. Permissions are enforced by the backend."
        testid="page-roles"
      />
      <div className="p-6 sm:p-8">
        <div className="max-w-3xl divide-y divide-border rounded-md border border-border bg-white" data-testid="roles-list">
          {roles.map((r) => (
            <div key={r.key} className="flex items-start gap-3 p-5" data-testid={`role-${r.key}`}>
              <div className={`mt-0.5 flex h-9 w-9 items-center justify-center rounded-md ${r.sensitive ? "bg-slate-900" : "bg-slate-100"}`}>
                {r.sensitive ? <ShieldCheck className="h-5 w-5 text-orange-500" /> : <User className="h-5 w-5 text-slate-500" />}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-heading font-semibold text-slate-900">{r.label}</span>
                  {r.sensitive && (
                    <span className="rounded-sm bg-orange-50 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-orange-700">
                      Sensitive access
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-sm text-slate-500">{r.description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
