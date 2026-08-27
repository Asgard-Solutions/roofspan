import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import PhotoGallery from "@/components/PhotoGallery";
import { Ban, User, Home, MapPin, Loader2, UserPlus, Bed, Bath, Ruler, CalendarClock, Crosshair, CheckCircle2, AlertTriangle } from "lucide-react";

const OUTCOMES = [
  { value: "no_answer", label: "No answer" },
  { value: "not_interested", label: "Not interested" },
  { value: "interested", label: "Interested" },
  { value: "callback", label: "Callback requested" },
  { value: "appointment", label: "Appointment set" },
  { value: "do_not_knock", label: "Do Not Knock" },
];
const MANAGE = ["owner", "administrator", "office"];

function Stat({ icon: Icon, label, value }) {
  if (value == null || value === "") return null;
  return (
    <div className="flex items-center gap-2 text-sm text-slate-700">
      <Icon className="h-4 w-4 text-slate-400" />
      <span className="text-slate-400">{label}:</span> {value}
    </div>
  );
}

function formatCoords(lat, lng) {
  if (lat == null || lng == null) return "—";
  return `${Number(lat).toFixed(6)}, ${Number(lng).toFixed(6)}`;
}

function humanReason(reason) {
  const labels = {
    known_address_located: "Known RentCast address located",
    no_result: "No Mapbox address result for the known address",
    house_number_mismatch: "Returned house number did not match",
    street_mismatch: "Returned street did not match",
    city_mismatch: "Returned city did not match",
    state_mismatch: "Returned state did not match",
    zip_mismatch: "Returned ZIP code did not match",
    low_confidence: "Mapbox match confidence was too low",
    insufficient_precision: "Mapbox result was not precise enough for a property pin",
    provider_http_error: "Mapbox returned an HTTP error",
    provider_request_error: "Mapbox request failed",
    single_result_missing: "Mapbox did not return a result for this property",
    batch_result_missing: "Mapbox batch response was missing this property",
    batch_result_count_mismatch: "Mapbox returned an unexpected batch result count",
    queued_after_rentcast_import: "Waiting for property location lookup",
  };
  return labels[reason] || reason || "Unknown";
}

function accuracyLabel(type) {
  const labels = {
    rooftop: "Rooftop",
    parcel: "Parcel",
    point: "Address point",
    interpolated: "Interpolated",
    approximate: "Approximate",
  };
  return labels[type] || type || "—";
}

export default function PropertySheet({ propertyId, open, onOpenChange, onChanged }) {
  const { user } = useAuth();
  const canLocate = MANAGE.includes(user?.role);
  const [p, setP] = useState(null);
  const [loading, setLoading] = useState(false);
  const [locating, setLocating] = useState(false);
  const [visitOutcome, setVisitOutcome] = useState("no_answer");
  const [visitNotes, setVisitNotes] = useState("");
  const [savingVisit, setSavingVisit] = useState(false);
  const [leadOpen, setLeadOpen] = useState(false);
  const [lead, setLead] = useState({ name: "", phone: "", email: "", notes: "" });
  const [savingLead, setSavingLead] = useState(false);

  const load = () => {
    if (!propertyId) return;
    setLoading(true);
    api.get(`/properties/${propertyId}`).then((r) => setP(r.data)).catch((e) => toast.error(apiError(e))).finally(() => setLoading(false));
  };

  useEffect(() => {
    if (open && propertyId) load();
  }, [open, propertyId]); // eslint-disable-line

  const locateProperty = async () => {
    if (!p?.id) return;
    setLocating(true);
    try {
      const { data } = await api.post(`/properties/${p.id}/locate`);
      toast.success(data.resolved ? "Property located and cached" : "Mapbox could not confidently locate this property");
      load();
      onChanged && onChanged();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLocating(false);
    }
  };

  const toggleDNK = async (val) => {
    try {
      await api.patch(`/properties/${p.id}`, { do_not_knock: val, do_not_knock_reason: val ? p.do_not_knock_reason || "Marked in office" : null });
      setP({ ...p, do_not_knock: val });
      toast.success(val ? "Marked Do Not Knock" : "Do Not Knock removed");
      onChanged && onChanged();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const addVisit = async () => {
    setSavingVisit(true);
    try {
      await api.post(`/properties/${p.id}/visits`, { outcome: visitOutcome, notes: visitNotes });
      toast.success("Visit recorded");
      setVisitNotes("");
      load();
      onChanged && onChanged();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSavingVisit(false);
    }
  };

  const convertLead = async () => {
    setSavingLead(true);
    try {
      await api.post(`/properties/${p.id}/convert-to-lead`, lead);
      toast.success("Lead created");
      setLeadOpen(false);
      setLead({ name: "", phone: "", email: "", notes: "" });
      load();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSavingLead(false);
    }
  };

  const owner = p?.contacts?.find((c) => c.kind === "owner");
  const loc = p?.location_diagnostics;
  const mapboxUsed = ["mapbox_rooftop", "mapbox_parcel", "mapbox_point", "mapbox_interpolated", "mapbox"].includes(loc?.coordinate_source);
  const locationResolved = loc?.location_resolved === true || mapboxUsed;
  const pinSource = loc?.coordinate_source === "mapbox_rooftop"
    ? "Mapbox rooftop"
    : loc?.coordinate_source === "mapbox_parcel"
      ? "Mapbox parcel"
      : loc?.coordinate_source === "mapbox_point"
        ? "Mapbox address point"
        : loc?.coordinate_source === "mapbox_interpolated"
          ? "Mapbox interpolated address"
          : loc?.coordinate_source === "mapbox"
            ? "Mapbox"
            : "RentCast";

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md" data-testid="property-sheet">
        {loading || !p ? (
          <div className="flex h-full items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
        ) : (
          <>
            <SheetHeader>
              <SheetTitle className="pr-6 font-heading text-lg">{p.formatted_address || p.address_line1}</SheetTitle>
            </SheetHeader>

            {p.do_not_knock && (
              <div className="mt-3 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700" data-testid="dnk-banner">
                <Ban className="h-4 w-4" /> Do Not Knock{p.do_not_knock_reason ? ` — ${p.do_not_knock_reason}` : ""}
              </div>
            )}

            <div className="mt-4 space-y-1.5">
              <Stat icon={Home} label="Type" value={p.property_type} />
              <Stat icon={Bed} label="Beds" value={p.bedrooms} />
              <Stat icon={Bath} label="Baths" value={p.bathrooms} />
              <Stat icon={Ruler} label="Sq ft" value={p.square_footage} />
              <Stat icon={CalendarClock} label="Year built" value={p.year_built} />
              <Stat icon={MapPin} label="Coordinates" value={p.latitude ? `${p.latitude.toFixed(4)}, ${p.longitude.toFixed(4)}` : null} />
            </div>

            <div className="mt-5">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Owner / Renter</div>
              {owner ? (
                <div className="mt-2 rounded-md border border-border p-3 text-sm" data-testid="owner-info">
                  <div className="flex items-center gap-2 font-medium text-slate-900"><User className="h-4 w-4 text-slate-400" /> {owner.name}</div>
                  <div className="mt-1 text-slate-500">{owner.contact_type || "—"} · {p.owner_occupied === true ? "Owner-occupied" : p.owner_occupied === false ? "Non-owner-occupied" : "Occupancy unknown"}</div>
                  {owner.mailing_address && <div className="mt-1 text-slate-500">Mailing: {owner.mailing_address}</div>}
                </div>
              ) : (
                <div className="mt-2 text-sm text-slate-400">No owner/renter information on file.</div>
              )}
            </div>

            <div className="mt-5 flex items-center justify-between rounded-md border border-border p-3">
              <div className="flex items-center gap-2">
                <Ban className="h-4 w-4 text-red-500" />
                <span className="text-sm font-medium text-slate-900">Do Not Knock</span>
              </div>
              <Switch checked={p.do_not_knock} onCheckedChange={toggleDNK} data-testid="dnk-toggle" />
            </div>

            <div className="mt-5">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Record a visit</div>
              <div className="mt-2 space-y-2">
                <Select value={visitOutcome} onValueChange={setVisitOutcome}>
                  <SelectTrigger data-testid="visit-outcome"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {OUTCOMES.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Textarea value={visitNotes} onChange={(e) => setVisitNotes(e.target.value)} placeholder="Notes (optional)" data-testid="visit-notes" />
                <Button onClick={addVisit} disabled={savingVisit} className="w-full" data-testid="add-visit-button">
                  {savingVisit ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save visit"}
                </Button>
              </div>
            </div>

            {p.visits?.length > 0 && (
              <div className="mt-5">
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">History</div>
                <div className="mt-2 space-y-1.5" data-testid="visit-history">
                  {p.visits.map((v) => (
                    <div key={v.id} className="rounded-md border border-border px-3 py-2 text-sm">
                      <div className="flex justify-between"><span className="font-medium text-slate-800">{OUTCOMES.find((o) => o.value === v.outcome)?.label || v.outcome}</span><span className="text-xs text-slate-400">{new Date(v.visited_at).toLocaleDateString()}</span></div>
                      {v.notes && <div className="text-slate-500">{v.notes}</div>}
                      <div className="mt-2"><PhotoGallery recordType="visit" recordId={v.id} compact hideWhenEmpty testid={`visit-photos-${v.id}`} /></div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-5">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Field photos</div>
              <div className="mt-2">
                <PhotoGallery recordType="property" recordId={p.id} testid="property-photos" />
              </div>
            </div>

            <div className="mt-6">
              {p.lead_id ? (
                <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm font-medium text-green-700" data-testid="lead-exists">Lead created for this property.</div>
              ) : (
                <Button variant="default" className="w-full" onClick={() => setLeadOpen(true)} data-testid="convert-lead-button">
                  <UserPlus className="h-4 w-4" /> Convert to lead
                </Button>
              )}
            </div>

            <details className="group mt-6 rounded-md border border-border bg-slate-50" data-testid="pin-location-diagnostics">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-3 text-sm font-medium text-slate-800 [&::-webkit-details-marker]:hidden">
                <span className="flex items-center gap-2">
                  {locationResolved ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <AlertTriangle className="h-4 w-4 text-amber-500" />}
                  Pin location diagnostics
                </span>
                <span className={`rounded px-2 py-0.5 text-[10px] font-semibold ${locationResolved ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                  {locationResolved ? "RESOLVED" : "UNRESOLVED"}
                </span>
              </summary>

              <div className="border-t border-border bg-white p-3 text-sm">
                <div className="flex items-center gap-2 font-medium text-slate-900">Pin source: {pinSource}</div>
                {!locationResolved && (
                  <div className="mt-2 text-xs text-slate-600">
                    RentCast supplied this property's known address. RoofSpan keeps the RentCast pin until Mapbox returns a matching property-level location.
                  </div>
                )}
                {loc ? (
                  <div className="mt-2 space-y-1 text-xs text-slate-600">
                    <div><span className="font-medium text-slate-700">Active pin:</span> {formatCoords(p.latitude, p.longitude)}</div>
                    <div><span className="font-medium text-slate-700">RentCast source:</span> {formatCoords(loc.rentcast_latitude, loc.rentcast_longitude)}</div>
                    {locationResolved && <div><span className="font-medium text-slate-700">Mapbox location:</span> {formatCoords(loc.mapbox_latitude, loc.mapbox_longitude)}</div>}
                    <div><span className="font-medium text-slate-700">Status:</span> {humanReason(loc.geocoder_reason)}</div>
                    {loc.geocoder_http_status != null && <div><span className="font-medium text-slate-700">HTTP:</span> {loc.geocoder_http_status}</div>}
                    {loc.mapbox_formatted_address && <div><span className="font-medium text-slate-700">Matched address:</span> {loc.mapbox_formatted_address}</div>}
                    {loc.mapbox_accuracy && <div><span className="font-medium text-slate-700">Location accuracy:</span> {accuracyLabel(loc.mapbox_accuracy)}</div>}
                    {loc.mapbox_confidence && <div><span className="font-medium text-slate-700">Match confidence:</span> {String(loc.mapbox_confidence).toUpperCase()}</div>}
                    <div><span className="font-medium text-slate-700">Known address:</span> {loc.query_address || p.formatted_address}</div>
                    {loc.cached_permanently && <div className="font-medium text-green-700">Cached locally — normal map use will not geocode this address again.</div>}
                  </div>
                ) : (
                  <div className="mt-2 text-xs text-slate-500">Property location lookup has not run yet.</div>
                )}
                {canLocate && p.source === "rentcast" && (
                  <Button size="sm" variant="outline" className="mt-3 w-full" onClick={locateProperty} disabled={locating} data-testid="locate-property-button">
                    {locating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Crosshair className="h-4 w-4" />}
                    {locating ? "Locating property..." : "Locate property with Mapbox"}
                  </Button>
                )}
              </div>
            </details>
          </>
        )}

        <Dialog open={leadOpen} onOpenChange={setLeadOpen}>
          <DialogContent data-testid="convert-lead-dialog">
            <DialogHeader>
              <DialogTitle>Convert to lead</DialogTitle>
              <DialogDescription>Leave name blank to use the owner's name.</DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <div className="space-y-1.5"><Label>Name</Label><Input value={lead.name} onChange={(e) => setLead({ ...lead, name: e.target.value })} placeholder={owner?.name || "Contact name"} data-testid="lead-name" /></div>
              <div className="space-y-1.5"><Label>Phone</Label><Input value={lead.phone} onChange={(e) => setLead({ ...lead, phone: e.target.value })} data-testid="lead-phone" /></div>
              <div className="space-y-1.5"><Label>Email</Label><Input value={lead.email} onChange={(e) => setLead({ ...lead, email: e.target.value })} data-testid="lead-email" /></div>
              <div className="space-y-1.5"><Label>Notes</Label><Textarea value={lead.notes} onChange={(e) => setLead({ ...lead, notes: e.target.value })} data-testid="lead-notes" /></div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setLeadOpen(false)}>Cancel</Button>
              <Button onClick={convertLead} disabled={savingLead} data-testid="save-lead">
                {savingLead ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create lead"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </SheetContent>
    </Sheet>
  );
}
