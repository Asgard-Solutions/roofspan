import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Eye, EyeOff, Loader2, PlugZap, CheckCircle2, XCircle, Save, Trash2, MapPinned, PackageSearch, ChevronRight, Copy } from "lucide-react";

function IntegrationCard({ provider, label, help, keyLabel }) {
  const [data, setData] = useState(null);
  const [secret, setSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const load = () => api.get(`/integrations/${provider}`).then((r) => setData(r.data)).catch((e) => toast.error(apiError(e)));
  useEffect(() => { load(); }, []); // eslint-disable-line

  const toggleEnabled = async (val) => {
    try {
      const { data: d } = await api.put(`/integrations/${provider}`, { enabled: val });
      setData(d);
      toast.success(`${label} ${val ? "enabled" : "disabled"}`);
    } catch (e) { toast.error(apiError(e)); }
  };

  const saveSecret = async () => {
    if (!secret.trim()) { toast.error("Enter an API key first"); return; }
    setBusy(true);
    try {
      const { data: d } = await api.put(`/integrations/${provider}/secret`, { secret: secret.trim() });
      setData(d);
      setSecret("");
      setTestResult(null);
      toast.success("API key saved (encrypted)");
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const clearSecret = async () => {
    setBusy(true);
    try {
      const { data: d } = await api.delete(`/integrations/${provider}/secret`);
      setData(d);
      setTestResult(null);
      toast.success("API key removed");
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const test = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const { data: res } = await api.post(`/integrations/${provider}/test`);
      setTestResult(res);
    } catch (e) { setTestResult({ ok: false, message: apiError(e) }); } finally { setTesting(false); }
  };

  if (!data) return <div className="p-6 text-sm text-slate-400">Loading…</div>;

  return (
    <div className="max-w-2xl space-y-5 rounded-md border border-border bg-white p-6" data-testid={`integration-${provider}`}>
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-heading text-lg font-semibold text-slate-900">{label}</h3>
          <p className="mt-0.5 text-sm text-slate-500">{help}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">{data.enabled ? "Enabled" : "Disabled"}</span>
          <Switch checked={data.enabled} onCheckedChange={toggleEnabled} data-testid={`toggle-${provider}`} />
        </div>
      </div>

      <div className="space-y-1.5">
        <Label>{keyLabel}</Label>
        {data.has_secret && (
          <div className="mb-2 flex items-center justify-between rounded-md border border-border bg-slate-50 px-3 py-2">
            <span className="font-mono text-sm text-slate-600" data-testid={`masked-${provider}`}>{data.secret_masked}</span>
            <Button variant="ghost" size="sm" className="text-destructive" onClick={clearSecret} disabled={busy} data-testid={`clear-secret-${provider}`}>
              <Trash2 className="h-4 w-4" /> Remove
            </Button>
          </div>
        )}
        <div className="relative">
          <Input type={showSecret ? "text" : "password"} value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={data.has_secret ? "Enter a new key to replace" : "Paste API key"} className="pr-10 font-mono" data-testid={`secret-input-${provider}`} />
          <button type="button" onClick={() => setShowSecret((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700" tabIndex={-1}>
            {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={saveSecret} disabled={busy} data-testid={`save-secret-${provider}`}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Save className="h-4 w-4" /> Save key</>}
        </Button>
        <Button variant="outline" onClick={test} disabled={testing || !data.has_secret} data-testid={`test-${provider}`}>
          {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <><PlugZap className="h-4 w-4" /> Test connection</>}
        </Button>
      </div>

      {testResult && (
        <div className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${testResult.ok ? "border-green-200 bg-green-50 text-green-700" : "border-red-200 bg-red-50 text-red-700"}`} data-testid={`test-result-${provider}`}>
          {testResult.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
          {testResult.message}
        </div>
      )}
    </div>
  );
}

function MapSettings() {
  const [cfg, setCfg] = useState(null);
  const [cadastre, setCadastre] = useState(null);
  const [checkingCadastre, setCheckingCadastre] = useState(false);
  const load = () => api.get("/map-config").then((r) => setCfg(r.data));
  useEffect(() => { load(); }, []);

  const setSatellite = async (val) => {
    try {
      const { data } = await api.put("/map-config", { satellite_enabled: val });
      setCfg(data);
      toast.success("Map configuration updated");
    } catch (e) { toast.error(apiError(e)); }
  };

  const checkCadastre = async () => {
    setCheckingCadastre(true);
    setCadastre(null);
    try { const { data } = await api.get("/map/cadastre-capability"); setCadastre(data); }
    catch (e) { setCadastre({ configured: true, tileset_accessible: false, reason: apiError(e) }); }
    finally { setCheckingCadastre(false); }
  };

  if (!cfg) return <div className="p-6 text-sm text-slate-400">Loading…</div>;

  return (
    <div className="max-w-2xl space-y-5 rounded-md border border-border bg-white p-6" data-testid="map-settings">
      <div>
        <h3 className="font-heading text-lg font-semibold text-slate-900">Base map</h3>
        <p className="mt-0.5 text-sm text-slate-500">OpenStreetMap is the default street-map provider and requires no key.</p>
        <div className="mt-2 inline-flex items-center gap-2 rounded-md border border-border bg-slate-50 px-3 py-1.5 text-sm font-medium text-slate-700">OpenStreetMap</div>
      </div>
      <div className="border-t border-border pt-5">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="font-heading text-lg font-semibold text-slate-900">Satellite imagery (MapTiler)</h3>
            <p className="mt-0.5 text-sm text-slate-500">{cfg.maptiler_configured ? "MapTiler key is configured. Satellite imagery can be enabled." : "Add and enable a MapTiler key under the Integrations tab to use satellite imagery."}</p>
          </div>
          <Switch checked={cfg.satellite_enabled} disabled={!cfg.maptiler_configured} onCheckedChange={setSatellite} data-testid="toggle-satellite" />
        </div>
      </div>
      <div className="border-t border-border pt-5" data-testid="cadastre-capability">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-heading text-lg font-semibold text-slate-900">Parcel / Cadastre access</h3>
            <p className="mt-0.5 text-sm text-slate-500">Uses the same MapTiler API key. This checks whether the Cadastre tileset is available to RoofSpan.</p>
          </div>
          <Button variant="outline" onClick={checkCadastre} disabled={checkingCadastre || !cfg.maptiler_configured} data-testid="check-cadastre">
            {checkingCadastre ? <Loader2 className="h-4 w-4 animate-spin" /> : <><MapPinned className="h-4 w-4" /> Check parcel access</>}
          </Button>
        </div>
        {cadastre && (
          <div className={`mt-3 flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${cadastre.tileset_accessible ? "border-green-200 bg-green-50 text-green-700" : "border-amber-200 bg-amber-50 text-amber-800"}`} data-testid="cadastre-result">
            {cadastre.tileset_accessible ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
            <div><div className="font-medium">{cadastre.tileset_accessible ? "Cadastre tileset is accessible" : "Cadastre tileset is not accessible"}</div><div className="mt-0.5 text-xs opacity-80">Status: {cadastre.reason || "unknown"}{cadastre.tileset_http_status != null ? ` · HTTP ${cadastre.tileset_http_status}` : ""}</div></div>
          </div>
        )}
      </div>
    </div>
  );
}

function CompanySettings() {
  const [c, setC] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { api.get("/company").then((r) => setC(r.data)); }, []);
  const save = async () => { setSaving(true); try { const { data } = await api.put("/company", c); setC(data); toast.success("Company profile saved"); } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); } };
  if (!c) return <div className="p-6 text-sm text-slate-400">Loading…</div>;
  const field = (key, label, ph) => <div className="space-y-1.5"><Label>{label}</Label><Input value={c[key] || ""} onChange={(e) => setC({ ...c, [key]: e.target.value })} placeholder={ph} data-testid={`company-${key}`} /></div>;
  const area = (key, label, ph) => <div className="space-y-1.5"><Label>{label}</Label><textarea className="min-h-[70px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={c[key] || ""} onChange={(e) => setC({ ...c, [key]: e.target.value })} placeholder={ph} data-testid={`company-${key}`} /></div>;
  return (
    <div className="space-y-6">
      <div className="max-w-2xl space-y-4 rounded-md border border-border bg-white p-6" data-testid="company-settings">
        {field("name", "Company name", "RoofSpan Roofing Co.")}{field("phone", "Phone", "(555) 123-4567")}
        {field("email", "Email", "office@company.com")}{field("address", "Address", "123 Main St, Austin, TX")}
        {field("license_number", "License number", "TX-ROOF-0001")}
        <div className="border-t border-slate-100 pt-4 text-xs font-semibold uppercase text-slate-400">Proposal branding</div>
        {field("logo_url", "Logo URL", "https://…/logo.png")}{field("website", "Website", "www.company.com")}
        <div className="space-y-1.5"><Label>Brand color</Label><div className="flex items-center gap-2"><input type="color" value={c.primary_color || "#0f172a"} onChange={(e) => setC({ ...c, primary_color: e.target.value })} className="h-9 w-14 cursor-pointer rounded border border-input" data-testid="company-primary_color" /><Input value={c.primary_color || ""} onChange={(e) => setC({ ...c, primary_color: e.target.value })} placeholder="#0f172a" className="w-32" /></div></div>
        {area("proposal_footer_text", "Proposal footer text", "Thank you for your business.")}
        {area("proposal_terms_text", "Default proposal terms", "50% deposit due on acceptance…")}
        <Button onClick={save} disabled={saving} data-testid="save-company">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Save className="h-4 w-4" /> Save profile</>}</Button>
      </div>
      <MarginPolicySettings />
    </div>
  );
}

function MarginPolicySettings() {
  const [p, setP] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { api.get("/margin-policy").then((r) => setP(r.data)).catch(() => {}); }, []);
  const save = async () => { setSaving(true); try { const { data } = await api.put("/margin-policy", { enabled: !!p.enabled, target_minimum_margin: Number(p.target_minimum_margin) || 0 }); setP(data); toast.success("Margin policy saved"); } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); } };
  if (!p) return null;
  return (
    <div className="max-w-2xl space-y-4 rounded-md border border-border bg-white p-6" data-testid="margin-policy-settings">
      <div className="text-sm font-semibold text-slate-700">Margin guardrail</div>
      <p className="text-xs text-slate-500">Internal warning only — never blocks estimates or appears on customer proposals.</p>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!p.enabled} onChange={(e) => setP({ ...p, enabled: e.target.checked })} data-testid="margin-enabled" /> Enable margin warnings</label>
      <div className="space-y-1.5"><Label>Target minimum margin (%)</Label><Input type="number" min="0" max="100" step="0.1" value={p.target_minimum_margin} onChange={(e) => setP({ ...p, target_minimum_margin: e.target.value })} data-testid="margin-target" className="w-40" /></div>
      <Button onClick={save} disabled={saving} data-testid="save-margin-policy">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Save className="h-4 w-4" /> Save policy</>}</Button>
    </div>
  );
}

function AboutCard() {
  const [v, setV] = useState(null);
  useEffect(() => { api.get("/version").then((r) => setV(r.data)).catch(() => {}); }, []);
  const label = v ? `RoofSpan Office v${v.display_version || v.version}${v.channel && v.channel !== "stable" ? ` (${v.channel})` : ""}` : "…";
  const copy = () => { navigator.clipboard?.writeText(label); toast.success("Version copied"); };
  return (
    <div className="mb-6 flex max-w-2xl flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-white p-4" data-testid="about-version">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Software version</div>
        <div className="mt-0.5 font-mono text-sm font-medium text-slate-900" data-testid="settings-app-version">{label}</div>
        <p className="mt-0.5 text-xs text-slate-500">Share this with RoofSpan support when reporting an issue.</p>
      </div>
      <Button variant="outline" size="sm" onClick={copy} data-testid="copy-version"><Copy className="h-4 w-4" /> Copy</Button>
    </div>
  );
}

export default function Settings() {
  return (
    <div>
      <PageHeader title="Settings" description="Manage integrations, maps, and company details." testid="page-settings" />
      <div className="p-6 sm:p-8">
        <AboutCard />
        <Tabs defaultValue="integrations">
          <TabsList data-testid="settings-tabs"><TabsTrigger value="integrations" data-testid="tab-integrations">Integrations</TabsTrigger><TabsTrigger value="map" data-testid="tab-map">Map Configuration</TabsTrigger><TabsTrigger value="company" data-testid="tab-company">Company Profile</TabsTrigger></TabsList>
          <TabsContent value="integrations" className="mt-6 space-y-6">
            <Link to="/admin/settings/abc" className="block max-w-2xl" data-testid="abc-supply-link">
              <div className="flex items-center justify-between rounded-md border border-border bg-white p-6 transition-colors hover:border-orange-300 hover:bg-orange-50/40">
                <div className="flex items-start gap-3">
                  <PackageSearch className="mt-0.5 h-6 w-6 text-orange-600" />
                  <div>
                    <h3 className="font-heading text-lg font-semibold text-slate-900">ABC Supply</h3>
                    <p className="mt-0.5 text-sm text-slate-500">Connect your myABCSupply account for products, real-time pricing, and ordering.</p>
                  </div>
                </div>
                <ChevronRight className="h-5 w-5 text-slate-400" />
              </div>
            </Link>
            <IntegrationCard provider="rentcast" label="RentCast" keyLabel="RentCast API key" help="Server-side property data import. The key is encrypted and never returned to the browser." />
            <IntegrationCard provider="mapbox" label="Mapbox Permanent Geocoding" keyLabel="Mapbox access token" help="Bring your own Mapbox token for permanent address-to-coordinate lookup. RoofSpan requests permanent geocodes and caches completed results in the local database so normal map use does not geocode the same address again." />
            <IntegrationCard provider="maptiler" label="MapTiler" keyLabel="MapTiler API key" help="Server-side key for satellite imagery, building visualization, and parcel/cadastre capability checks. Property pin placement is handled separately by Mapbox Permanent Geocoding." />
          </TabsContent>
          <TabsContent value="map" className="mt-6"><MapSettings /></TabsContent>
          <TabsContent value="company" className="mt-6"><CompanySettings /></TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
