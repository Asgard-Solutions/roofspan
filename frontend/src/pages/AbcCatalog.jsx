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
import { Search, RefreshCw, Loader2, Plus, CheckCircle2, PackageSearch, ArrowLeft, AlertTriangle, ExternalLink } from "lucide-react";

const PAGE_SIZE = 25;

function fmtTime(s) {
  if (!s) return "—";
  try { return new Date(s).toLocaleString(); } catch { return s; }
}

export default function AbcCatalog() {
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
    try { const { data } = await api.get("/integrations/abc/catalog/sync/status"); setSync(data); }
    catch { /* ignore */ }
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
    } catch { /* pricing is best-effort */ }
  }, []);

  const load = useCallback(async (opts = {}) => {
    const p = opts.page ?? page;
    setLoading(true);
    try {
      const { data } = await api.get("/integrations/abc/catalog", { params: { q: q || undefined, page: p, page_size: PAGE_SIZE, active_only: true } });
      setItems(data.items || []);
      setCtx(data.context);
      setTotal(data.total);
      setTotalPages(data.total_pages || 1);
      setSource(data.source);
      setPage(data.page || p);
      priceVisible(data.items || [], data.context);
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  }, [q, page, priceVisible]);

  useEffect(() => { load({ page: 1 }); loadSync(); /* eslint-disable-next-line */ }, []);

  const doSearch = () => { setPrices({}); load({ page: 1 }); };
  const goPage = (p) => { if (p < 1 || p > totalPages) return; load({ page: p }); };

  const runSync = async () => {
    setSyncing(true);
    try {
      await api.post("/integrations/abc/catalog/sync");
      toast.success("Catalog sync started");
      // poll a few times
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
    <div>
      <PageHeader title="ABC Supply Catalog" description="Search ABC Supply products and add materials to RoofSpan Inventory." testid="page-abc-catalog" />

      <div className="mb-4 flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => navigate("/inventory")} data-testid="catalog-back"><ArrowLeft className="h-4 w-4" /> Inventory</Button>
      </div>

      {/* Context / connection */}
      {ctx && !ctx.connected && (
        <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900" data-testid="catalog-disconnected">
          <div className="flex items-center gap-1.5 font-medium"><AlertTriangle className="h-4 w-4" /> ABC Supply is not connected</div>
          <p className="mt-1">Connect your ABC Supply account to browse the live catalog and pricing.</p>
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

      {/* Context bar + sync */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-slate-50 p-3 text-sm" data-testid="catalog-context">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="font-medium text-slate-700">ABC Supply</span>
          <span className="text-slate-500">Ship-To: <span className="font-medium text-slate-700" data-testid="catalog-ship-to">{ctx?.ship_to_name || ctx?.ship_to_number || "—"}</span></span>
          <span className="text-slate-500">Branch: <span className="font-medium text-slate-700" data-testid="catalog-branch">{ctx?.branch_number || "—"}</span></span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500" data-testid="catalog-sync-status">
            {sync?.status === "syncing" || syncing ? "Syncing…" : sync?.status === "failed" ? <span className="text-red-500">Sync failed</span> : sync?.last_synced_at ? `Last synced: ${fmtTime(sync.last_synced_at)} (${sync.total_items} items)` : "Never synced"}
          </span>
          <Button size="sm" variant="outline" onClick={runSync} disabled={syncing || !ctx?.connected} data-testid="catalog-sync-button">
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Sync ABC Catalog
          </Button>
        </div>
      </div>

      {/* Search */}
      <div className="mb-4 flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && doSearch()} placeholder="Search description or ABC item number" className="pl-8" data-testid="catalog-search-input" />
        </div>
        <Button onClick={doSearch} disabled={loading} data-testid="catalog-search-button">{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} Search</Button>
        {source === "live" && <Badge variant="secondary" className="bg-blue-50 text-blue-700">Live</Badge>}
      </div>

      <div className="rounded-md border border-border">
        <Table data-testid="catalog-table">
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead>
              <TableHead>Item #</TableHead>
              <TableHead>Manufacturer</TableHead>
              <TableHead>UoM</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Availability</TableHead>
              <TableHead>Price</TableHead>
              <TableHead></TableHead>
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
                <TableCell>{priceCell(item)}</TableCell>
                <TableCell className="text-right">
                  {item.in_inventory ? (
                    <Badge className="bg-green-50 text-green-700" variant="secondary" data-testid={`in-inventory-${item.item_number}`}><CheckCircle2 className="mr-1 h-3.5 w-3.5" /> In Inventory</Badge>
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
                {ctx?.connected ? "No products found. Try a different search or Sync the ABC catalog." : "Connect ABC Supply to browse products."}
              </TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
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
