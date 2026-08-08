import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { UserPlus, Loader2, Search } from "lucide-react";

export default function Customers() {
  const { user } = useAuth();
  const canManage = ["owner", "administrator", "office", "sales"].includes(user?.role);
  const [customers, setCustomers] = useState([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", phone: "", email: "", billing_address: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get(`/customers${q ? `?q=${encodeURIComponent(q)}` : ""}`).then((r) => setCustomers(r.data)).catch((e) => toast.error(apiError(e)));
  }, [q]);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!form.name.trim()) { toast.error("Name is required"); return; }
    setBusy(true);
    try { await api.post("/customers", form); toast.success("Customer created"); setOpen(false); setForm({ name: "", phone: "", email: "", billing_address: "" }); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title="Customers" description={`${customers.length} customer${customers.length === 1 ? "" : "s"}`} testid="page-customers"
        actions={canManage && <Button onClick={() => setOpen(true)} data-testid="add-customer-button"><UserPlus className="h-4 w-4" /> Add customer</Button>} />
      <div className="p-6 sm:p-8">
        <div className="relative mb-4 max-w-sm">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search customers" className="pl-8" data-testid="customer-search" />
        </div>
        <div className="overflow-x-auto rounded-md border border-border bg-white">
          <Table data-testid="customers-table">
            <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Phone</TableHead><TableHead>Email</TableHead><TableHead>Properties</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
            <TableBody>
              {customers.map((c) => (
                <TableRow key={c.id} data-testid={`customer-row-${c.id}`}>
                  <TableCell className="font-medium text-slate-900">{c.name}</TableCell>
                  <TableCell className="text-slate-600">{c.phone || "—"}</TableCell>
                  <TableCell className="text-slate-600">{c.email || "—"}</TableCell>
                  <TableCell className="text-slate-500">{c.property_ids.length}</TableCell>
                  <TableCell><Badge variant="secondary">{c.status}</Badge></TableCell>
                </TableRow>
              ))}
              {customers.length === 0 && <TableRow><TableCell colSpan={5} className="text-center text-sm text-slate-400">No customers.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid="create-customer-dialog">
          <DialogHeader><DialogTitle>Add customer</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5"><Label>Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="cust-name" /></div>
            <div className="space-y-1.5"><Label>Phone</Label><Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} data-testid="cust-phone" /></div>
            <div className="space-y-1.5"><Label>Email</Label><Input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="cust-email" /></div>
            <div className="space-y-1.5"><Label>Billing address</Label><Input value={form.billing_address} onChange={(e) => setForm({ ...form, billing_address: e.target.value })} data-testid="cust-address" /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={create} disabled={busy} data-testid="save-customer">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
