import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { quickPicks, toLocalInput } from "@/lib/followups";

export function DateTimeField({ value, onChange, testid }) {
  return (
    <div className="space-y-2">
      <Input type="datetime-local" value={value} onChange={(e) => onChange(e.target.value)} data-testid={testid} />
      <div className="flex flex-wrap gap-1.5">
        {quickPicks().map((q) => (
          <Button key={q.label} type="button" size="sm" variant="outline" className="h-7 rounded-full px-3 text-xs"
            onClick={() => onChange(toLocalInput(q.date))} data-testid={`${testid}-pick-${q.label.toLowerCase().replace(/\s+/g, "-")}`}>
            {q.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
