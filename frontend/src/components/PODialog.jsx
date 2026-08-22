import { useEffect, useState, useMemo } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Plus, Trash2, Loader2, PackageSearch, AlertTriangle, Zap } from "lucide-react";
import AbcProductSearch from "@/components/AbcProductSearch";

const ABC_PROVIDER = "abc_supply";

export default function PODialog({ open, onOpenChange, jobId, onCreated, initialSupplierId, initialMaterialId }) {
  const [suppliers, setSuppliers] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [supplierId, setSupplierId] = useState("");
  const [expected, setExpected] = useState("");
  const [items, setItems] = useState([{ material_id: "", description: "", quantity: 1, unit: "each", unit_cost: 0 }]);
  const [abcItems, setAbcItems] = useState([]);
  const [busy, setBusy] = useState(false);

  // ABC context
  const [abcStatus, setAbcStatus] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [branches, setBranches] = useState([]);
  const [shipTo, setShipTo] = useState("");
  const [branch, setBranch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);

  const selectedSupplier = useMemo(() => suppliers.find((s) => s.id === supplierId) || null, [suppliers, supplierId]);
  const abcMode = selectedSupplier?.integration_provider === ABC_PROVIDER;

  // Load supplier + material lists whenever the dialog opens.
  useEffect(() => {
    if (!open) return;
    api.get("/suppliers", { params: { active: true } }).then((r) => setSuppliers(r.data)).catch(() => {});
    api.get("/materials").then((r) => setMaterials(r.data)).catch(() => {});
  }, [open]);

  // Apply preset supplier / material from callers (e.g. Product Catalog "Add to PO").
  useEffect(() => {
    if (!open) return;
    if (initialSupplierId) setSupplierId(initialSupplierId);
    if (initialMaterialId) {
      setItems([{ material_id: initialMaterialId, description: "", quantity: 1, unit: "each", unit_cost: 0 }]);
    }
  }, [open, initialSupplierId, initialMaterialId]);

  // Pre-fill line descriptions once materials are known and a preset material was supplied.
  useEffect(() => {
    if (open && initialMaterialId && materials.length) {
      const m = materials.find((x) => x.id === initialMaterialId);
      if (m) setItems((prev) => prev.map((it, i) => (i === 0 ? { ...it, description: m.name, unit: m.unit || "each", unit_cost: it.unit_cost || m.primary_supplier_cost || m.best_known_cost || 0 } : it)));
    }
  }, [open, initialMaterialId, materials]);

  useEffect(() => {
    if (open && abcMode && !abcStatus) {
      api.get("/integrations/abc/status").then((r) => {
        setAbcStatus(r.data);
        if (r.data.status === "connected") {
          setShipTo(r.data.default_ship_to_number || "");
          setBranch(r.data.default_branch_number || "");
          api.get("/integrations/abc/accounts").then((a) => setAccounts(a.data)).catch(() => {});
        }
      }).catch(() => {});
    }
  }, [open, abcMode, abcStatus]);

  useEffect(() => {
    if (abcMode && shipTo) {
      api.get(`/integrations/abc/branches?ship_to=${encodeURIComponent(shipTo)}`).then((r) => setBranches(r.data)).catch(() => {});
    }
  }, [abcMode, shipTo]);

  const invalidateAbcPricing = () => {
    if (abcItems.length) {
      setAbcItems((lines) => lines.map((l) => ({ ...l, abc_price: null, abc_price_status: "unavailable", unit_cost: 0 })));
      toast.warning("Ship-To/branch changed — ABC pricing was cleared. Re-add or refresh items.");
    }
  };

  const setItem = (i, patch) => setItems(items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));
  const pickMaterial = (i, mid) => {
    const m = materials.find((x) => x.id === mid);
    setItem(i, { material_id: mid, description: m?.name || "", unit: m?.unit || "each" });
  };

  const branchLabel = branches.find((b) => b.number === branch)?.name;
  const genericTotal = items.reduce((s, it) => s + (Number(it.quantity) || 0) * (Number(it.unit_cost) || 0), 0);
  const abcTotal = abcItems.reduce((s, it) => s + (Number(it.quantity) || 0) * (Number(it.unit_cost) || 0), 0);
  const total = abcMode ? abcTotal : genericTotal;
  const unresolved = abcItems.filter((l) => l.abc_price_status === "unavailable").length;

  const reset = () => {
    setSupplierId(""); setExpected(""); setAbcItems([]); setAbcStatus(null);
    setShipTo(""); setBranch(""); setBranches([]);
    setItems([{ material_id: "", description: "", quantity: 1, unit: "each", unit_cost: 0 }]);
  };

  const create = async () => {
    if (!selectedSupplier) { toast.error("Select a supplier"); return; }
    if (abcMode && (!shipTo || !branch)) { toast.error("Select a Ship-To and branch for ABC Supply"); return; }
    setBusy(true);
    try {
      const payload = {
        supplier_id: selectedSupplier.id, supplier_name: selectedSupplier.name, job_id: jobId || null,
        expected_date: expected ? new Date(expected).toISOString() : null,
      };
      if (abcMode) {
        payload.integration_provider = ABC_PROVIDER;
        payload.abc_ship_to_number = shipTo;
        payload.abc_branch_number = branch;
        payload.items = abcItems.map((it) => ({ ...it, quantity: Number(it.quantity) || 0, unit_cost: Number(it.unit_cost) || 0 }));
      } else {
        payload.items = items.filter((it) => it.material_id || it.description)
          .map((it) => ({ material_id: it.material_id || null, description: it.description, quantity: Number(it.quantity) || 0, unit: it.unit, unit_cost: Number(it.unit_cost) || 0 }));
      }
      await api.post("/purchase-orders", payload);
      toast.success("Purchase order created");
      onOpenChange(false);
      reset();
      onCreated && onCreated();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) reset(); }}>
      <DialogContent className="max-w-2xl" data-testid="po-dialog">
        <DialogHeader><DialogTitle>New purchase order</DialogTitle><DialogDescription>Select a supplier. Integrated suppliers unlock live catalog &amp; ordering.</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Supplier</Label>
              <Select value={supplierId} onValueChange={(v) => { setSupplierId(v); setAbcStatus(null); }}>
                <SelectTrigger data-testid="po-supplier"><SelectValue placeholder="Select supplier" /></SelectTrigger>
                <SelectContent>
                  {suppliers.map((s) => (
                    <SelectItem key={s.id} value={s.id} data-testid={`po-supplier-option-${s.id}`}>
                      {s.name}{s.integration_provider === ABC_PROVIDER ? " · Integrated" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5"><Label>Expected date</Label><Input type="date" value={expected} onChange={(e) => setExpected(e.target.value)} data-testid="po-expected" /></div>
          </div>

          {selectedSupplier && (
            <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="po-supplier-caps">
              {abcMode
                ? <Badge className="bg-blue-50 text-blue-700" variant="secondary"><Zap className="mr-1 h-3 w-3" /> Live catalog &amp; ordering</Badge>
                : <Badge variant="secondary" className="bg-slate-100 text-slate-500">Manual supplier</Badge>}
              {selectedSupplier.payment_terms && <span className="text-slate-400">Terms: {selectedSupplier.payment_terms}</span>}
            </div>
          )}

          {abcMode && abcStatus?.status !== "connected" && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" data-testid="abc-not-connected-warning">
              ABC Supply is not connected. Connect it under Settings → Integrations → ABC Supply to order ABC products.
            </div>
          )}

          {abcMode && abcStatus?.status === "connected" && (
            <div className="space-y-3 rounded-md border border-border bg-slate-50/60 p-3" data-testid="abc-po-context">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1"><Label className="text-xs">Ship-To</Label>
                  <Select value={shipTo} onValueChange={(v) => { setShipTo(v); setBranch(""); invalidateAbcPricing(); }}>
                    <SelectTrigger className="h-8" data-testid="po-abc-shipto"><SelectValue placeholder="Select Ship-To" /></SelectTrigger>
                    <SelectContent>{accounts.map((a) => <SelectItem key={a.number} value={a.number}>{a.name} ({a.number})</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1"><Label className="text-xs">Branch</Label>
                  <Select value={branch} onValueChange={(v) => { setBranch(v); invalidateAbcPricing(); }} disabled={!shipTo}>
                    <SelectTrigger className="h-8" data-testid="po-abc-branch"><SelectValue placeholder="Select branch" /></SelectTrigger>
                    <SelectContent>{branches.map((b) => <SelectItem key={b.number} value={b.number}>{b.name} ({b.number}){b.home_branch ? " · Home" : ""}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              </div>
              <Button variant="outline" size="sm" disabled={!shipTo || !branch} onClick={() => setSearchOpen(true)} data-testid="po-abc-search-products">
                <PackageSearch className="h-4 w-4" /> Search {selectedSupplier?.name} Products
              </Button>
              <div className="space-y-1.5">
                {abcItems.map((it, i) => (
                  <div key={i} className="flex items-center gap-2 rounded border border-border bg-white px-2 py-1.5 text-sm" data-testid={`abc-line-${i}`}>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium text-slate-800">{it.description}</div>
                      <div className="text-xs text-slate-500">{it.abc_item_number} · {it.quantity} {it.unit}</div>
                    </div>
                    {it.abc_price_status === "priced"
                      ? <span className="tabular-nums font-medium">{money(it.unit_cost)}</span>
                      : <Badge className="bg-amber-50 text-amber-700" variant="secondary">Pricing unavailable</Badge>}
                    <button onClick={() => setAbcItems(abcItems.filter((_, idx) => idx !== i))} className="text-slate-300 hover:text-red-500"><Trash2 className="h-4 w-4" /></button>
                  </div>
                ))}
                {abcItems.length === 0 && <div className="text-xs text-slate-400">No products added yet.</div>}
              </div>
              {unresolved > 0 && (
                <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" data-testid="abc-pricing-warning">
                  <AlertTriangle className="h-4 w-4" /> {unresolved} item{unresolved === 1 ? "" : "s"} do not currently have pricing.
                </div>
              )}
            </div>
          )}

          {selectedSupplier && !abcMode && (
            <div className="space-y-2">
              {items.map((it, i) => (
                <div key={i} className="grid grid-cols-[1fr_60px_80px_28px] items-center gap-2">
                  <Select value={it.material_id} onValueChange={(v) => pickMaterial(i, v)}>
                    <SelectTrigger className="h-8" data-testid={`po-material-${i}`}><SelectValue placeholder="Select material" /></SelectTrigger>
                    <SelectContent>{materials.map((m) => <SelectItem key={m.id} value={m.id}>{m.name} ({m.unit})</SelectItem>)}</SelectContent>
                  </Select>
                  <Input type="number" value={it.quantity} onChange={(e) => setItem(i, { quantity: e.target.value })} className="h-8" data-testid={`po-qty-${i}`} />
                  <Input type="number" value={it.unit_cost} onChange={(e) => setItem(i, { unit_cost: e.target.value })} className="h-8" placeholder="cost" data-testid={`po-cost-${i}`} />
                  <button onClick={() => setItems(items.filter((_, idx) => idx !== i))} className="text-slate-300 hover:text-red-500"><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={() => setItems([...items, { material_id: "", description: "", quantity: 1, unit: "each", unit_cost: 0 }])} data-testid="po-add-line"><Plus className="h-4 w-4" /> Add line</Button>
            </div>
          )}

          <div className="flex justify-between border-t border-border pt-2 font-semibold"><span>Total</span><span className="tabular-nums" data-testid="po-total">{money(total)}</span></div>
        </div>
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={create} disabled={busy || !selectedSupplier} data-testid="po-save">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create PO"}</Button></DialogFooter>
      </DialogContent>

      {abcMode && (
        <AbcProductSearch open={searchOpen} onOpenChange={setSearchOpen} shipTo={shipTo} branch={branch} branchLabel={branchLabel}
          onAdd={(line) => setAbcItems((prev) => [...prev, line])} />
      )}
    </Dialog>
  );
}
