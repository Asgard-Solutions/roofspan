import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { UserPlus, KeyRound, Loader2, Smartphone } from "lucide-react";

const ROLE_OPTIONS = [
  { value: "owner", label: "Owner" },
  { value: "administrator", label: "Administrator" },
  { value: "office", label: "Office" },
  { value: "sales", label: "Sales" },
];

function roleBadge(role) {
  const sensitive = role === "owner" || role === "administrator";
  return (
    <Badge variant={sensitive ? "default" : "secondary"} data-testid="user-role-badge">
      {role.charAt(0).toUpperCase() + role.slice(1)}
    </Badge>
  );
}

function formatPairingCode(value) {
  const digits = String(value || "").replace(/\D/g, "").slice(0, 6);
  return digits.length > 3 ? `${digits.slice(0, 3)} ${digits.slice(3)}` : digits;
}

function PairingExpiry({ expiresAt }) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!expiresAt) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [expiresAt]);

  if (!expiresAt) return null;
  const deadline = new Date(expiresAt).getTime();
  if (!Number.isFinite(deadline)) return null;
  const remaining = Math.max(0, Math.ceil((deadline - now) / 1000));
  if (remaining <= 0) {
    return <p className="mt-2 text-xs font-medium text-red-600">Expired · generate a new code</p>;
  }
  const minutes = Math.floor(remaining / 60);
  const seconds = String(remaining % 60).padStart(2, "0");
  return <p className="mt-2 text-xs text-amber-700">Expires in {minutes}:{seconds} · single-use</p>;
}

export default function Users() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ email: "", full_name: "", password: "", role: "sales" });
  const [saving, setSaving] = useState(false);

  const [pwOpen, setPwOpen] = useState(false);
  const [pwTarget, setPwTarget] = useState(null);
  const [pwValue, setPwValue] = useState("");

  const [mobileOpen, setMobileOpen] = useState(false);
  const [mobileTarget, setMobileTarget] = useState(null);
  const [pairing, setPairing] = useState(null);
  const [devices, setDevices] = useState([]);
  const [mobileBusy, setMobileBusy] = useState(false);

  const openMobile = async (u) => {
    setMobileTarget(u);
    setPairing(null);
    setDevices([]);
    setMobileOpen(true);
    try {
      const r = await api.get(`/admin/users/${u.id}/mobile/devices`);
      setDevices(r.data.devices || []);
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const connectDevice = async () => {
    setMobileBusy(true);
    try {
      const r = await api.post(`/admin/users/${mobileTarget.id}/mobile/pair`);
      setPairing(r.data);
      const d = await api.get(`/admin/users/${mobileTarget.id}/mobile/devices`);
      setDevices(d.data.devices || []);
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setMobileBusy(false);
    }
  };

  const revokeDevice = async (id) => {
    try {
      await api.post(`/admin/mobile/devices/${id}/revoke`);
      toast.success("Device revoked");
      const d = await api.get(`/admin/users/${mobileTarget.id}/mobile/devices`);
      setDevices(d.data.devices || []);
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const load = useCallback(() => {
    setLoading(true);
    api.get("/users")
      .then((r) => setUsers(r.data))
      .catch((e) => toast.error(apiError(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const createUser = async () => {
    setSaving(true);
    try {
      await api.post("/users", form);
      toast.success("User created");
      setCreateOpen(false);
      setForm({ email: "", full_name: "", password: "", role: "sales" });
      load();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const updateUser = async (id, patch) => {
    try {
      await api.patch(`/users/${id}`, patch);
      toast.success("User updated");
      load();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const resetPassword = async () => {
    if (pwValue.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    try {
      await api.post(`/users/${pwTarget.id}/reset-password`, { new_password: pwValue });
      toast.success("Password reset");
      setPwOpen(false);
      setPwValue("");
      setPwTarget(null);
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  return (
    <div>
      <PageHeader
        title="Users"
        description="Create Office and Sales accounts and manage access."
        testid="page-users"
        actions={
          <Button onClick={() => setCreateOpen(true)} data-testid="add-user-button">
            <UserPlus className="h-4 w-4" /> Add user
          </Button>
        }
      />
      <div className="p-6 sm:p-8">
        <div className="overflow-x-auto rounded-md border border-border bg-white">
          <Table data-testid="users-table">
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => {
                const isSelf = u.id === me?.id;
                return (
                  <TableRow key={u.id} data-testid={`user-row-${u.email}`}>
                    <TableCell className="font-medium text-slate-900">{u.full_name || "—"}</TableCell>
                    <TableCell className="text-slate-600">{u.email}</TableCell>
                    <TableCell>
                      <Select value={u.role} onValueChange={(v) => updateUser(u.id, { role: v })}>
                        <SelectTrigger className="h-8 w-[150px]" data-testid={`role-select-${u.email}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {ROLE_OPTIONS.map((r) => (
                            <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell>
                      {u.is_active ? (
                        <span className="text-sm font-medium text-green-600">Active</span>
                      ) : (
                        <span className="text-sm font-medium text-slate-400">Disabled</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => { setPwTarget(u); setPwOpen(true); }}
                          data-testid={`reset-pw-${u.email}`}
                        >
                          <KeyRound className="h-3.5 w-3.5" /> Reset
                        </Button>
                        {u.role === "sales" && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => openMobile(u)}
                            data-testid={`mobile-access-${u.email}`}
                          >
                            <Smartphone className="h-3.5 w-3.5" /> Mobile
                          </Button>
                        )}
                        <Button
                          variant={u.is_active ? "outline" : "default"}
                          size="sm"
                          disabled={isSelf}
                          onClick={() => updateUser(u.id, { is_active: !u.is_active })}
                          data-testid={`toggle-active-${u.email}`}
                        >
                          {u.is_active ? "Disable" : "Enable"}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
              {users.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-sm text-slate-400">No users.</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent data-testid="create-user-dialog">
          <DialogHeader>
            <DialogTitle>Add user</DialogTitle>
            <DialogDescription>Create a new Office or Sales account.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label>Full name</Label>
              <Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} placeholder="Jane Roofer" data-testid="new-user-name" />
            </div>
            <div className="space-y-1.5">
              <Label>Email</Label>
              <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="jane@company.com" data-testid="new-user-email" />
            </div>
            <div className="space-y-1.5">
              <Label>Temporary password</Label>
              <Input type="text" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="At least 8 characters" data-testid="new-user-password" />
            </div>
            <div className="space-y-1.5">
              <Label>Role</Label>
              <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                <SelectTrigger data-testid="new-user-role"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {ROLE_OPTIONS.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={createUser} disabled={saving} data-testid="save-new-user">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create user"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={pwOpen} onOpenChange={setPwOpen}>
        <DialogContent data-testid="reset-password-dialog">
          <DialogHeader>
            <DialogTitle>Reset password</DialogTitle>
            <DialogDescription>{pwTarget?.email}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label>New password</Label>
            <Input type="text" value={pwValue} onChange={(e) => setPwValue(e.target.value)} placeholder="At least 8 characters" data-testid="reset-pw-input" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPwOpen(false)}>Cancel</Button>
            <Button onClick={resetPassword} data-testid="confirm-reset-pw">Set password</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        <DialogContent className="sm:max-w-[560px]" data-testid="mobile-access-dialog">
          <DialogHeader>
            <DialogTitle>Mobile Access</DialogTitle>
            <DialogDescription>{mobileTarget?.full_name || mobileTarget?.email}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {pairing ? (
              <div className="rounded-lg border border-border bg-slate-50 p-5 text-center" data-testid="pairing-code-box">
                {pairing.qr_code_data_url ? (
                  <div className="mx-auto mb-4 w-fit rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
                    <img
                      src={pairing.qr_code_data_url}
                      alt="RoofSpan Mobile pairing QR code"
                      className="h-56 w-56"
                      data-testid="pairing-qr-code"
                    />
                  </div>
                ) : (
                  <p className="mb-4 rounded-md bg-amber-50 p-3 text-sm text-amber-800" data-testid="pairing-qr-unavailable">
                    QR image is unavailable. Enter the pairing code in RoofSpan Mobile.
                  </p>
                )}
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Pairing code</p>
                <p className="my-1 text-3xl font-black tracking-widest text-slate-900" data-testid="pairing-numeric">
                  {formatPairingCode(pairing.numeric_code)}
                </p>
                <p className="text-xs leading-5 text-slate-500">
                  Scan the QR code in RoofSpan Mobile, or enter the six-digit code. This code is bound to {mobileTarget?.full_name || mobileTarget?.email}.
                </p>
                <PairingExpiry expiresAt={pairing.expires_at} />
              </div>
            ) : (
              <Button onClick={connectDevice} disabled={mobileBusy} className="w-full" data-testid="connect-mobile-device">
                {mobileBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Connect Mobile Device"}
              </Button>
            )}
            {pairing && (
              <Button variant="outline" onClick={connectDevice} disabled={mobileBusy} className="w-full" data-testid="regenerate-pairing">
                {mobileBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Generate new pairing code"}
              </Button>
            )}
            <div>
              <p className="mb-2 text-sm font-semibold text-slate-700">Devices</p>
              {devices.length === 0 ? (
                <p className="text-sm text-slate-400" data-testid="no-devices">No paired device yet.</p>
              ) : devices.map((d) => (
                <div key={d.id} className="flex items-center justify-between border-b border-border py-2" data-testid={`device-${d.id}`}>
                  <div>
                    <p className="text-sm font-medium text-slate-900">{d.label || "Mobile device"}</p>
                    <p className="text-xs text-slate-500">
                      {d.status === "ACTIVE" ? "Connected" : "Revoked"}
                      {d.last_seen_at ? ` · last seen ${new Date(d.last_seen_at).toLocaleString()}` : ""}
                    </p>
                  </div>
                  {d.status === "ACTIVE" && (
                    <Button variant="outline" size="sm" onClick={() => revokeDevice(d.id)} data-testid={`revoke-${d.id}`}>Revoke</Button>
                  )}
                </div>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMobileOpen(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
