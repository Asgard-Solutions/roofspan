// Secure device pairing storage. The durable per-device credential lives ONLY in secure native
// storage (expo-secure-store) — never in plain storage, logs, or analytics.
import * as SecureStore from "expo-secure-store";

const CRED_KEY = "roofspan_device_credential"; // secret
const BIND_KEY = "roofspan_pairing"; // non-secret binding metadata

export async function savePairing(p) {
  await SecureStore.setItemAsync(CRED_KEY, p.device_credential);
  await SecureStore.setItemAsync(
    BIND_KEY,
    JSON.stringify({
      installation_id: p.installation_id,
      device_id: p.device_id,
      relay_endpoint: p.relay_endpoint,
      protocol_version: p.protocol_version,
      min_mobile_version: p.min_mobile_version,
    })
  );
}

export async function loadPairing() {
  const raw = await SecureStore.getItemAsync(BIND_KEY);
  if (!raw) return null;
  const cred = await SecureStore.getItemAsync(CRED_KEY);
  if (!cred) return null;
  return { ...JSON.parse(raw), device_credential: cred };
}

export async function clearPairing() {
  await SecureStore.deleteItemAsync(CRED_KEY);
  await SecureStore.deleteItemAsync(BIND_KEY);
}
