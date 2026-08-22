import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Loader2, PlugZap, CheckCircle2, XCircle, Save, Trash2, Link2, Unlink, RefreshCw, Building2, ShieldCheck, Eye, EyeOff, Copy, AlertTriangle,
} from "lucide-react";

const STATUS_BADGE = {
  connected: { cls: "bg-green-50 text-green-700", label: "Connected" },
  not_connected: { cls: "bg-slate-100 text-slate-600", label: "Not Connected" },
  reconnect_required: { cls: "bg-amber-50 text-amber-700", label: "Reconnect Required" },
};

function Section({ title, description, children, testid }) {
  return (
    <div className="max-w-2xl space-y-5 rounded-md border border-border bg-white p-6" data-testid={testid}>
      <div>
        <h3 className="font-heading text-lg font-semibold text-slate-900">{title}</h3>
        {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
      </div>
      {children}
    </div>
  );
}

export default function AbcSupply() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [params, setParams] = useSearchParams();

  // config form
  const [environment, setEnvironment] = useState("sandbox");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [redirectUri, setRedirectUri] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");

  // account/branch selection
  const [accounts, setAccounts] = useState([]);
  const [branches, setBranches] = useState([]);
  const [shipTo, setShipTo] = useState("");
  const [branch, setBranch] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/integrations/abc/status");
      setStatus(data);
      setEnvironment(data.environment || "sandbox");
      setRedirectUri(data.redirect_uri || "");
      setWebhookUrl(data.webhook_public_url || "");
      setShipTo(data.default_ship_to_number || "");
      setBranch(data.default_branch_number || "");
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Handle OAuth callback return (?abc=connected|error)
  useEffect(() => {
    const abc = params.get("abc");
    if (!abc) return;
    if (abc === "connected") toast.success("ABC Supply connected");
    else toast.error(`ABC Supply connection failed${params.get("reason") ? `: ${params.get("reason")}` : ""}`);
    params.delete("abc"); params.delete("reason");
    setParams(params, { replace: true });
  }, [params, setParams]);

  const loadAccounts = useCallback(async () => {
    try {
      const { data } = await api.get("/integrations/abc/accounts");
      setAccounts(data);
    } catch (e) { /* not connected yet */ }
  }, []);

  useEffect(() => { if (status?.status === "connected") loadAccounts(); }, [status?.status, loadAccounts]);

  useEffect(() => {
    if (status?.status === "connected" && shipTo) {
      api.get(`/integrations/abc/branches?ship_to=${encodeURIComponent(shipTo)}`).then((r) => setBranches(r.data)).catch(() => {});
    }
  }, [status?.status, shipTo]);

  const saveConfig = async () => {
    setBusy(true);
    try {
      await api.put("/integrations/abc/config", {
        environment, client_id: clientId || null, redirect_uri: redirectUri || null, webhook_public_url: webhookUrl || null,
      });
      if (clientSecret.trim()) {
        await api.put("/integrations/abc/config/secret", { client_secret: clientSecret.trim() });
        setClientSecret("");
      }
      toast.success("ABC Supply configuration saved");
      await load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const connect = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/integrations/abc/connect");
      window.location.href = data.authorize_url;
    } catch (e) { toast.error(apiError(e)); setBusy(false); }
  };

  const disconnect = async () => {
    setBusy(true);
    try { await api.post("/integrations/abc/disconnect"); toast.success("ABC Supply disconnected"); setTestResult(null); await load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const test = async () => {
    setTesting(true); setTestResult(null);
    try { const { data } = await api.post("/integrations/abc/test"); setTestResult(data); }
    catch (e) { setTestResult({ ok: false, message: apiError(e) }); } finally { setTesting(false); }
  };

  const copyRedirect = async (value) => {
    try { await navigator.clipboard.writeText(value); toast.success("Redirect URI copied"); }
    catch { toast.error("Could not copy — select and copy manually"); }
  };

  const saveDefaults = async () => {
    setBusy(true);
    try {
      await api.put("/integrations/abc/defaults", { default_ship_to_number: shipTo || null, default_branch_number: branch || null });
      toast.success("Default Ship-To and branch saved");
      await load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  if (loading || !status) return <div className="p-8 text-sm text-slate-400">Loading…</div>;

  const sb = STATUS_BADGE[status.status] || STATUS_BADGE.not_connected;
  const connected = status.status === "connected";
  const identity = status.connected_identity || {};

  return (
    <div>
      <PageHeader title="ABC Supply" description="Connect your myABCSupply account for products, pricing, and ordering." testid="page-abc-supply" />
      <div className="space-y-6 p-6 sm:p-8">
        {status.is_mock && (
          <div className="max-w-2xl rounded-md border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm text-blue-800" data-testid="abc-mock-banner">
            <ShieldCheck className="mr-1 inline h-4 w-4" /> Local mock ABC server is active (development mode). No real ABC calls are made.
          </div>
        )}

        {/* Connection status */}
        <Section title="Connection" description="Connect your myABCSupply account through the browser. RoofSpan never stores your ABC username or password." testid="abc-connection-card">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-slate-500">Status</span>
            <Badge className={sb.cls} variant="secondary" data-testid="abc-status-badge">{sb.label}</Badge>
          </div>
          {connected && (
            <div className="rounded-md border border-border bg-slate-50 px-4 py-3 text-sm text-slate-600" data-testid="abc-identity">
              <div><span className="text-slate-400">Connected Account:</span> {identity.sold_to_name || "—"} {identity.sold_to_number ? `(${identity.sold_to_number})` : ""}</div>
              {status.last_connected_at && <div><span className="text-slate-400">Last Connected:</span> {new Date(status.last_connected_at).toLocaleString()}</div>}
              {status.token_scopes && <div className="mt-1 text-xs text-slate-400">Scopes: {status.token_scopes}</div>}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {!connected && (
              <Button onClick={connect} disabled={busy || !status.has_client_id} data-testid="abc-connect-button">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Link2 className="h-4 w-4" /> Connect ABC Supply</>}
              </Button>
            )}
            {connected && (
              <>
                <Button variant="outline" onClick={connect} disabled={busy} data-testid="abc-reconnect-button"><RefreshCw className="h-4 w-4" /> Reconnect</Button>
                <Button variant="outline" className="text-destructive" onClick={disconnect} disabled={busy} data-testid="abc-disconnect-button"><Unlink className="h-4 w-4" /> Disconnect</Button>
              </>
            )}
            <Button variant="outline" onClick={test} disabled={testing || (!status.has_client_secret && !status.is_mock)} data-testid="abc-test-button">
              {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <><PlugZap className="h-4 w-4" /> Test connection</>}
            </Button>
          </div>
          {testResult && (
            <div className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${testResult.ok ? "border-green-200 bg-green-50 text-green-700" : "border-red-200 bg-red-50 text-red-700"}`} data-testid="abc-test-result">
              {testResult.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
              {testResult.message}
            </div>
          )}
          {!status.has_client_id && <p className="text-sm text-amber-700" data-testid="abc-config-required">Configure your ABC Client ID and Client Secret below before connecting.</p>}

          {/* Redirect URI registration callout — the #1 cause of ABC's "redirect_uri must be a Login redirect URI" 400 */}
          {!connected && !status.is_mock && status.redirect_uri_effective && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900" data-testid="abc-redirect-callout">
              <div className="mb-1 flex items-center gap-1.5 font-medium"><AlertTriangle className="h-4 w-4" /> Before connecting: register this Redirect URI with ABC</div>
              <p className="text-amber-800">In your <span className="font-medium">ABC Developer Portal</span> application, add this <span className="font-medium">exact</span> value under <span className="font-medium">OAuth 2.0 Redirect URI(s)</span>. It must match byte-for-byte — same scheme (<span className="font-mono">http</span>), host (<span className="font-mono">127.0.0.1</span>, not <span className="font-mono">localhost</span>), port, path, and no trailing slash.</p>
              <div className="mt-2 flex items-center gap-2">
                <code className="flex-1 overflow-x-auto rounded border border-amber-200 bg-white px-3 py-2 font-mono text-xs text-slate-800" data-testid="abc-redirect-callout-value">{status.redirect_uri_effective}</code>
                <Button variant="outline" size="sm" onClick={() => copyRedirect(status.redirect_uri_effective)} data-testid="abc-copy-redirect-callout"><Copy className="h-4 w-4" /> Copy</Button>
              </div>
              <p className="mt-2 text-xs text-amber-700">If ABC still returns a 400 after saving, wait a moment and retry — or ask ABC API Support to confirm the portal value propagated to their Okta client.</p>
            </div>
          )}
        </Section>

        {/* Account & branch defaults */}
        {connected && (
          <Section title="ABC Supply Account" description="Select the default Ship-To account and branch used for pricing and ordering." testid="abc-account-card">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Default Ship-To</Label>
                <Select value={shipTo} onValueChange={setShipTo}>
                  <SelectTrigger data-testid="abc-shipto-select"><SelectValue placeholder="Select Ship-To account" /></SelectTrigger>
                  <SelectContent>
                    {accounts.map((a) => <SelectItem key={a.number} value={a.number}>{a.name} ({a.number})</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Default Branch</Label>
                <Select value={branch} onValueChange={setBranch} disabled={!shipTo}>
                  <SelectTrigger data-testid="abc-branch-select"><SelectValue placeholder="Select branch" /></SelectTrigger>
                  <SelectContent>
                    {branches.map((b) => <SelectItem key={b.number} value={b.number}>{b.name} ({b.number}){b.home_branch ? " · Home" : ""}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            {accounts.length > 0 && shipTo && (() => {
              const a = accounts.find((x) => x.number === shipTo);
              if (!a) return null;
              return (
                <div className="rounded-md border border-border bg-slate-50 px-4 py-3 text-sm text-slate-600" data-testid="abc-hierarchy">
                  <div><Building2 className="mr-1 inline h-4 w-4 text-slate-400" /> Sold-To: {a.sold_to_name || "—"} ({a.sold_to_number || "—"})</div>
                  <div className="ml-5">Bill-To: {a.bill_to_name || "—"} ({a.bill_to_number || "—"})</div>
                  <div className="ml-5">Ship-To: {a.name} ({a.number})</div>
                </div>
              );
            })()}
            <Button onClick={saveDefaults} disabled={busy} data-testid="abc-save-defaults"><Save className="h-4 w-4" /> Save defaults</Button>
          </Section>
        )}

        {/* Configuration */}
        <Section title="Configuration" description="ABC developer application credentials. The client secret is encrypted and never returned to the browser." testid="abc-config-card">
          <div className="space-y-1.5">
            <Label>Environment</Label>
            <Select value={environment} onValueChange={setEnvironment}>
              <SelectTrigger data-testid="abc-environment-select"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="sandbox">Sandbox</SelectItem>
                <SelectItem value="production">Production</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Client ID</Label>
            <Input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder={status.has_client_id ? (status.client_id_masked || "Configured") : "ABC application client id"} className="font-mono" data-testid="abc-client-id" />
          </div>
          <div className="space-y-1.5">
            <Label>Client Secret</Label>
            {status.has_client_secret && (
              <div className="mb-2 flex items-center justify-between rounded-md border border-border bg-slate-50 px-3 py-2">
                <span className="font-mono text-sm text-slate-600">•••••••• configured</span>
                <Button variant="ghost" size="sm" className="text-destructive" onClick={async () => { try { await api.delete("/integrations/abc/config/secret"); toast.success("Client secret removed"); load(); } catch (e) { toast.error(apiError(e)); } }} data-testid="abc-clear-secret"><Trash2 className="h-4 w-4" /> Remove</Button>
              </div>
            )}
            <div className="relative">
              <Input type={showSecret ? "text" : "password"} value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} placeholder={status.has_client_secret ? "Enter a new secret to replace" : "ABC application client secret"} className="pr-10 font-mono" data-testid="abc-client-secret" />
              <button type="button" onClick={() => setShowSecret((s) => !s)} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700" tabIndex={-1}>
                {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>OAuth Redirect URI</Label>
            <Input value={redirectUri} onChange={(e) => setRedirectUri(e.target.value)} placeholder={status.redirect_uri_effective} className="font-mono" data-testid="abc-redirect-uri" />
            <p className="flex items-center gap-1.5 text-xs text-slate-400">
              Register this exact URL with ABC. Effective: <span className="font-mono text-slate-600">{status.redirect_uri_effective}</span>
              <button type="button" onClick={() => copyRedirect(status.redirect_uri_effective)} className="inline-flex items-center gap-1 text-slate-500 hover:text-slate-800" data-testid="abc-copy-redirect-field"><Copy className="h-3.5 w-3.5" /> Copy</button>
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>Webhook Public URL</Label>
            <Input value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} placeholder="https://relay.roofspan.io/webhooks/abc/order" className="font-mono" data-testid="abc-webhook-url" />
            <p className="text-xs text-slate-400">Public RoofSpan Relay endpoint that receives ABC order notifications (used in a later phase).</p>
          </div>
          <Button onClick={saveConfig} disabled={busy} data-testid="abc-save-config">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Save className="h-4 w-4" /> Save configuration</>}</Button>
        </Section>
      </div>
    </div>
  );
}
