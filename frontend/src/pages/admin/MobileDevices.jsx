import { useEffect, useState, useCallback } from "react";
import { QRCodeSVG } from "qrcode.react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Smartphone, RefreshCw, QrCode, Loader2, ShieldX } from "lucide-react";

const fmtCode = (c) => (c && c.length === 6 ? `${c.slice(0, 3)} ${c.slice(3)}` : c || "");
const fmtTime = (t) => (t ? new Date(t).toLocaleString() : "—");

function Countdown({ expiresAt }) {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    const tick = () => setLeft(Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);
  const m = Math.floor(left / 60), s = left % 60;
  return (
    <span data-testid="pairing-countdown" className={left <= 0 ? "text-destructive" : "text-slate-500"}>
      {left <= 0 ? "Expired" : `Expires in ${m}:${String(s).padStart(2, "0")}`}
    </span>
  );
}

export default function MobileDevices() {
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [pairing, setPairing] = useState(false);
  const [pair, setPair] = useState(null); // {numeric_code, expires_at, qr_payload, relay_endpoint}
  const [unavailable, setUnavailable] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/mobile/devices");
      setDevices(Array.isArray(data) ? data : (data.devices || []));
      setUnavailable(false);
    } catch (e) {
      setUnavailable(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    setPairing(true);
    try {
      const { data } = await api.post("/admin/mobile/pair");
      setPair(data);
      toast.success("Pairing code generated");
      load();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setPairing(false);
    }
  };

  const revoke = async (id) => {
    try {
      await api.post(`/admin/mobile/devices/${id}/revoke`);
      toast.success("Device revoked");
      load();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  return (
    <div>
      <PageHeader title="Mobile Devices" description="Pair and manage RoofSpan Mobile field devices" testid="page-mobile-devices" />
      <div className="space-y-6 p-6 sm:p-8">
        <div className="rounded-md border border-border bg-white p-6" data-testid="pairing-panel">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-orange-50">
                <QrCode className="h-5 w-5 text-orange-600" />
              </div>
              <div>
                <h2 className="font-heading text-base font-semibold text-slate-900">Pair a new device</h2>
                <p className="text-sm text-slate-500">Scan the QR code in the RoofSpan Mobile app, or enter the numeric code.</p>
              </div>
            </div>
            <Button onClick={generate} disabled={pairing} data-testid="generate-pairing-button">
              {pairing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Smartphone className="mr-2 h-4 w-4" />}
              Generate pairing code
            </Button>
          </div>

          {pair && (
            <div className="mt-6 flex flex-col items-start gap-6 sm:flex-row" data-testid="pairing-result">
              <div className="rounded-md border border-border bg-white p-3">
                <QRCodeSVG value={JSON.stringify(pair.qr_payload)} size={168} level="M" data-testid="pairing-qr" />
              </div>
              <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Numeric code</div>
                <div className="font-heading text-4xl font-bold tracking-widest text-slate-900" data-testid="pairing-code">
                  {fmtCode(pair.numeric_code)}
                </div>
                <div className="text-sm"><Countdown expiresAt={pair.expires_at} /></div>
                <p className="max-w-md text-xs text-slate-400">
                  This code is single-use and expires shortly. It contains no passwords or company data. Pairing does not sign the field user in — they still log in with their own RoofSpan account.
                </p>
              </div>
            </div>
          )}
        </div>

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-heading text-lg font-semibold text-slate-900">Paired devices</h2>
            <Button variant="outline" size="sm" onClick={load} disabled={loading} data-testid="refresh-devices-button">
              <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh
            </Button>
          </div>

          {unavailable ? (
            <div className="flex max-w-xl items-start gap-3 rounded-md border border-dashed border-border bg-white p-6" data-testid="devices-unavailable">
              <ShieldX className="mt-0.5 h-5 w-5 text-slate-400" />
              <p className="text-sm text-slate-500">RoofSpan can't reach the pairing service right now. Your local Office is unaffected — try Refresh in a moment.</p>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-md border border-border bg-white">
              <Table data-testid="devices-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Device</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Paired</TableHead>
                    <TableHead>Last seen</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {devices.length === 0 && (
                    <TableRow><TableCell colSpan={5} className="py-8 text-center text-sm text-slate-400">No devices paired yet.</TableCell></TableRow>
                  )}
                  {devices.map((d) => (
                    <TableRow key={d.id} data-testid={`device-row-${d.id}`}>
                      <TableCell className="font-medium text-slate-900">{d.label || `Device ${String(d.id).slice(0, 8)}`}</TableCell>
                      <TableCell>
                        <Badge variant={d.status === "ACTIVE" ? "default" : "secondary"} data-testid={`device-status-${d.id}`}>{d.status}</Badge>
                      </TableCell>
                      <TableCell className="text-slate-500">{fmtTime(d.paired_at)}</TableCell>
                      <TableCell className="text-slate-500">{fmtTime(d.last_seen_at)}</TableCell>
                      <TableCell className="text-right">
                        {d.status === "ACTIVE" ? (
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button variant="outline" size="sm" data-testid={`revoke-device-${d.id}`}>Revoke</Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>Revoke this device?</AlertDialogTitle>
                                <AlertDialogDescription>
                                  The device will lose access to your company's RoofSpan. Any saved offline work on the device is kept. It can be paired again later.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Cancel</AlertDialogCancel>
                                <AlertDialogAction onClick={() => revoke(d.id)} data-testid={`confirm-revoke-${d.id}`}>Revoke device</AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        ) : (
                          <span className="text-xs text-slate-400">Revoked</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
