import { useEffect, useState, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { money } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { ArrowLeft, Plus, Trash2, Loader2, Search, Package, Layers, PenLine, Save, RefreshCw, FileCheck2, Star } from "lucide-react";

const MANAGE = ["owner", "administrator", "office"];
const UNITS = ["EA", "PC", "BDL", "SQ", "RL", "BX", "PL", "LF", "SF", "GAL", "PAIL"];

const r2 = (v) => Math.round((Number(v) || 0) * 100) / 100;
const calcQty = (measured, waste) => r2((Number(measured) || 0) * (1 + (Number(waste) || 0) / 100));
const unitCost = (l) => r2((Number(l.material_cost) || 0) + (Number(l.labor_cost) || 0) + (Number(l.equipment_cost) || 0) + (Number(l.subcontract_cost) || 0));

function blankLine(over = {}) {
  return { description: "", unit: "EA", measured_quantity: 1, waste_percent: 0, material_cost: 0, labor_cost: 0,
    equipment_cost: 0, subcontract_cost: 0, markup_percent: 0, selling_unit_price: 0, line_kind: "custom", ...over };
}

export default function EstimateEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const seeCost = MANAGE.includes(user?.role);

  const [est, setEst] = useState(null);
  const [lines, setLines] = useState([]);
  const [taxRate, setTaxRate] = useState(0);
  const [version, setVersion] = useState(1);
  const [busy, setBusy] = useState(false);
  const [prodOpen, setProdOpen] = useState(false);
  const [asmOpen, setAsmOpen] = useState(false);
  const [refreshData, setRefreshData] = useState(null);
  const [priceBooks, setPriceBooks] = useState([]);
  const [priceBookId, setPriceBookId] = useState("");
  const [reprice, setReprice] = useState(null); // { price_book_id, lines }

  useEffect(() => { api.get("/estimating/price-books", { params: { active: true } }).then((r) => setPriceBooks(r.data)).catch(() => {}); }, []);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/estimates/${id}`);
      setEst(data); setTaxRate(data.tax_rate || 0); setVersion(data.version);
      setPriceBookId(data.price_book_id || "");
      setLines((data.items || []).map((i) => ({
        description: i.description, unit: i.unit || "EA", measured_quantity: i.measured_quantity ?? i.quantity,
        waste_percent: i.waste_percent || 0, material_cost: i.material_cost || 0, labor_cost: i.labor_cost || 0,
        equipment_cost: i.equipment_cost || 0, subcontract_cost: i.subcontract_cost || 0,
        markup_percent: i.markup_percent || 0, selling_unit_price: i.selling_unit_price || i.unit_price || 0,
        line_kind: i.line_kind || "custom", material_id: i.material_id, supplier_material_id: i.supplier_material_id,
        conversion_factor: i.conversion_factor, purchase_unit: i.purchase_unit,
        cost_source_supplier_name: i.cost_source_supplier_name, cost_source: i.cost_source,
        assembly_id: i.assembly_id, assembly_version: i.assembly_version, assembly_name: i.assembly_name,
      })));
    } catch (e) { toast.error(apiError(e)); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const setLine = (i, patch) => setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  const removeLine = (i) => setLines((ls) => ls.filter((_, idx) => idx !== i));

  // when markup changes (cost roles) recompute sell; when sell changes recompute markup
  const onMarkup = (i, val) => { const l = lines[i]; const uc = unitCost(l); setLine(i, { markup_percent: val, selling_unit_price: r2(uc * (1 + (Number(val) || 0) / 100)) }); };
  const onSell = (i, val) => { const l = lines[i]; const uc = unitCost(l); const mk = uc ? r2(((Number(val) || 0) - uc) / uc * 100) : 0; setLine(i, { selling_unit_price: val, markup_percent: mk }); };

  const totals = useMemo(() => {
    let est_cost = 0, selling = 0;
    lines.forEach((l) => { const q = calcQty(l.measured_quantity, l.waste_percent); est_cost += q * unitCost(l); selling += q * (Number(l.selling_unit_price) || 0); });
    selling = r2(selling); est_cost = r2(est_cost);
    const gp = r2(selling - est_cost);
    const gm = selling ? r2(gp / selling * 100) : 0;
    const tax = r2(selling * (Number(taxRate) || 0) / 100);
    return { est_cost, selling, gp, gm, tax, total: r2(selling + tax) };
  }, [lines, taxRate]);

  const save = async () => {
    setBusy(true);
    try {
      const payload = { lead_id: est.lead_id, customer_id: est.customer_id, property_id: est.property_id,
        inspection_id: est.inspection_id, tax_rate: Number(taxRate) || 0, price_book_id: priceBookId || null,
        items: lines.map((l) => ({ ...l, measured_quantity: Number(l.measured_quantity) || 0, waste_percent: Number(l.waste_percent) || 0,
          material_cost: Number(l.material_cost) || 0, labor_cost: Number(l.labor_cost) || 0,
          equipment_cost: Number(l.equipment_cost) || 0, subcontract_cost: Number(l.subcontract_cost) || 0,
          markup_percent: Number(l.markup_percent) || 0, selling_unit_price: Number(l.selling_unit_price) || 0 })) };
      const { data } = await api.put(`/estimates/${id}`, payload, { headers: { "If-Match": String(version) } });
      setEst(data); setVersion(data.version); toast.success("Estimate saved");
      load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const generateQuote = async () => {
    try { const { data } = await api.post("/quotes", { estimate_id: id }); toast.success(`Quote ${data.number} created`); navigate(est.lead_id ? `/leads/${est.lead_id}` : "/"); }
    catch (e) { toast.error(apiError(e)); }
  };

  const addProduct = (m, sm) => {
    const cost = sm ? (sm.current_cost || 0) : (m.primary_supplier_cost || m.best_known_cost || 0);
    setLines((ls) => [...ls, blankLine({ description: m.name, unit: (m.unit || "EA").toUpperCase(), line_kind: "material",
      material_id: m.id, supplier_material_id: sm?.id, material_cost: cost, selling_unit_price: cost,
      cost_source_supplier_name: sm ? sm.supplier_name : m.primary_supplier_name, cost_source: sm?.price_status })]);
    setProdOpen(false); toast.success(`Added ${m.name}`);
  };

  const addAssemblyLines = (expandLines) => {
    setLines((ls) => [...ls, ...expandLines.map((l) => blankLine({ ...l, unit: (l.unit || "EA").toUpperCase() }))]);
    setAsmOpen(false);
  };

  const openRefresh = async () => {
    try { const { data } = await api.get(`/estimates/${id}/cost-refresh/preview`); setRefreshData({ ...data, recalc: false }); }
    catch (e) { toast.error(apiError(e)); }
  };
  const applyRefresh = async () => {
    try {
      const ids = refreshData.rows.filter((r) => r.changed).map((r) => r.line_id);
      const { data } = await api.post(`/estimates/${id}/cost-refresh/apply`, { line_ids: ids, recalc_selling_price: !!refreshData.recalc });
      setEst(data); setVersion(data.version); setRefreshData(null); toast.success("Costs refreshed"); load();
    } catch (e) { toast.error(apiError(e)); }
  };

  const onPriceBookChange = async (pbId) => {
    if (pbId === priceBookId) return;
    try {
      const { data } = await api.post(`/estimates/${id}/price-book/preview`, { price_book_id: pbId });
      if (data.affected > 0) {
        setReprice({ price_book_id: pbId, lines: data.lines });
      } else {
        setPriceBookId(pbId);
        toast.info("Price Book set. No existing lines matched a rule — nothing repriced.");
      }
    } catch (e) { toast.error(apiError(e)); }
  };
  const applyReprice = async () => {
    try {
      const { data } = await api.post(`/estimates/${id}/price-book/apply`, { price_book_id: reprice.price_book_id });
      setEst(data); setVersion(data.version); setPriceBookId(data.price_book_id || ""); setReprice(null);
      toast.success("Price Book applied"); load();
    } catch (e) { toast.error(apiError(e)); }
  };

  if (!est) return <div className="p-8"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;
  const editable = est.status === "draft" || est.status === "sent";

  return (
    <div>
      <PageHeader title={`Estimate ${est.number}`} description="Catalog-backed pricing — cost, waste, markup and selling price." testid="page-estimate-editor" />
      <div className="p-6 sm:p-8">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={() => navigate(est.lead_id ? `/leads/${est.lead_id}` : "/")} data-testid="estimate-back"><ArrowLeft className="h-4 w-4" /> Back</Button>
          <div className="flex flex-wrap items-center gap-2">
            {seeCost && priceBooks.length > 0 && (
              <div className="flex items-center gap-1.5">
                <Label className="text-xs text-slate-500">Price Book</Label>
                <Select value={priceBookId || "none"} onValueChange={(v) => onPriceBookChange(v === "none" ? "" : v)}>
                  <SelectTrigger className="h-9 w-44" data-testid="estimate-price-book"><SelectValue placeholder="None" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none" data-testid="price-book-none">None (manual)</SelectItem>
                    {priceBooks.map((pb) => <SelectItem key={pb.id} value={pb.id} data-testid={`price-book-${pb.id}`}>{pb.name}{pb.is_default ? " ★" : ""}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            )}
            {seeCost && <Button variant="outline" size="sm" onClick={openRefresh} data-testid="estimate-cost-refresh"><RefreshCw className="h-4 w-4" /> Refresh Current Costs</Button>}
            <Button variant="outline" size="sm" onClick={generateQuote} data-testid="estimate-generate-quote"><FileCheck2 className="h-4 w-4" /> Generate Quote</Button>
            <Button size="sm" onClick={save} disabled={busy || !editable} data-testid="estimate-save">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save</Button>
          </div>
        </div>

        {seeCost && est.margin_warnings?.enabled && est.margin_warnings.overall_below && (
          <div className="mb-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800" data-testid="estimate-margin-warning">
            <span className="font-medium">Margin below target.</span>
            <span>Actual: {Number(est.margin_warnings.overall_margin_percent).toFixed(1)}% · Target: {Number(est.margin_warnings.target_minimum_margin).toFixed(1)}%
            {est.margin_warnings.below_lines?.length ? ` · ${est.margin_warnings.below_lines.length} line(s) below target.` : ""}</span>
          </div>
        )}

        <div className="mb-3">
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="outline" size="sm" data-testid="estimate-add-item"><Plus className="h-4 w-4" /> Add Item</Button></DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onClick={() => setProdOpen(true)} data-testid="add-from-catalog"><Search className="mr-2 h-4 w-4" /> Search Product Catalog</DropdownMenuItem>
              <DropdownMenuItem onClick={() => setAsmOpen(true)} data-testid="add-assembly"><Layers className="mr-2 h-4 w-4" /> Add Assembly</DropdownMenuItem>
              <DropdownMenuItem onClick={() => setLines((ls) => [...ls, blankLine()])} data-testid="add-custom-line"><PenLine className="mr-2 h-4 w-4" /> Add Custom Line</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="overflow-x-auto rounded-md border border-border bg-white">
          <Table data-testid="estimate-lines-table">
            <TableHeader>
              <TableRow>
                <TableHead>Description</TableHead><TableHead className="w-20">Measured</TableHead><TableHead className="w-16">UOM</TableHead>
                <TableHead className="w-16">Waste %</TableHead><TableHead className="w-20 text-right">Qty</TableHead>
                {seeCost && <TableHead className="w-24 text-right">Unit Cost</TableHead>}
                {seeCost && <TableHead className="w-20 text-right">Markup %</TableHead>}
                <TableHead className="w-24 text-right">Sell Price</TableHead>
                <TableHead className="w-24 text-right">Line Total</TableHead><TableHead className="w-8" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.map((l, i) => {
                const q = calcQty(l.measured_quantity, l.waste_percent);
                const uc = unitCost(l);
                return (
                  <TableRow key={i} data-testid={`estimate-line-${i}`}>
                    <TableCell>
                      <Input value={l.description} onChange={(e) => setLine(i, { description: e.target.value })} className="h-8" data-testid={`el-desc-${i}`} />
                      {(l.cost_source_supplier_name || l.assembly_name) && <div className="mt-0.5 text-[11px] text-slate-400">{l.assembly_name ? `${l.assembly_name} · ` : ""}{l.cost_source_supplier_name || ""}{l.cost_source ? ` (${l.cost_source})` : ""}</div>}
                    </TableCell>
                    <TableCell><Input type="number" value={l.measured_quantity} onChange={(e) => setLine(i, { measured_quantity: e.target.value })} className="h-8" data-testid={`el-measured-${i}`} /></TableCell>
                    <TableCell>
                      <Select value={l.unit} onValueChange={(v) => setLine(i, { unit: v })}><SelectTrigger className="h-8" data-testid={`el-unit-${i}`}><SelectValue /></SelectTrigger>
                        <SelectContent>{[...new Set([l.unit, ...UNITS])].map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent></Select>
                    </TableCell>
                    <TableCell><Input type="number" value={l.waste_percent} onChange={(e) => setLine(i, { waste_percent: e.target.value })} className="h-8" data-testid={`el-waste-${i}`} /></TableCell>
                    <TableCell className="text-right tabular-nums" data-testid={`el-qty-${i}`}>{q}</TableCell>
                    {seeCost && <TableCell><Input type="number" value={l.material_cost} onChange={(e) => setLine(i, { material_cost: e.target.value })} className="h-8 text-right" data-testid={`el-cost-${i}`} title="Material cost/unit" /></TableCell>}
                    {seeCost && <TableCell><Input type="number" value={l.markup_percent} onChange={(e) => onMarkup(i, e.target.value)} className="h-8 text-right" data-testid={`el-markup-${i}`} /></TableCell>}
                    <TableCell><Input type="number" value={l.selling_unit_price} onChange={(e) => onSell(i, e.target.value)} className="h-8 text-right" data-testid={`el-sell-${i}`} /></TableCell>
                    <TableCell className="text-right tabular-nums font-medium" data-testid={`el-total-${i}`}>{money(q * (Number(l.selling_unit_price) || 0))}</TableCell>
                    <TableCell><button onClick={() => removeLine(i)} className="text-slate-300 hover:text-red-500" data-testid={`el-remove-${i}`}><Trash2 className="h-4 w-4" /></button></TableCell>
                  </TableRow>
                );
              })}
              {lines.length === 0 && <TableRow><TableCell colSpan={seeCost ? 10 : 8} className="py-8 text-center text-sm text-slate-400">No line items. Use "Add Item" to begin.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>

        <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:justify-end">
          <div className="w-full max-w-sm rounded-md border border-border bg-white p-4 text-sm" data-testid="estimate-summary">
            {seeCost && <>
              <Row label="Estimated Cost" value={money(totals.est_cost)} testid="summary-cost" />
              <Row label="Gross Profit" value={money(totals.gp)} testid="summary-gp" />
              <Row label="Gross Margin" value={`${totals.gm}%`} testid="summary-gm" />
              <div className="my-2 border-t border-border" />
            </>}
            <Row label="Selling Price" value={money(totals.selling)} testid="summary-selling" bold />
            <div className="flex items-center justify-between py-1">
              <span className="flex items-center gap-2 text-slate-500">Tax rate %<Input type="number" value={taxRate} onChange={(e) => setTaxRate(e.target.value)} className="h-7 w-20" data-testid="estimate-taxrate" /></span>
              <span className="tabular-nums">{money(totals.tax)}</span>
            </div>
            <Row label="Total" value={money(totals.total)} testid="summary-total" bold />
          </div>
        </div>
      </div>

      <ProductPicker open={prodOpen} onOpenChange={setProdOpen} seeCost={seeCost} onPick={addProduct} />
      <AssemblyPicker open={asmOpen} onOpenChange={setAsmOpen} onAdd={addAssemblyLines} />
      <RefreshDialog data={refreshData} setData={setRefreshData} onApply={applyRefresh} />

      <Dialog open={!!reprice} onOpenChange={(o) => !o && setReprice(null)}>
        <DialogContent data-testid="reprice-dialog">
          <DialogHeader>
            <DialogTitle>Apply Price Book?</DialogTitle>
            <DialogDescription>Changing the Price Book may affect {reprice?.lines?.length || 0} line(s). Review the new selling prices before applying. Manual lines without a matching rule are unchanged.</DialogDescription>
          </DialogHeader>
          <div className="max-h-72 overflow-y-auto">
            <Table>
              <TableHeader><TableRow><TableHead>Item</TableHead><TableHead className="text-right">Current</TableHead><TableHead className="text-right">New</TableHead><TableHead className="text-right">Diff</TableHead></TableRow></TableHeader>
              <TableBody>
                {reprice?.lines?.map((r) => (
                  <TableRow key={r.line_id} data-testid={`reprice-row-${r.line_id}`}>
                    <TableCell className="max-w-[220px] truncate">{r.description}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(r.current_sell)}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(r.new_sell)}</TableCell>
                    <TableCell className={`text-right tabular-nums ${r.difference >= 0 ? "text-green-700" : "text-red-600"}`}>{r.difference > 0 ? "+" : ""}{money(r.difference)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReprice(null)}>Cancel</Button>
            <Button onClick={applyReprice} data-testid="reprice-apply">Apply changes</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Row({ label, value, testid, bold }) {
  return <div className={`flex items-center justify-between py-1 ${bold ? "font-semibold text-slate-900" : "text-slate-600"}`}><span>{label}</span><span className="tabular-nums" data-testid={testid}>{value}</span></div>;
}

function ProductPicker({ open, onOpenChange, seeCost, onPick }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const search = useCallback(async () => {
    setLoading(true);
    try { const { data } = await api.get("/materials", { params: { active: true, q: q || undefined } }); setRows(data); }
    catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, [q]);
  useEffect(() => { if (open) search(); }, [open]); // eslint-disable-line
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto" data-testid="product-picker">
        <DialogHeader><DialogTitle>Search Product Catalog</DialogTitle><DialogDescription>Add a material — its current cost is snapshotted onto the estimate.</DialogDescription></DialogHeader>
        <div className="flex gap-2"><Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} placeholder="Search name / SKU / manufacturer" data-testid="picker-search" /><Button onClick={search} disabled={loading} data-testid="picker-search-btn">{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}</Button></div>
        <div className="rounded-md border border-border">
          <Table><TableHeader><TableRow><TableHead>Material</TableHead><TableHead>Preferred</TableHead>{seeCost && <TableHead>Best Cost</TableHead>}<TableHead /></TableRow></TableHeader>
            <TableBody>{rows.map((m) => (
              <TableRow key={m.id} data-testid={`picker-row-${m.id}`}>
                <TableCell><div className="font-medium text-slate-800">{m.name}</div><div className="text-xs text-slate-400">{m.manufacturer || m.category || ""}</div></TableCell>
                <TableCell className="text-sm">{m.primary_supplier_name ? <span className="flex items-center gap-1"><Star className="h-3 w-3 fill-indigo-500 text-indigo-500" />{m.primary_supplier_name}{seeCost && m.primary_supplier_cost != null ? ` · ${money(m.primary_supplier_cost)}` : ""}</span> : "—"}</TableCell>
                {seeCost && <TableCell className="text-sm">{m.best_known_cost != null ? `${money(m.best_known_cost)}${m.best_supplier_name ? ` (${m.best_supplier_name})` : ""}` : "—"}</TableCell>}
                <TableCell className="text-right"><Button size="sm" variant="outline" onClick={() => onPick(m, null)} data-testid={`picker-add-${m.id}`}><Plus className="h-4 w-4" /> Add</Button></TableCell>
              </TableRow>
            ))}{!loading && rows.length === 0 && <TableRow><TableCell colSpan={seeCost ? 4 : 3} className="py-6 text-center text-slate-400">No materials.</TableCell></TableRow>}</TableBody>
          </Table>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function AssemblyPicker({ open, onOpenChange, onAdd }) {
  const [rows, setRows] = useState([]);
  const [sel, setSel] = useState("");
  const [qty, setQty] = useState(1);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) api.get("/estimating/assemblies", { params: { active: true } }).then((r) => setRows(r.data)).catch(() => {}); }, [open]);
  const chosen = rows.find((a) => a.id === sel);
  const expand = async () => {
    setBusy(true);
    try { const { data } = await api.post(`/estimating/assemblies/${sel}/expand?quantity=${Number(qty) || 0}`); onAdd(data.lines); toast.success(`Added ${data.assembly_name} (${data.lines.length} lines)`); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="assembly-picker">
        <DialogHeader><DialogTitle>Add Assembly</DialogTitle><DialogDescription>Expands into estimate lines (a snapshot of the assembly's current version).</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <div><Label className="text-xs">Assembly</Label>
            <Select value={sel} onValueChange={setSel}><SelectTrigger data-testid="assembly-select"><SelectValue placeholder="Choose assembly" /></SelectTrigger>
              <SelectContent>{rows.map((a) => <SelectItem key={a.id} value={a.id}>{a.name} (per {a.unit_basis})</SelectItem>)}</SelectContent></Select></div>
          <div><Label className="text-xs">Quantity {chosen ? `(${chosen.unit_basis})` : ""}</Label><Input type="number" value={qty} onChange={(e) => setQty(e.target.value)} data-testid="assembly-qty" /></div>
        </div>
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={expand} disabled={!sel || busy} data-testid="assembly-expand">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Add lines"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RefreshDialog({ data, setData, onApply }) {
  if (!data) return null;
  return (
    <Dialog open={!!data} onOpenChange={(o) => !o && setData(null)}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto" data-testid="cost-refresh-dialog">
        <DialogHeader><DialogTitle>Refresh Current Costs</DialogTitle><DialogDescription>Review supplier cost changes. Nothing is applied until you confirm.</DialogDescription></DialogHeader>
        <div className="rounded-md border border-border">
          <Table><TableHeader><TableRow><TableHead>Item</TableHead><TableHead>Supplier</TableHead><TableHead className="text-right">Old</TableHead><TableHead className="text-right">Current</TableHead><TableHead className="text-right">Change</TableHead></TableRow></TableHeader>
            <TableBody>{data.rows.map((r) => (
              <TableRow key={r.line_id} className={r.changed ? "bg-amber-50/40" : ""} data-testid={`refresh-row-${r.line_id}`}>
                <TableCell>{r.description}</TableCell><TableCell className="text-sm text-slate-500">{r.supplier_name || "—"}</TableCell>
                <TableCell className="text-right tabular-nums">{money(r.old_cost || 0)}</TableCell>
                <TableCell className="text-right tabular-nums">{money(r.current_cost || 0)}</TableCell>
                <TableCell className={`text-right tabular-nums ${r.delta > 0 ? "text-red-600" : r.delta < 0 ? "text-green-600" : "text-slate-400"}`}>{r.delta > 0 ? "+" : ""}{money(r.delta || 0)}</TableCell>
              </TableRow>
            ))}{data.rows.length === 0 && <TableRow><TableCell colSpan={5} className="py-6 text-center text-slate-400">No catalog-linked lines to refresh.</TableCell></TableRow>}</TableBody>
          </Table>
        </div>
        <div className="flex items-center gap-2"><Checkbox id="recalc" checked={data.recalc} onCheckedChange={(v) => setData({ ...data, recalc: !!v })} data-testid="refresh-recalc" /><Label htmlFor="recalc" className="text-sm">Also recalculate selling price from markup</Label></div>
        <DialogFooter><Button variant="outline" onClick={() => setData(null)}>Cancel</Button><Button onClick={onApply} disabled={data.changed_count === 0} data-testid="refresh-apply">Apply {data.changed_count} change{data.changed_count === 1 ? "" : "s"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
