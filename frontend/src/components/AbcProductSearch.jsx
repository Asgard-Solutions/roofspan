import { useState, useCallback, useRef } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Search, Loader2, Package, Plus, CheckCircle2, XCircle } from "lucide-react";

// Reusable ABC Supply product selector. Requires an ABC Ship-To + Branch context (Phase 1 selection).
// Searches products, shows selected-branch availability, fetches customer price on add, and returns a
// fully-populated ABC PO line via onAdd(). Availability is shown as Available/Not — never a stock number.
export default function AbcProductSearch({ open, onOpenChange, shipTo, branch, branchLabel, onAdd }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState(null);
  const [qty, setQty] = useState(1);
  const [lengthValue, setLengthValue] = useState("");
  const [lengthUom, setLengthUom] = useState("ft");
  const [pricing, setPricing] = useState(false);
  const debounceRef = useRef(null);

  const runSearch = useCallback(async (q) => {
    if (!q || q.trim().length < 2) { setResults([]); return; }
    setSearching(true);
    try {
      const { data } = await api.post("/integrations/abc/products/search", { query: q.trim(), by: "itemDescription", branch_number: branch });
      setResults(data);
    } catch (e) { toast.error(apiError(e)); } finally { setSearching(false); }
  }, [branch]);

  const onQueryChange = (v) => {
    setQuery(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => runSearch(v), 450); // debounce; no request per keystroke
  };

  const chooseProduct = (p) => {
    setSelected(p);
    setQty(1);
    setLengthValue("");
    setLengthUom("ft");
  };

  const stockingUom = (p) => (p?.uoms?.find((u) => (u.description || "").includes("stocking")) || p?.uoms?.[0])?.code || "each";

  const addWithPrice = async () => {
    if (!selected) return;
    const q = Number(qty) || 1;
    const uom = stockingUom(selected);
    const line = { id: "1", item_number: selected.item_number, quantity: q, uom };
    if (selected.is_dimensional) {
      if (!lengthValue) { toast.error("This item requires a length variation before pricing."); return; }
      line.length_value = Number(lengthValue);
      line.length_uom = lengthUom;
    }
    setPricing(true);
    try {
      const { data } = await api.post("/integrations/abc/pricing", { ship_to_number: shipTo, branch_number: branch, purpose: "ordering", lines: [line] });
      const r = (data.lines || [])[0] || {};
      const priced = r.price_status === "priced" && r.unit_price != null;
      if (!priced) toast.warning(r.status_message || "Pricing unavailable. Contact this ABC Supply branch for pricing.");
      onAdd({
        description: selected.description || selected.item_number,
        quantity: q,
        unit: uom,
        unit_cost: priced ? Number(r.unit_price) : 0,
        integration_provider: "abc_supply",
        abc_item_number: selected.item_number,
        abc_branch_number: branch,
        abc_ship_to_number: shipTo,
        abc_uom: uom,
        abc_variation: selected.is_dimensional ? { value: Number(lengthValue), uom: lengthUom } : null,
        abc_price: priced ? Number(r.unit_price) : null,
        abc_price_status: r.price_status || "unavailable",
        abc_product_description: selected.description,
        abc_product_family: selected.product_family,
        abc_product_image_url: selected.image_url,
        pricing_source: "abc",
      });
      toast.success(priced ? `Added ${selected.item_number} at ${money(r.unit_price)}` : `Added ${selected.item_number} (pricing unavailable)`);
      setSelected(null);
    } catch (e) { toast.error(apiError(e)); } finally { setPricing(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl" data-testid="abc-product-search-dialog">
        <DialogHeader>
          <DialogTitle>Search ABC Supply Products</DialogTitle>
          <DialogDescription>Branch: {branchLabel || branch || "—"} · Ship-To: {shipTo || "—"}</DialogDescription>
        </DialogHeader>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input value={query} onChange={(e) => onQueryChange(e.target.value)} placeholder="Search products by description…" className="pl-9" data-testid="abc-product-query" />
        </div>

        <div className="max-h-[380px] overflow-y-auto rounded-md border border-border">
          {searching && <div className="p-4 text-sm text-slate-400"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Searching…</div>}
          {!searching && results.length === 0 && <div className="p-4 text-center text-sm text-slate-400">Type at least 2 characters to search ABC products.</div>}
          {!searching && results.map((p) => (
            <div key={p.item_number} className="border-b border-border last:border-0" data-testid={`abc-product-${p.item_number}`}>
              <button onClick={() => chooseProduct(p)} className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-slate-50">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded bg-slate-100 text-slate-400"><Package className="h-4 w-4" /></div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-900">{p.description || p.item_number}</div>
                  <div className="text-xs text-slate-500">{p.item_number}{p.product_family ? ` · ${p.product_family}` : ""}{p.is_dimensional ? " · dimensional" : ""}</div>
                </div>
                {p.available_at_branch ? (
                  <Badge className="bg-green-50 text-green-700" variant="secondary"><CheckCircle2 className="mr-1 h-3 w-3" />Available at Branch</Badge>
                ) : (
                  <Badge className="bg-slate-100 text-slate-500" variant="secondary"><XCircle className="mr-1 h-3 w-3" />Not Available at Branch</Badge>
                )}
              </button>
              {selected?.item_number === p.item_number && (
                <div className="flex flex-wrap items-end gap-3 border-t border-border bg-slate-50/60 px-3 py-3" data-testid="abc-product-addform">
                  <div className="space-y-1"><Label className="text-xs">Quantity ({stockingUom(p)})</Label><Input type="number" value={qty} onChange={(e) => setQty(e.target.value)} className="h-8 w-24" data-testid="abc-add-qty" /></div>
                  {p.is_dimensional && (
                    <>
                      <div className="space-y-1"><Label className="text-xs">Length</Label><Input type="number" value={lengthValue} onChange={(e) => setLengthValue(e.target.value)} className="h-8 w-24" placeholder="required" data-testid="abc-add-length" /></div>
                      <div className="space-y-1"><Label className="text-xs">Unit</Label><Input value={lengthUom} onChange={(e) => setLengthUom(e.target.value)} className="h-8 w-20" data-testid="abc-add-length-uom" /></div>
                    </>
                  )}
                  <Button size="sm" onClick={addWithPrice} disabled={pricing || !p.available_at_branch} data-testid="abc-add-to-po">
                    {pricing ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Plus className="h-4 w-4" /> Get price &amp; add</>}
                  </Button>
                  {!p.available_at_branch && <span className="text-xs text-amber-700">Not available at the selected branch.</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
