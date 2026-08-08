// Wires the pure queue core to device storage + network. Server acknowledgement is the ONLY
// thing that flips a mutation to 'synced'. Pending data is never deleted until acknowledged.
import NetInfo from "@react-native-community/netinfo";
import queue from "./queue";
import { send } from "./api";
import { enqueue, saveMutation, loadPending, loadAllMutations } from "./storage";

// Create + durably persist a field mutation, then attempt to sync immediately (best effort).
export async function queueMutation(spec) {
  const m = queue.makeMutation(spec);
  await enqueue(m);
  runSync().catch(() => {});
  return m;
}

let _running = false;

export async function runSync() {
  if (_running) return;
  _running = true;
  try {
    const net = await NetInfo.fetch();
    if (!net.isConnected) return; // stay offline; pending items remain safely stored
    const pending = await loadPending();
    if (pending.length === 0) return;
    const processed = await queue.processQueue(pending, send);
    for (const m of processed) await saveMutation(m); // persist new state (synced/conflict/failed/pending)
  } finally {
    _running = false;
  }
}

export async function pendingSummary() {
  const all = await loadAllMutations();
  const by = { pending: 0, failed: 0, conflict: 0, synced: 0 };
  for (const m of all) by[m.state] = (by[m.state] || 0) + 1;
  return { items: all, counts: by };
}

// Auto-sync when connectivity returns.
export function startAutoSync() {
  return NetInfo.addEventListener((state) => {
    if (state.isConnected) runSync().catch(() => {});
  });
}
