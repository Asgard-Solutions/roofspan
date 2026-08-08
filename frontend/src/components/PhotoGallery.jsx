import { useEffect, useRef, useState, useCallback } from "react";
import { api, apiError } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Image as ImageIcon, Loader2, User, Clock } from "lucide-react";

/**
 * Read-only Office-side photo gallery for field evidence.
 * Images are fetched WITH the auth token (axios) and rendered via blob object URLs —
 * the backend stays authoritative over access control; no public/object-storage URLs are used.
 *
 * Props:
 *   recordType: "lead" | "inspection" | "job" | "property" | "visit"
 *   recordId:   string (the record's id)
 *   compact:    boolean (smaller thumbnails, for nested use inside a card)
 *   testid:     optional data-testid prefix
 */
export default function PhotoGallery({ recordType, recordId, compact = false, testid }) {
  const [photos, setPhotos] = useState([]);
  const [urls, setUrls] = useState({}); // photoId -> objectURL
  const [loading, setLoading] = useState(true);
  const [active, setActive] = useState(null); // photo currently opened in dialog
  const urlsRef = useRef({});

  const tid = testid || `photos-${recordType}-${recordId}`;

  const revokeAll = useCallback(() => {
    Object.values(urlsRef.current).forEach((u) => {
      try { URL.revokeObjectURL(u); } catch (e) { /* noop */ }
    });
    urlsRef.current = {};
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    revokeAll();
    setUrls({});
    setPhotos([]);

    (async () => {
      if (!recordType || !recordId) { setLoading(false); return; }
      try {
        const { data } = await api.get("/mobile/photos", { params: { record_type: recordType, record_id: recordId } });
        if (cancelled) return;
        setPhotos(data);
        // Fetch each image with auth -> blob object URL
        await Promise.all(
          data.map(async (p) => {
            try {
              const res = await api.get(`/mobile/photos/${p.id}/content`, { responseType: "blob" });
              if (cancelled) return;
              const objectUrl = URL.createObjectURL(res.data);
              urlsRef.current[p.id] = objectUrl;
              setUrls((prev) => ({ ...prev, [p.id]: objectUrl }));
            } catch (e) { /* individual image failure is non-fatal */ }
          })
        );
      } catch (e) {
        if (!cancelled) apiError(e); // silent-ish; parent pages surface toasts elsewhere
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordType, recordId]);

  // Revoke object URLs on unmount
  useEffect(() => () => revokeAll(), [revokeAll]);

  const fmt = (iso) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-3 text-sm text-slate-400" data-testid={`${tid}-loading`}>
        <Loader2 className="h-4 w-4 animate-spin" /> Loading photos…
      </div>
    );
  }

  if (!photos.length) {
    return <p className="text-sm text-slate-500" data-testid={`${tid}-empty`}>No field photos yet.</p>;
  }

  const thumbClass = compact ? "h-16 w-16" : "aspect-square w-full";
  const gridClass = compact ? "flex flex-wrap gap-2" : "grid grid-cols-3 gap-2 sm:grid-cols-4";

  return (
    <div data-testid={tid}>
      <div className={gridClass}>
        {photos.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => setActive(p)}
            className={`group relative overflow-hidden rounded-md border border-border bg-slate-50 ${compact ? "" : ""}`}
            data-testid={`${tid}-thumb-${p.id}`}
            title={p.category || "Photo"}
          >
            {urls[p.id] ? (
              <img src={urls[p.id]} alt={p.category || "field photo"} className={`${thumbClass} object-cover transition group-hover:opacity-90`} />
            ) : (
              <div className={`${thumbClass} flex items-center justify-center text-slate-300`}>
                <ImageIcon className="h-5 w-5" />
              </div>
            )}
            {p.category && !compact && (
              <span className="absolute bottom-1 left-1 rounded bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white">
                {p.category}
              </span>
            )}
          </button>
        ))}
      </div>

      <Dialog open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <DialogContent className="max-w-2xl" data-testid={`${tid}-viewer`}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ImageIcon className="h-4 w-4 text-orange-600" />
              {active?.category || "Field photo"}
            </DialogTitle>
          </DialogHeader>
          {active && (
            <div className="space-y-3">
              <div className="flex justify-center rounded-md bg-slate-900/5 p-2">
                {urls[active.id] ? (
                  <img src={urls[active.id]} alt={active.category || "field photo"} className="max-h-[60vh] w-auto rounded" data-testid={`${tid}-fullimg`} />
                ) : (
                  <div className="flex h-48 w-full items-center justify-center text-slate-300"><ImageIcon className="h-8 w-8" /></div>
                )}
              </div>
              <div className="space-y-2 text-sm">
                {active.category && (
                  <div><Badge variant="secondary" className="bg-orange-50 text-orange-700">{active.category}</Badge></div>
                )}
                {active.description && (
                  <p className="text-slate-700" data-testid={`${tid}-note`}><span className="text-slate-400">Note: </span>{active.description}</p>
                )}
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-slate-500">
                  <span className="flex items-center gap-1.5" data-testid={`${tid}-uploader`}><User className="h-3.5 w-3.5 text-slate-400" /> {active.uploaded_by || "Unknown"}</span>
                  <span className="flex items-center gap-1.5" data-testid={`${tid}-timestamp`}><Clock className="h-3.5 w-3.5 text-slate-400" /> {fmt(active.created_at)}</span>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
