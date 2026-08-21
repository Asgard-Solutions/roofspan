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
    accepted: "MapTiler returned the known address location",
    exact_address_identity: "MapTiler returned the known address location",
    known_address_located_by_building_number: "Located from the known house number and nearby MapTiler building data",
    no_result: "No MapTiler location result",
    invalid_response: "Invalid provider response",
    invalid_feature: "Invalid provider feature",
    invalid_coordinates: "Invalid returned coordinates",
    not_address_result: "MapTiler found the road/place but not a confident property location",
    no_house_number: "MapTiler found the road but not a confident house-number location",
    house_number_mismatch: "MapTiler returned a different house number",
    street_mismatch: "MapTiler returned a different street",
    city_mismatch: "MapTiler returned a different city",
    state_mismatch: "MapTiler returned a different state",
    zip_mismatch: "MapTiler returned a different ZIP code",
    returned_street_missing: "MapTiler result did not include a street",
    returned_city_missing: "MapTiler result did not include a city",
    returned_state_missing: "MapTiler result did not include a state",
    returned_zip_missing: "MapTiler result did not include a ZIP code",
    low_relevance: "MapTiler result was not close enough to the known address",
    invalid_relevance: "Invalid relevance value",
    outside_territory: "Located point was outside the territory",
    provider_http_error: "MapTiler returned an HTTP error",
    provider_request_error: "MapTiler request failed",
    single_result_count_mismatch: "MapTiler returned an unexpected result count",
    single_request_exception: "MapTiler request failed unexpectedly",
    maptiler_not_configured: "MapTiler location service is not configured",
    unexpected_geocoder_error: "Unexpected MapTiler error",
    not_attempted: "MapTiler location lookup was not attempted",
  };
  return labels[reason] || reason || "Unknown";
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
      toast.success(data.resolved ? "Property located with MapTiler" : "MapTiler could not confidently locate this property");
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
  const maptilerUsed = ["maptiler_address", "maptiler_numbered_building", "maptiler_location"].includes(loc?.coordinate_source);
  const locationResolved = loc?.location_resolved === true || maptilerUsed;
  const pinSource = loc?.coordinate_source === "maptiler_numbered_building"
    ? "MapTiler numbered building"
    : loc?.coordinate_source === "maptiler_address"
      ? "MapTiler address point"
      : loc?.coordinate_source === "maptiler_location"
        ? "MapTiler located point"
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
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Pin location diagnostics</div>
              {loc ? (
                <div className="mt-2 rounded-md border border-border p-3 text-sm" data-testid="pin-location-diagnostics">
                  <div className="flex items-center gap-2 font-medium text-slate-900">
                    {locationResolved ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <AlertTriangle className="h-4 w-4 text-amber-500" />}
                    Pin source: {pinSource}
                  </div>
                  <div className={`mt-2 rounded px-2 py-1.5 text-xs font-semibold ${locationResolved ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"}`}>
                    Pin location: {locationResolved ? "RESOLVED" : "UNRESOLVED"}
                  </div>
                  {!locationResolved && (
                    <div className="mt-2 text-xs text-slate-600">
                      RentCast supplied this property's address. MapTiler has not yet found a confident location for that known address, so RoofSpan is keeping the RentCast pin.
                    </div>
                  )}
                  <div className="mt-2 space-y-1 text-xs text-slate-600">
                    <div><span className="font-medium text-slate-700">Active pin:</span> {formatCoords(p.latitude, p.longitude)}</div>
                    <div><span className="font-medium text-slate-700">RentCast source:</span> {formatCoords(loc.rentcast_latitude, loc.rentcast_longitude)}</div>
                    {locationResolved && (
                      <div><span className="font-medium text-slate-700">MapTiler location:</span> {formatCoords(loc.maptiler_latitude, loc.maptiler_longitude)}</div>
                    )}
                    {loc.building_number && <div><span className="font-medium text-slate-700">Matched building number:</span> {loc.building_number}</div>}
                    <div><span className="font-medium text-slate-700">Status:</span> {humanReason(loc.maptiler_reason)}</div>
                    {loc.maptiler_http_status != null && <div><span className="font-medium text-slate-700">HTTP:</span> {loc.maptiler_http_status}</div>}
                    {loc.maptiler_returned_address && <div><span className="font-medium text-slate-700">MapTiler returned number:</span> {loc.maptiler_returned_address}</div>}
                    {loc.maptiler_returned_label && <div><span className="font-medium text-slate-700">MapTiler search result:</span> {loc.maptiler_returned_label}</div>}
                    {loc.maptiler_relevance != null && <div><span className="font-medium text-slate-700">Search relevance:</span> {Number(loc.maptiler_relevance).toFixed(2)}</div>}
                    <div><span className="font-medium text-slate-700">Known address:</span> {loc.query_address || p.formatted_address}</div>
                  </div>
                  {canLocate && p.source === "rentcast" && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="mt-3 w-full"
                      onClick={locateProperty}
                      disabled={locating}
                      data-testid="locate-property-button"
                    >
                      {locating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Crosshair className="h-4 w-4" />}
                      {locating ? "Locating property..." : "Locate property with MapTiler"}
                    </Button>
                  )}
                </div>
              ) : (
                <div className="mt-2 space-y-2">
                  <div className="flex items-center gap-2 text-sm text-slate-400">
                    <Crosshair className="h-4 w-4" /> MapTiler location lookup has not run for this property yet.
                  </div>
                  {canLocate && p.source === "rentcast" && (
                    <Button size="sm" variant="outline" className="w-full" onClick={locateProperty} disabled={locating} data-testid="locate-property-button">
                      {locating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Crosshair className="h-4 w-4" />}
                      {locating ? "Locating property..." : "Locate property with MapTiler"}
                    </Button>
                  )}
                </div>
              )}
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
