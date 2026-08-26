// Pairing + connection gate for RoofSpan Mobile. Decides which screen the app shows:
// welcome/connect (unpaired) -> update-required / subscription-lock / device-revoked /
// server-unavailable / offline -> sign-in -> main app. Never deletes offline queued work.
import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import Constants from "expo-constants";
import NetInfo from "@react-native-community/netinfo";

import { clearPairing, loadPairing, savePairing } from "./pairingStore";
import { probeConnection, resolvePairing, checkVersion } from "./relay";
import { setActivePairing } from "./transport";
import { setInstallationScope } from "./storage";
import { runSync } from "./sync";
import { versionGate } from "./version";
import { STATES, mapRelayError } from "./connectionState";

const APP_VERSION = (Constants.expoConfig && Constants.expoConfig.version) || "1.0.0";
const Ctx = createContext(null);

export function PairingProvider({ children }) {
  const [ready, setReady] = useState(false);
  const [pairing, setPairing] = useState(null);
  const [conn, setConn] = useState(STATES.CONNECTING);
  const [optionalUpdate, setOptionalUpdate] = useState(false);

  const evaluate = useCallback(async (p) => {
    if (!p) return;
    setActivePairing(p);
    setInstallationScope(p.installation_id);

    const vp = await checkVersion(APP_VERSION);
    if (vp) {
      if (vp.status === "must_update") { setConn(STATES.UPDATE_REQUIRED); return; }
      setOptionalUpdate(vp.status === "update_available");
    } else if (versionGate(APP_VERSION, p.min_mobile_version, null) === "must_update") {
      setConn(STATES.UPDATE_REQUIRED);
      return;
    }

    try {
      const net = await NetInfo.fetch();
      if (net && net.isConnected === false) { setConn(STATES.OFFLINE); return; }
    } catch (e) { /* ignore */ }

    setConn(STATES.CONNECTING);
    const r = await probeConnection(p);
    setConn(r.ok ? STATES.CONNECTED : mapRelayError(r.code));
    if (r.ok) runSync().catch(() => {});
  }, []);

  useEffect(() => {
    (async () => {
      const p = await loadPairing();
      setPairing(p);
      setActivePairing(p);
      if (p) await evaluate(p);
      setReady(true);
    })();
  }, [evaluate]);

  const pair = useCallback(async ({ token, numeric_code }) => {
    const r = await resolvePairing({ token, numeric_code, label: "RoofSpan Mobile" });
    if (r.status >= 200 && r.status < 300 && r.data && r.data.device_credential) {
      const p = {
        installation_id: r.data.installation_id,
        device_id: r.data.device_id,
        device_credential: r.data.device_credential,
        relay_endpoint: r.data.relay_endpoint,
        protocol_version: r.data.protocol_version,
        min_mobile_version: r.data.min_mobile_version,
        expected_user_id: r.data.expected_user_id || null,
        expected_user_label: r.data.expected_user_label || null,
      };
      await savePairing(p);
      setPairing(p);
      setActivePairing(p);
      await evaluate(p);
      return { ok: true };
    }

    let code = "error";
    if (r.status === 0) code = "unreachable";
    else if (r.status === 404) code = "not_found";
    else if (r.status === 409) code = "used";
    else if (r.status === 410) code = "expired";
    else if (r.status === 503) code = "unavailable";
    return { ok: false, code };
  }, [evaluate]);

  // Full unpair: removes the device pairing credential (requires admin to pair again).
  const unpair = useCallback(async () => {
    await clearPairing();
    setPairing(null);
    setActivePairing(null);
    setConn(STATES.CONNECTING);
  }, []);

  const retry = useCallback(async () => { await evaluate(pairing); }, [evaluate, pairing]);

  return (
    <Ctx.Provider value={{
      ready, pairing, conn, optionalUpdate, setOptionalUpdate,
      isPaired: !!pairing, appVersion: APP_VERSION, pair, unpair, retry,
    }}>
      {children}
    </Ctx.Provider>
  );
}

export const usePairing = () => useContext(Ctx);
