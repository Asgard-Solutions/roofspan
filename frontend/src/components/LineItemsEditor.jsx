import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { money } from "@/lib/format";
import { Plus, Trash2 } from "lucide-react";

const empty = () => ({ description: "", quantity: 1, unit: "ea", unit_price: 0 });

export function computeTotals(items, taxRate) {
  const subtotal = items.reduce((s, it) => s + Math.round((Number(it.quantity) || 0) * (Number(it.unit_price) || 0) * 100) / 100, 0);
  const tax = Math.round(subtotal * (Number(taxRate) || 0)) / 100;
  return { subtotal: Math.round(subtotal * 100) / 100, tax, total: Math.round((subtotal + tax) * 100) / 100 };
}

export default function LineItemsEditor({ items, onChange, taxRate, onTaxChange }) {
  const update = (i, field, val) => {
    const next = items.map((it, idx) => (idx === i ? { ...it, [field]: val } : it));
    onChange(next);
  };
  const add = () => onChange([...items, empty()]);
  const remove = (i) => onChange(items.filter((_, idx) => idx !== i));
  const { subtotal, tax, total } = computeTotals(items, taxRate);

  return (
    <div className="space-y-2" data-testid="line-items-editor">
      <div className="grid grid-cols-[1fr_60px_50px_80px_80px_28px] items-center gap-2 text-xs font-semibold uppercase text-slate-400">
        <span>Description</span><span>Qty</span><span>Unit</span><span>Price</span><span className="text-right">Total</span><span />
      </div>
      {items.map((it, i) => (
        <div key={i} className="grid grid-cols-[1fr_60px_50px_80px_80px_28px] items-center gap-2">
          <Input value={it.description} onChange={(e) => update(i, "description", e.target.value)} placeholder="Item" data-testid={`li-desc-${i}`} className="h-8" />
          <Input type="number" value={it.quantity} onChange={(e) => update(i, "quantity", e.target.value)} data-testid={`li-qty-${i}`} className="h-8" />
          <Input value={it.unit} onChange={(e) => update(i, "unit", e.target.value)} className="h-8" />
          <Input type="number" value={it.unit_price} onChange={(e) => update(i, "unit_price", e.target.value)} data-testid={`li-price-${i}`} className="h-8" />
          <span className="text-right text-sm tabular-nums text-slate-700">{money((Number(it.quantity) || 0) * (Number(it.unit_price) || 0))}</span>
          <button onClick={() => remove(i)} className="text-slate-300 hover:text-red-500" data-testid={`li-remove-${i}`}><Trash2 className="h-4 w-4" /></button>
        </div>
      ))}
      <Button variant="outline" size="sm" onClick={add} data-testid="add-line-item"><Plus className="h-4 w-4" /> Add line</Button>

      <div className="mt-3 space-y-1 border-t border-border pt-3 text-sm">
        <div className="flex items-center justify-between"><span className="text-slate-500">Subtotal</span><span className="tabular-nums" data-testid="li-subtotal">{money(subtotal)}</span></div>
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-slate-500">Tax rate %
            <Input type="number" value={taxRate} onChange={(e) => onTaxChange(e.target.value)} className="h-7 w-20" data-testid="li-taxrate" />
          </span>
          <span className="tabular-nums" data-testid="li-tax">{money(tax)}</span>
        </div>
        <div className="flex items-center justify-between font-semibold text-slate-900"><span>Total</span><span className="tabular-nums" data-testid="li-total">{money(total)}</span></div>
      </div>
    </div>
  );
}
