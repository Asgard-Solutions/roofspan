import { useState, useRef } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import PhotoGallery from "@/components/PhotoGallery";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, Upload, Paperclip } from "lucide-react";

const CATS = [
  { v: "packing_slip", l: "Packing Slip" },
  { v: "receipt", l: "Receipt" },
  { v: "delivery_photo", l: "Delivery Photo" },
  { v: "damage_photo", l: "Damage Photo" },
  { v: "other", l: "Other" },
];

export default function ReceivingAttachments({ poId, canUpload }) {
  const [cat, setCat] = useState("packing_slip");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const fileRef = useRef(null);

  const upload = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("record_type", "purchase_order");
      fd.append("record_id", poId);
      fd.append("category", cat);
      if (desc) fd.append("description", desc);
      await api.post("/mobile/photos", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Attachment uploaded");
      setDesc("");
      if (fileRef.current) fileRef.current.value = "";
      setReloadKey((k) => k + 1);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4" data-testid="po-attachments">
      {canUpload && (
        <div className="flex flex-wrap items-end gap-2 rounded-md border border-dashed border-border bg-slate-50/50 p-3">
          <div className="space-y-1">
            <Label className="text-xs">Type</Label>
            <Select value={cat} onValueChange={setCat}>
              <SelectTrigger className="w-40" data-testid="po-attach-cat"><SelectValue /></SelectTrigger>
              <SelectContent>{CATS.map((c) => <SelectItem key={c.v} value={c.v} data-testid={`po-attach-cat-${c.v}`}>{c.l}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="flex-1 space-y-1 min-w-[160px]">
            <Label className="text-xs">Description (optional)</Label>
            <Input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="e.g. Slip #4821" data-testid="po-attach-desc" />
          </div>
          <input ref={fileRef} type="file" accept="image/*" className="hidden" data-testid="po-attach-file"
                 onChange={(e) => upload(e.target.files?.[0])} />
          <Button size="sm" onClick={() => fileRef.current?.click()} disabled={busy} data-testid="po-attach-upload">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Upload
          </Button>
        </div>
      )}
      <PhotoGallery key={reloadKey} recordType="purchase_order" recordId={poId} compact testid="po-photos" />
    </div>
  );
}
