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
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Plus, Trash2, BookOpen, Star } from "lucide-react";

const emptyEntry = () => ({ target_type: "material", material_id: "", label: "", rule_type: "markup", fixed_price: "", markup_percent: "", margin_percent: "", active: true });

export default function PriceBooks() {
  const [rows, setRows] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", active: true, is_default: false });
  const [entriesOpen, setEntriesOpen] = useState(null); // price book object
  const [entries, setEntries] = useState([]);

  const load = useCallback(async () => {
    try { const { data } = await api.get("/estimating/price-books"); setRows(data); }
    catch (e) { toast.error(apiError(e)); }
  }, []);
  useEffect(() => { load(); api.get("/materials", { params: { active: true } }).then((r) => setMaterials(r.data)).catch(() => {}); }, [load]);

  const create = async () => {
    try { await api.post("/estimating/price-books", form); toast.success("Price book created"); setOpen(false); setForm({ name: "", description: "", active: true, is_default: false }); load(); }
    catch (e) { toast.error(apiError(e)); }
  };
  const makeDefault = async (pb) => { try { await api.patch(`/estimating/price-books/${pb.id}`, { is_default: true }); toast.success(`${pb.name} is now default`); load(); } catch (e) { toast.error(apiError(e)); } };
  const toggleActive = async (pb) => { try { await api.patch(`/estimating/price-books/${pb.id}`, { active: !pb.active }); load(); } catch (e) { toast.error(apiError(e)); } };

  const openEntries = (pb) => { setEntriesOpen(pb); setEntries((pb.entries || []).map((e) => ({ target_type: e.target_type, material_id: e.material_id || "", label: e.label || "", rule_type: e.rule_type, fixed_price: e.fixed_price ?? "", markup_percent: e.markup_percent ?? "", margin_percent: e.margin_percent ?? "", active: e.active }))); };
  const setEntry = (i, patch) => setEntries((es) => es.map((e, idx) => (idx === i ? { ...e, ...patch } : e)));
  const saveEntries = async () => {
    try {
      const payload = entries.map((e) => ({ target_type: e.target_type, material_id: e.material_id || null, label: e.label || null, rule_type: e.rule_type,
        fixed_price: e.fixed_price === "" ? null : Number(e.fixed_price), markup_percent: e.markup_percent === "" ? null : Number(e.markup_percent),
        margin_percent: e.margin_percent === "" ? null : Number(e.margin_percent), active: !!e.active }));
      await api.put(`/estimating/price-books/${entriesOpen.id}/entries`, payload);
      toast.success("Entries saved"); setEntriesOpen(null); load();
    } catch (e) { toast.error(apiError(e)); }
  };

  return (
    <div>
      <PageHeader title="Price Books" description="Selling-price rules (fixed / markup / margin) per material, labor, or assembly." testid="page-price-books" />
      <div className="p-6 sm:p-8">
        <div className="mb-4"><Button onClick={() => setOpen(true)} data-testid="add-pricebook-button"><Plus className="h-4 w-4" /> New price book</Button></div>
        <div className="rounded-md border border-border bg-white">
          <Table data-testid="pricebooks-table">
            <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Entries</TableHead><TableHead>Default</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              {rows.map((pb) => (
                <TableRow key={pb.id} data-testid={`pricebook-row-${pb.id}`}>
                  <TableCell className="font-medium text-slate-800"><BookOpen className="mr-1 inline h-3.5 w-3.5 text-orange-500" />{pb.name}{pb.description ? <span className="ml-2 text-xs text-slate-400">{pb.description}</span> : ""}</TableCell>
                  <TableCell>{pb.entries?.length || 0}</TableCell>
                  <TableCell>{pb.is_default ? <Badge className="bg-indigo-50 text-indigo-700" variant="secondary"><Star className="mr-1 h-3 w-3 fill-indigo-500 text-indigo-500" />Default</Badge> : <Button size="sm" variant="ghost" onClick={() => makeDefault(pb)} data-testid={`make-default-${pb.id}`}>Make default</Button>}</TableCell>
                  <TableCell>{pb.active ? <Badge className="bg-green-50 text-green-700" variant="secondary">Active</Badge> : <Badge variant="secondary" className="bg-slate-100 text-slate-500">Inactive</Badge>}</TableCell>
                  <TableCell className="text-right"><Button size="sm" variant="outline" onClick={() => openEntries(pb)} data-testid={`edit-entries-${pb.id}`}>Entries</Button> <Button size="sm" variant="ghost" onClick={() => toggleActive(pb)} data-testid={`toggle-pricebook-${pb.id}`}>{pb.active ? "Deactivate" : "Reactivate"}</Button></TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && <TableRow><TableCell colSpan={5} className="py-8 text-center text-slate-400">No price books.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg" data-testid="pricebook-form">
          <DialogHeader><DialogTitle>New price book</DialogTitle><DialogDescription>At most one active default price book.</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1"><Label className="text-xs">Name</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="pricebook-name" /></div>
            <div className="space-y-1"><Label className="text-xs">Description</Label><Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
            <div className="flex items-center gap-2"><Switch checked={form.is_default} onCheckedChange={(v) => setForm({ ...form, is_default: v })} data-testid="pricebook-default" /><Label className="text-sm">Set as default</Label></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={create} disabled={!form.name} data-testid="pricebook-save">Create</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!entriesOpen} onOpenChange={(o) => !o && setEntriesOpen(null)}>
        <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto" data-testid="pricebook-entries">
          <DialogHeader><DialogTitle>{entriesOpen?.name} — entries</DialogTitle><DialogDescription>Fixed price, markup %, or margin % per target.</DialogDescription></DialogHeader>
          <div className="space-y-2">
            {entries.map((e, i) => (
              <div key={i} className="grid grid-cols-[110px_1fr_110px_100px_28px] items-center gap-2" data-testid={`pb-entry-${i}`}>
                <Select value={e.target_type} onValueChange={(v) => setEntry(i, { target_type: v })}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="material">Material</SelectItem><SelectItem value="labor">Labor</SelectItem><SelectItem value="assembly">Assembly</SelectItem></SelectContent></Select>
                {e.target_type === "material"
                  ? <Select value={e.material_id || "none"} onValueChange={(v) => setEntry(i, { material_id: v === "none" ? "" : v })}><SelectTrigger className="h-8" data-testid={`pb-material-${i}`}><SelectValue placeholder="Material" /></SelectTrigger><SelectContent className="max-h-64"><SelectItem value="none">—</SelectItem>{materials.map((m) => <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>)}</SelectContent></Select>
                  : <Input value={e.label} onChange={(ev) => setEntry(i, { label: ev.target.value })} placeholder="Label" className="h-8" data-testid={`pb-label-${i}`} />}
                <Select value={e.rule_type} onValueChange={(v) => setEntry(i, { rule_type: v })}><SelectTrigger className="h-8" data-testid={`pb-rule-${i}`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="fixed">Fixed</SelectItem><SelectItem value="markup">Markup %</SelectItem><SelectItem value="margin">Margin %</SelectItem></SelectContent></Select>
                <Input type="number" className="h-8" data-testid={`pb-value-${i}`}
                  value={e.rule_type === "fixed" ? e.fixed_price : e.rule_type === "markup" ? e.markup_percent : e.margin_percent}
                  onChange={(ev) => setEntry(i, e.rule_type === "fixed" ? { fixed_price: ev.target.value } : e.rule_type === "markup" ? { markup_percent: ev.target.value } : { margin_percent: ev.target.value })}
                  placeholder={e.rule_type === "fixed" ? "$" : "%"} />
                <button onClick={() => setEntries((es) => es.filter((_, idx) => idx !== i))} className="text-slate-300 hover:text-red-500"><Trash2 className="h-4 w-4" /></button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={() => setEntries((es) => [...es, emptyEntry()])} data-testid="pb-add-entry"><Plus className="h-4 w-4" /> Add entry</Button>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setEntriesOpen(null)}>Cancel</Button><Button onClick={saveEntries} data-testid="pb-save-entries">Save entries</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
