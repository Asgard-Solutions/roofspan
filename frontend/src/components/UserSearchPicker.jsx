import { useEffect, useState } from "react";
import { Check, ChevronsUpDown, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";

// Server-side type-ahead over active, assignable users.
export function UserSearchPicker({ valueId, valueLabel, onSelect, disabled, testid = "user-picker" }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    let stale = false;
    setLoading(true);
    const t = setTimeout(() => {
      api.get("/users/assignable", { params: { q: q || undefined, limit: 25 } })
        .then((r) => { if (!stale) setUsers(r.data); })
        .catch(() => { if (!stale) setUsers([]); })
        .finally(() => { if (!stale) setLoading(false); });
    }, 200);
    return () => { stale = true; clearTimeout(t); };
  }, [q, open]);

  const pick = (id) => { setOpen(false); setQ(""); onSelect(id); };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" role="combobox" disabled={disabled} className="w-full justify-between font-normal" data-testid={`${testid}-trigger`}>
          <span className={`truncate ${valueId ? "text-slate-900" : "text-slate-400"}`}>{valueLabel || "Unassigned"}</span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 text-slate-400" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] min-w-[280px] p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput placeholder="Search name or email…" value={q} onValueChange={setQ} data-testid={`${testid}-search`} />
          <CommandList>
            {loading && <div className="flex items-center gap-2 px-3 py-2 text-xs text-slate-400"><Loader2 className="h-3 w-3 animate-spin" /> Searching…</div>}
            {!loading && <CommandEmpty data-testid={`${testid}-empty`}>No active users match.</CommandEmpty>}
            <CommandGroup>
              {valueId && <CommandItem value="__none__" onSelect={() => pick(null)} data-testid={`${testid}-none`}>Unassigned</CommandItem>}
              {users.map((u) => (
                <CommandItem key={u.id} value={u.id} onSelect={() => pick(u.id)} data-testid={`${testid}-option-${u.id}`}>
                  <Check className={`mr-2 h-4 w-4 ${u.id === valueId ? "opacity-100" : "opacity-0"}`} />
                  <div className="min-w-0">
                    <div className="truncate text-sm">{u.full_name || u.email}</div>
                    <div className="truncate text-xs text-slate-400">{u.email} · {u.role}</div>
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
