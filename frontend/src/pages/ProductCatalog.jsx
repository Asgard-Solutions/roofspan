import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAuth } from "@/context/AuthContext";
import PODialog from "@/components/PODialog";
import { Search, RefreshCw, Loader2, Plus, CheckCircle2, PackageSearch, ArrowLeft, AlertTriangle, ExternalLink, Star, ShoppingCart, Eye } from "lucide-react";

const PAGE_SIZE = 25;
const ABC_PROVIDER = "abc_supply";
const MANAGE = ["owner", "administrator", "office"];

function fmtTime(s) {
  if (!s) return null;
  try { return new Date(s).toLocaleDateString(); } catch { return null; }
}

// Normalized price-freshness label. Never invents a stale threshold — only reflects backend status.
function PriceBadge({ status, provider, updatedAt, testid }) {
  const t = fmtTime(updatedAt);
  const s = (status || "").toLowerCase();
  let label = "—", cls = "bg-slate-100 text-slate-400";
  if (s === "priced" || s === "live") { label = "Live"; cls = "bg-green-50 text-green-700"; }
  else if (s === "cached") { label = "Cached"; cls = "bg-blue-50 text-blue-700"; }
  else if (s === "stale") { label = "Stale"; cls = "bg-amber-50 text-amber-700"; }
  else if (s === "manual") { label = "Manual"; cls = "bg-slate-100 text-slate-600"; }
  else if (s === "unavailable") { label = "Unavailable"; cls = "bg-amber-50 text-amber-700"; }
  else if (provider === ABC_PROVIDER) { label = "Cached"; cls = "bg-blue-50 text-blue-700"; }
  else if (provider) { label = "Manual"; cls = "bg-slate-100 text-slate-600"; }
  if (label === "—") return <span className="text-xs text-slate-300">—</span>;
  return <Badge variant="secondary" className={cls} data-testid={testid} title={t ? `Updated ${t}` : ""}>{label}{t ? ` · ${t}` : ""}</Badge>;
}

/* ------------------------------ ABC live catalog source ------------------------------ */
function AbcCatalogSource({ supplierName }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [ctx, setCtx] = useState(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(null);
  const [source, setSource] = useState("cache");
  const [loading, setLoading] = useState(false);
  const [prices, setPrices] = useState({});
  const [adding, setAdding] = useState({});
  const [sync, setSync] = useState(null);
  const [syncing, setSyncing] = useState(false);

  const loadSync = useCallback(async () => {
    try { const { data } = await api.get("/integrations/abc/catalog/sync/status"); setSync(data); } catch { /* ignore */ }
  }, []);

  const priceVisible = useCallback(async (rows, context) => {
    if (!context?.connected || !context?.ship_to_number || !context?.branch_number) return;
    const priceable = rows.filter((r) => r.available_at_branch && !r.is_dimensional).slice(0, 50);
    if (!priceable.length) return;
    try {
      const { data } = await api.post("/integrations/abc/pricing", {
        ship_to_number: context.ship_to_number, branch_number: context.branch_number, purpose: "ordering",
        lines: priceable.map((r) => ({ id: r.item_number, item_number: r.item_number, quantity: 1, uom: r.unit_of_measure || undefined })),
      });
      const map = {};
      (data.lines || []).forEach((l) => { map[l.item_number] = l; });
      setPrices((prev) => ({ ...prev, ...map }));
    } catch { /* best-effort */ }
  }, []);

  const load = useCallback(async (opts = {}) => {
    const p = opts.page ?? page;
    setLoading(true);
    try {
      const { data } = await api.get("/integrations/abc/catalog", { params: { q: q || undefined, page: p, page_size: PAGE_SIZE, active_only: true } });
      setItems(data.items || []); setCtx(data.context); setTotal(data.total);
      setTotalPages(data.total_pages || 1); setSource(data.source); setPage(data.page || p);
      priceVisible(data.items || [], data.context);
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, [q, page, priceVisible]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load({ page: 1 }); loadSync(); }, []);

  const doSearch = () => { setPrices({}); load({ page: 1 }); };
  const goPage = (p) => { if (p < 1 || p > totalPages) return; load({ page: p }); };

  const runSync = async () => {
    setSyncing(true);
    try {
      await api.post("/integrations/abc/catalog/sync");
      toast.success("Catalog sync started");
      for (let i = 0; i < 8; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const { data } = await api.get("/integrations/abc/catalog/sync/status");
        setSync(data);
        if (data.status === "completed" || data.status === "failed") break;
      }
      load({ page: 1 });
    } catch (e) { toast.error(apiError(e)); } finally { setSyncing(false); }
  };

  const addToInventory = async (item) => {
    setAdding((a) => ({ ...a, [item.item_number]: true }));
    try {
      const { data } = await api.post(`/integrations/abc/catalog/${encodeURIComponent(item.item_number)}/add-to-inventory`, {});
      if (data.already_linked) toast.info(`${item.item_number} is already in Inventory`);
      else toast.success(`Added ${data.material_name} to Inventory`);
      setItems((prev) => prev.map((r) => r.item_number === item.item_number ? { ...r, in_inventory: true, material_id: data.material_id } : r));
    } catch (e) { toast.error(apiError(e)); } finally { setAdding((a) => ({ ...a, [item.item_number]: false })); }
  };

  const priceCell = (item) => {
    const p = prices[item.item_number];
    if (item.is_dimensional) return <span className="text-xs text-slate-400">By length</span>;
    if (!p) return <span className="text-xs text-slate-300">—</span>;
    if (p.price_status === "priced" && p.unit_price != null) return <span className="font-medium">{money(p.unit_price)}</span>;
    return <span className="text-xs text-amber-600" title={p.status_message || ""}>Call for pricing</span>;
  };

  const availabilityBadge = (item) => {
    if (item.available_at_branch === true) return <Badge className="bg-green-50 text-green-700" variant="secondary" data-testid={`avail-${item.item_number}`}>Available</Badge>;
    if (item.available_at_branch === false) return <Badge className="bg-slate-100 text-slate-500" variant="secondary" data-testid={`avail-${item.item_number}`}>Not at branch</Badge>;
    return <Badge className="bg-slate-100 text-slate-400" variant="secondary" data-testid={`avail-${item.item_number}`}>Unknown</Badge>;
  };

  return (
    <div data-testid="catalog-abc-source">
      {ctx && !ctx.connected && (
        <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900" data-testid="catalog-disconnected">
          <div className="flex items-center gap-1.5 font-medium"><AlertTriangle className="h-4 w-4" /> {supplierName} is not connected</div>
          <p className="mt-1">Connect your {supplierName} account to browse the live catalog and pricing.</p>
          <Button className="mt-2" size="sm" variant="outline" onClick={() => navigate("/admin/settings/abc")} data-testid="catalog-go-settings">Go to Settings → ABC Supply <ExternalLink className="h-3.5 w-3.5" /></Button>
        </div>
      )}
      {ctx && ctx.connected && (ctx.needs_ship_to || ctx.needs_branch) && (
        <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900" data-testid="catalog-needs-selection">
          <div className="flex items-center gap-1.5 font-medium"><AlertTriangle className="h-4 w-4" /> Select a {ctx.needs_ship_to ? "Ship-To" : ""}{ctx.needs_ship_to && ctx.needs_branch ? " and " : ""}{ctx.needs_branch ? "Branch" : ""}</div>
          <p className="mt-1">Availability and pricing need a default Ship-To and ABC branch.</p>
          <Button className="mt-2" size="sm" variant="outline" onClick={() => navigate("/admin/settings/abc")} data-testid="catalog-go-settings-2">Go to Settings → ABC Supply <ExternalLink className="h-3.5 w-3.5" /></Button>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-slate-50 p-3 text-sm" data-testid="catalog-context">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="font-medium text-slate-700">{supplierName}</span>
          <span className="text-slate-500">Ship-To: <span className="font-medium text-slate-700" data-testid="catalog-ship-to">{ctx?.ship_to_name || ctx?.ship_to_number || "—"}</span></span>
          <span className="text-slate-500">Branch: <span className="font-medium text-slate-700" data-testid="catalog-branch">{ctx?.branch_number || "—"}</span></span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500" data-testid="catalog-sync-status">
            {sync?.status === "syncing" || syncing ? "Syncing…" : sync?.status === "failed" ? <span className="text-red-500">Sync failed</span> : sync?.last_synced_at ? `Last synced: ${new Date(sync.last_synced_at).toLocaleString()} (${sync.total_items} items)` : "Never synced"}
          </span>
          <Button size="sm" variant="outline" onClick={runSync} disabled={syncing || !ctx?.connected} data-testid="catalog-sync-button">
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Sync catalog
          </Button>
        </div>
      </div>

      <div className="mb-4 flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && doSearch()} placeholder="Search description or item number" className="pl-8" data-testid="catalog-search-input" />
        </div>
        <Button onClick={doSearch} disabled={loading} data-testid="catalog-search-button">{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} Search</Button>
        {source === "live" && <Badge variant="secondary" className="bg-blue-50 text-blue-700">Live</Badge>}
      </div>

      <div className="rounded-md border border-border bg-white">
        <Table data-testid="catalog-table">
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead><TableHead>Item #</TableHead><TableHead>Manufacturer</TableHead>
              <TableHead>UoM</TableHead><TableHead>Category</TableHead><TableHead>Availability</TableHead>
              <TableHead>Cost</TableHead><TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.item_number} data-testid={`catalog-row-${item.item_number}`}>
                <TableCell className="max-w-[280px]">
                  <div className="font-medium text-slate-800">{item.description || item.item_number}</div>
                  {item.brand && <div className="text-xs text-slate-400">{item.brand}</div>}
                </TableCell>
                <TableCell className="font-mono text-xs">{item.item_number}</TableCell>
                <TableCell className="text-sm">{item.manufacturer || "—"}</TableCell>
                <TableCell className="text-sm">{item.unit_of_measure || "—"}</TableCell>
                <TableCell className="text-sm">{item.category || "—"}</TableCell>
                <TableCell>{availabilityBadge(item)}</TableCell>
                <TableCell data-testid={`catalog-cost-${item.item_number}`}>{priceCell(item)}</TableCell>
                <TableCell className="text-right">
                  {item.in_inventory ? (
                    <div className="flex items-center justify-end gap-1">
                      <Badge className="bg-green-50 text-green-700" variant="secondary" data-testid={`in-inventory-${item.item_number}`}><CheckCircle2 className="mr-1 h-3.5 w-3.5" /> In Inventory</Badge>
                      {item.material_id && <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => navigate(`/inventory/materials/${item.material_id}`)} data-testid={`view-material-${item.item_number}`} title="View material"><Eye className="h-4 w-4" /></Button>}
                    </div>
                  ) : (
                    <Button size="sm" variant="outline" onClick={() => addToInventory(item)} disabled={!!adding[item.item_number]} data-testid={`add-to-inventory-${item.item_number}`}>
                      {adding[item.item_number] ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Add to Inventory
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {!loading && items.length === 0 && (
              <TableRow><TableCell colSpan={8} className="py-10 text-center text-sm text-slate-400" data-testid="catalog-empty">
                <PackageSearch className="mx-auto mb-2 h-6 w-6 text-slate-300" />
                {ctx?.connected ? "No products found. Try a different search or Sync the catalog." : `Connect ${supplierName} to browse products.`}
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
        <span data-testid="catalog-total">{total != null ? `${total} product${total === 1 ? "" : "s"}` : ""}</span>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => goPage(page - 1)} disabled={page <= 1 || loading} data-testid="catalog-prev">Previous</Button>
          <span data-testid="catalog-page">Page {page} of {totalPages}</span>
          <Button size="sm" variant="outline" onClick={() => goPage(page + 1)} disabled={page >= totalPages || loading} data-testid="catalog-next">Next</Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------ RoofSpan master materials source ------------------------------ */
function MaterialsSource({ supplierId, canManage, onAddToPo }) {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [facets, setFacets] = useState({ categories: [], manufacturers: [], suppliers: [] });
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({ q: "", category: "all", manufacturer: "all", availability: "all" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = { active: true };
      if (filters.q) p.q = filters.q;
      if (filters.category !== "all") p.category = filters.category;
      if (filters.manufacturer !== "all") p.manufacturer = filters.manufacturer;
      if (filters.availability === "low") p.low_stock = true;
      if (supplierId) p.supplier_id = supplierId;
      const { data } = await api.get("/materials", { params: p });
      let out = data;
      if (filters.availability === "in") out = out.filter((m) => m.available > 0);
      setRows(out);
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, [filters, supplierId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get("/materials/facets").then((r) => setFacets(r.data)).catch(() => {}); }, []);

  return (
    <div data-testid="catalog-materials-source">
      <div className="mb-4 flex flex-wrap items-center gap-2" data-testid="catalog-material-filters">
        <div className="relative w-64"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" /><Input value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} placeholder="Search name / SKU / mfr" className="pl-8" data-testid="catalog-material-search" /></div>
        <Select value={filters.category} onValueChange={(v) => setFilters({ ...filters, category: v })}><SelectTrigger className="w-40" data-testid="catalog-filter-category"><SelectValue placeholder="Category" /></SelectTrigger><SelectContent><SelectItem value="all">All categories</SelectItem>{facets.categories.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent></Select>
        <Select value={filters.manufacturer} onValueChange={(v) => setFilters({ ...filters, manufacturer: v })}><SelectTrigger className="w-40" data-testid="catalog-filter-manufacturer"><SelectValue placeholder="Manufacturer" /></SelectTrigger><SelectContent><SelectItem value="all">All manufacturers</SelectItem>{facets.manufacturers.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent></Select>
        <Select value={filters.availability} onValueChange={(v) => setFilters({ ...filters, availability: v })}><SelectTrigger className="w-36" data-testid="catalog-filter-availability"><SelectValue placeholder="Availability" /></SelectTrigger><SelectContent><SelectItem value="all">All stock</SelectItem><SelectItem value="in">In stock</SelectItem><SelectItem value="low">Low stock</SelectItem></SelectContent></Select>
      </div>

      <div className="overflow-x-auto rounded-md border border-border bg-white">
        <Table data-testid="catalog-materials-table">
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead><TableHead>Manufacturer</TableHead><TableHead>Category</TableHead>
              <TableHead className="text-right">Available</TableHead>
              <TableHead>Preferred Supplier</TableHead><TableHead>Best Known Cost</TableHead>
              <TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((m) => {
              const same = m.primary_supplier_name && m.best_supplier_name && m.primary_supplier_name === m.best_supplier_name;
              return (
                <TableRow key={m.id} data-testid={`catalog-material-row-${m.id}`}>
                  <TableCell className="max-w-[260px]">
                    <div className="cursor-pointer font-medium text-slate-800 hover:text-orange-600" onClick={() => navigate(`/inventory/materials/${m.id}`)}>{m.name}</div>
                    <div className="text-xs text-slate-400">{m.brand || m.sku || ""}{m.supplier_count ? ` · ${m.supplier_count} supplier${m.supplier_count === 1 ? "" : "s"}` : ""}</div>
                  </TableCell>
                  <TableCell className="text-sm text-slate-600">{m.manufacturer || "—"}</TableCell>
                  <TableCell className="text-sm text-slate-500">{m.category || "—"}</TableCell>
                  <TableCell className="text-right tabular-nums">{m.available}<span className="text-xs text-slate-400"> {m.unit}</span></TableCell>
                  <TableCell>
                    {m.primary_supplier_name ? (
                      <div className="space-y-0.5" data-testid={`preferred-${m.id}`}>
                        <div className="flex items-center gap-1 text-sm font-medium text-slate-800"><Star className="h-3 w-3 fill-indigo-500 text-indigo-500" />{m.primary_supplier_name}</div>
                        <div className="flex items-center gap-1.5">
                          <span className="tabular-nums text-sm">{m.primary_supplier_cost != null ? money(m.primary_supplier_cost) : "—"}</span>
                          <PriceBadge status={m.primary_supplier_status} provider={m.primary_supplier_provider} updatedAt={m.primary_supplier_updated_at} testid={`preferred-badge-${m.id}`} />
                        </div>
                      </div>
                    ) : <span className="text-xs text-slate-300">No preferred</span>}
                  </TableCell>
                  <TableCell>
                    {m.best_supplier_name ? (
                      <div className="space-y-0.5" data-testid={`best-${m.id}`}>
                        <div className="text-sm font-medium text-slate-800">{m.best_supplier_name}{same ? " (preferred)" : ""}</div>
                        <div className="flex items-center gap-1.5">
                          <span className="tabular-nums text-sm">{m.best_known_cost != null ? money(m.best_known_cost) : "—"}</span>
                          <PriceBadge status={m.best_supplier_status} provider={m.best_supplier_provider} updatedAt={m.best_supplier_updated_at} testid={`best-badge-${m.id}`} />
                        </div>
                      </div>
                    ) : <span className="text-xs text-slate-300">—</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => navigate(`/inventory/materials/${m.id}`)} data-testid={`catalog-view-${m.id}`} title="View material"><Eye className="h-4 w-4" /></Button>
                      {canManage && <Button size="sm" variant="outline" onClick={() => onAddToPo(m)} data-testid={`catalog-add-po-${m.id}`}><ShoppingCart className="h-4 w-4" /> Add to PO</Button>}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
            {!loading && rows.length === 0 && (
              <TableRow><TableCell colSpan={7} className="py-10 text-center text-sm text-slate-400" data-testid="catalog-materials-empty">
                <PackageSearch className="mx-auto mb-2 h-6 w-6 text-slate-300" /> No materials found.
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

/* ------------------------------ Page ------------------------------ */
export default function ProductCatalog() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const [suppliers, setSuppliers] = useState([]);
  const [sourceId, setSourceId] = useState("all"); // "all" | supplier id
  const [poOpen, setPoOpen] = useState(false);
  const [poPreset, setPoPreset] = useState({ supplierId: undefined, materialId: undefined });

  useEffect(() => { api.get("/suppliers", { params: { active: true } }).then((r) => setSuppliers(r.data)).catch(() => {}); }, []);

  const selected = suppliers.find((s) => s.id === sourceId) || null;
  const abcMode = selected?.integration_provider === ABC_PROVIDER;
  const manualSupplierId = selected && !abcMode ? selected.id : "";

  const handleAddToPo = (material) => {
    setPoPreset({ supplierId: manualSupplierId || undefined, materialId: material?.id });
    setPoOpen(true);
  };
  const handleAbcAddToPo = () => {
    setPoPreset({ supplierId: selected?.id, materialId: undefined });
    setPoOpen(true);
  };

  return (
    <div>
      <PageHeader title="Product Catalog" description="Browse RoofSpan materials and supplier catalogs, compare pricing, and source products." testid="page-product-catalog" />

      <div className="p-6 sm:p-8">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => navigate("/inventory")} data-testid="catalog-back"><ArrowLeft className="h-4 w-4" /> Inventory</Button>
          <div className="w-64">
            <Select value={sourceId} onValueChange={setSourceId}>
              <SelectTrigger data-testid="catalog-source-select"><SelectValue placeholder="Source" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all" data-testid="catalog-source-all">All sources (RoofSpan)</SelectItem>
                {suppliers.map((s) => (
                  <SelectItem key={s.id} value={s.id} data-testid={`catalog-source-${s.id}`}>
                    {s.name}{s.integration_provider === ABC_PROVIDER ? " · Live catalog" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {abcMode && canManage && <Button variant="outline" size="sm" onClick={handleAbcAddToPo} data-testid="catalog-abc-new-po"><ShoppingCart className="h-4 w-4" /> New {selected?.name} PO</Button>}
        </div>

        {abcMode
          ? <AbcCatalogSource supplierName={selected?.name || "ABC Supply"} />
          : <MaterialsSource supplierId={manualSupplierId} canManage={canManage} onAddToPo={handleAddToPo} />}
      </div>

      <PODialog open={poOpen} onOpenChange={setPoOpen} initialSupplierId={poPreset.supplierId} initialMaterialId={poPreset.materialId} onCreated={() => setPoOpen(false)} />
    </div>
  );
}
