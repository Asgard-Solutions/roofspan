import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Plus, Trash2, Loader2, Layers, Search } from "lucide-react";

const UNITS = ["EA", "PC", "BDL", "SQ", "RL", "BX", "PL", "LF", "SF", "GAL", "PAIL"];
const emptyItem = () => ({ material_id: "", description: "", quantity_factor: 1, unit: "EA", waste_override: "", is_labor: false });

export default function Assemblies() {
  const [rows, setRows] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", category: "", unit_basis: "SQ", notes: "", items: [emptyItem()] });

  const load = useCallback(async () => {
    setLoading(true);
    try { const { data } = await api.get("/estimating/assemblies"); setRows(data); }
    catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); api.get("/materials", { params: { active: true } }).then((r) => setMaterials(r.data)).catch(() => {}); }, [load]);

  const openNew = () => { setEditing(null); setForm({ name: "", category: "", unit_basis: "SQ", notes: "", items: [emptyItem()] }); setOpen(true); };
  const openEdit = async (a) => {
    const { data } = await api.get(`/estimating/assemblies/${a.id}`);
    setEditing(a.id);
    setForm({ name: data.name, category: data.category || "", unit_basis: data.unit_basis, notes: data.notes || "",
      items: data.items.length ? data.items.map((it) => ({ material_id: it.material_id || "", description: it.description, quantity_factor: it.quantity_factor, unit: it.unit, waste_override: it.waste_override ?? "", is_labor: it.is_labor })) : [emptyItem()] });
    setOpen(true);
  };
  const setItem = (i, patch) => setForm((f) => ({ ...f, items: f.items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)) }));

  const save = async () => {
    try {
      const payload = { name: form.name, category: form.category || null, unit_basis: form.unit_basis, notes: form.notes || null,
        items: form.items.filter((it) => it.description || it.material_id).map((it) => ({ material_id: it.material_id || null, description: it.description, quantity_factor: Number(it.quantity_factor) || 0, unit: it.unit, waste_override: it.waste_override === "" ? null : Number(it.waste_override), is_labor: !!it.is_labor })) };
      if (editing) await api.put(`/estimating/assemblies/${editing}`, payload);
      else await api.post("/estimating/assemblies", payload);
      toast.success(editing ? "Assembly updated" : "Assembly created"); setOpen(false); load();
    } catch (e) { toast.error(apiError(e)); }
  };
  const toggle = async (a) => { try { await api.post(`/estimating/assemblies/${a.id}/active?active=${!a.active}`); load(); } catch (e) { toast.error(apiError(e)); } };

  return (
    <div>
      <PageHeader title="Assemblies" description="Reusable material/labor templates that expand into estimate lines." testid="page-assemblies" />
      <div className="p-6 sm:p-8">
        <div className="mb-4"><Button onClick={openNew} data-testid="add-assembly-button"><Plus className="h-4 w-4" /> New assembly</Button></div>
        <div className="rounded-md border border-border bg-white">
          <Table data-testid="assemblies-table">
            <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Category</TableHead><TableHead>Basis</TableHead><TableHead>Items</TableHead><TableHead>Version</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              {rows.map((a) => (
                <TableRow key={a.id} data-testid={`assembly-row-${a.id}`}>
                  <TableCell className="font-medium text-slate-800"><Layers className="mr-1 inline h-3.5 w-3.5 text-orange-500" />{a.name}</TableCell>
                  <TableCell className="text-slate-500">{a.category || "—"}</TableCell>
                  <TableCell>per {a.unit_basis}</TableCell>
                  <TableCell>{a.items.length}</TableCell>
                  <TableCell className="text-slate-500">v{a.version}</TableCell>
                  <TableCell>{a.active ? <Badge className="bg-green-50 text-green-700" variant="secondary">Active</Badge> : <Badge variant="secondary" className="bg-slate-100 text-slate-500">Inactive</Badge>}</TableCell>
                  <TableCell className="text-right"><Button size="sm" variant="outline" onClick={() => openEdit(a)} data-testid={`edit-assembly-${a.id}`}>Edit</Button> <Button size="sm" variant="ghost" onClick={() => toggle(a)} data-testid={`toggle-assembly-${a.id}`}>{a.active ? "Deactivate" : "Reactivate"}</Button></TableCell>
                </TableRow>
              ))}
              {!loading && rows.length === 0 && <TableRow><TableCell colSpan={7} className="py-8 text-center text-slate-400">No assemblies yet.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto" data-testid="assembly-form">
          <DialogHeader><DialogTitle>{editing ? "Edit assembly" : "New assembly"}</DialogTitle><DialogDescription>Quantities are per 1 unit of the assembly basis. Editing bumps the version; existing estimates keep their snapshot.</DialogDescription></DialogHeader>
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2 space-y-1"><Label className="text-xs">Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="assembly-name" /></div>
            <div className="space-y-1"><Label className="text-xs">Unit basis</Label>
              <Select value={form.unit_basis} onValueChange={(v) => setForm({ ...form, unit_basis: v })}><SelectTrigger data-testid="assembly-basis"><SelectValue /></SelectTrigger><SelectContent>{UNITS.map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-1"><Label className="text-xs">Category</Label><Input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="assembly-category" /></div>
            <div className="col-span-2 space-y-1"><Label className="text-xs">Notes</Label><Input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
          </div>
          <div className="mt-2">
            <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Items (per 1 {form.unit_basis})</div>
            <div className="space-y-2">
              {form.items.map((it, i) => (
                <div key={i} className="grid grid-cols-[1fr_120px_70px_60px_60px_28px] items-center gap-2" data-testid={`assembly-item-${i}`}>
                  <div>
                    <Select value={it.material_id || "none"} onValueChange={(v) => { const m = materials.find((x) => x.id === v); setItem(i, { material_id: v === "none" ? "" : v, description: m ? m.name : it.description, unit: m ? (m.unit || "EA").toUpperCase() : it.unit }); }}>
                      <SelectTrigger className="h-8" data-testid={`ai-material-${i}`}><SelectValue placeholder="Material (optional)" /></SelectTrigger>
                      <SelectContent className="max-h-64"><SelectItem value="none">— Custom / labor —</SelectItem>{materials.map((m) => <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>)}</SelectContent>
                    </Select>
                    <Input value={it.description} onChange={(e) => setItem(i, { description: e.target.value })} placeholder="Description" className="mt-1 h-7 text-xs" data-testid={`ai-desc-${i}`} />
                  </div>
                  <Input type="number" value={it.quantity_factor} onChange={(e) => setItem(i, { quantity_factor: e.target.value })} className="h-8" title="Qty per basis" data-testid={`ai-factor-${i}`} />
                  <Select value={it.unit} onValueChange={(v) => setItem(i, { unit: v })}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{[...new Set([it.unit, ...UNITS])].map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent></Select>
                  <Input type="number" value={it.waste_override} onChange={(e) => setItem(i, { waste_override: e.target.value })} placeholder="waste" className="h-8" title="Waste override %" data-testid={`ai-waste-${i}`} />
                  <div className="flex items-center gap-1"><Switch checked={it.is_labor} onCheckedChange={(v) => setItem(i, { is_labor: v })} data-testid={`ai-labor-${i}`} /><span className="text-[10px] text-slate-400">Labor</span></div>
                  <button onClick={() => setForm((f) => ({ ...f, items: f.items.filter((_, idx) => idx !== i) }))} className="text-slate-300 hover:text-red-500"><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
            </div>
            <Button variant="outline" size="sm" className="mt-2" onClick={() => setForm((f) => ({ ...f, items: [...f.items, emptyItem()] }))} data-testid="assembly-add-item"><Plus className="h-4 w-4" /> Add item</Button>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={save} disabled={!form.name} data-testid="assembly-save">{editing ? "Save" : "Create"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
