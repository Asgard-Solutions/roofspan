import { Construction } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";

export default function Placeholder({ title, phase = "a later Office phase" }) {
  return (
    <div>
      <PageHeader title={title} testid={`page-${title.toLowerCase()}`} />
      <div className="p-6 sm:p-8">
        <div className="flex max-w-xl items-start gap-4 rounded-md border border-dashed border-border bg-white p-8">
          <Construction className="mt-0.5 h-6 w-6 text-orange-500" />
          <div>
            <h3 className="font-heading text-lg font-semibold text-slate-900">Coming in {phase}</h3>
            <p className="mt-1 text-sm text-slate-500">
              {title} is part of the RoofSpan roadmap and will be built after the Foundation phase is
              complete. The Office is being built one workflow at a time to keep it simple.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
