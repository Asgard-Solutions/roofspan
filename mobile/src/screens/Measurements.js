import React, { useCallback, useMemo, useState, useEffect, useRef } from "react";
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, Alert, AppState } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { queueMutation, isSyncing, currentMeasurementMutation, currentMeasurementCreate, discardMeasurementUpdate, rebaseMeasurementUpdate } from "../sync";
import { cache, cacheMeasurementDetail, loadMeasurementDraft, saveMeasurementDraft, clearMeasurementDraft, saveMeasurementWorkingDraft, loadMeasurementWorkingDraft, clearMeasurementWorkingDraft } from "../cache";
import { getCache } from "../storage";
import { resolveMeasurementView } from "../measurementReconcile";
import { C } from "../theme";
import PhotoSection from "../components/PhotoSection";

const measurementKeys = require("../measurementCache");
const queueCore = require("../queue");
const { edgeForEdit, newEdge, edgeToBody } = require("../measurementEdges");

const STRUCTURE_TYPES = [
  ["main_house", "Main"], ["attached_garage", "Att. Garage"], ["detached_garage", "Det. Garage"],
  ["porch", "Porch"], ["addition", "Addition"], ["shed", "Shed"], ["other", "Other"],
];
const PITCHES = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12];
const EDGE_TYPES = [
  ["eave", "Eave"], ["rake", "Rake"], ["ridge", "Ridge"], ["hip", "Hip"], ["valley", "Valley"],
  ["sidewall", "Sidewall"], ["headwall", "Headwall"], ["transition", "Transition"],
];
const PEN_TYPES = [
  ["pipe_boot", "Pipe boots"], ["static_vent", "Static vents"], ["skylight", "Skylights"],
  ["turbine", "Turbines"], ["powered_vent", "Powered vents"], ["exhaust_vent", "Exhaust vents"],
  ["chimney", "Chimneys"], ["satellite", "Satellite dishes"], ["other", "Other"],
];
const uid = () => "r" + Math.random().toString(36).slice(2, 10);
const numberOrNull = (v) => (v === "" || v == null ? null : (Number.isFinite(Number(v)) ? Number(v) : null));

function initialPenetrations() {
  return PEN_TYPES.map(([t]) => {
    const ref = uid();
    return { _k: ref, ref, pen_type: t, quantity: 0, facet_ref: "" };
  });
}

function penForEdit(row) {
  const ref = row.ref || row.id || row._k || uid();
  return { ...row, ref, _k: row._k || row.id || ref, facet_ref: row.facet_ref || row.facet_id || "" };
}

export default function Measurements({ route, navigation }) {
  const { lead_id, property_id, inspection_id } = route.params || {};
  const scope = useMemo(() => lead_id ? { lead_id } : (property_id ? { property_id } : { inspection_id }), [lead_id, property_id, inspection_id]);
  const [existing, setExisting] = useState(null);
  const [localDraft, setLocalDraft] = useState(null);
  const [structures, setStructures] = useState([]);
  const [facets, setFacets] = useState([]);
  const [edges, setEdges] = useState([]);
  const [pens, setPens] = useState(initialPenetrations());
  const [summary, setSummary] = useState({});
  const [readonly, setReadonly] = useState(false);
  const [usingCached, setUsingCached] = useState(false);
  const [cachedAt, setCachedAt] = useState(null);
  const [syncStatus, setSyncStatus] = useState(null);   // Saved on device / Waiting to sync / Syncing / Synced / Needs review
  const [conflict, setConflict] = useState(null);       // { serverDetail } when Office changed the same revision
  const [showGutters, setShowGutters] = useState(false);

  const autosaveTimer = useRef(null);
  const savedGuard = useRef(false);        // #13: set at Save so a late autosave can't resurrect a stale draft
  const baselineRef = useRef("");          // JSON of the last hydrated form — autosave only fires on real edits
  const captureBaseline = useRef(false);   // set on hydrate so the first effect pass captures, never persists

  const formJson = useCallback(
    () => JSON.stringify({ structures, facets, edges, pens, summary }),
    [structures, facets, edges, pens, summary],
  );
  // Persist the in-progress working draft locally (debounced) so entries survive background/restart BEFORE Save.
  const persistWorking = useCallback(async () => {
    if (readonly || savedGuard.current) return true;   // #13: never re-create a working draft after Save
    return await saveMeasurementWorkingDraft(scope, {
      working: true, base: existing ? { ...existing } : null,
      local_client_id: localDraft ? localDraft.client_id : null,
      structures, facets, edges, pens, summary, updated_at: new Date().toISOString(),
    });
  }, [scope, readonly, existing, localDraft, structures, facets, edges, pens, summary]);

  // Always-latest flush closure; runs on unmount (navigate away / tap Back) so entries never depend on
  // the 700 ms timer having elapsed.
  const flushRef = useRef(() => {});
  flushRef.current = () => { if (!readonly && formJson() !== baselineRef.current) persistWorking(); };
  useEffect(() => () => { if (autosaveTimer.current) clearTimeout(autosaveTimer.current); flushRef.current(); }, []);

  const hydrateWorking = useCallback((wd) => {
    captureBaseline.current = true;
    setExisting(wd.base || null);
    setLocalDraft(wd.base ? null : (wd.local_client_id ? { local_draft: true, client_id: wd.local_client_id } : null));
    setReadonly(wd.base ? !wd.base.editable : false);
    setStructures(wd.structures || []);
    setFacets(wd.facets || []);
    setEdges((wd.edges || []).map((e) => ({ ...e })));
    setPens(wd.pens && wd.pens.length ? wd.pens : initialPenetrations());
    setSummary(wd.summary || {});
    setUsingCached(false); setCachedAt(null);
  }, []);

  const hydrate = useCallback((full, stale = false, cached = null) => {
    if (!full) return;
    captureBaseline.current = true;
    if (measurementKeys.isLocalDraft(full)) {
      const body = full.body || {};
      setExisting(null);
      setLocalDraft(full);
      setReadonly(false);
      setStructures((body.structures || []).map((row) => ({ ...row, ref: row.ref || row.id || uid(), included_in_scope: row.included_in_scope !== false })));
      setFacets((body.facets || []).map((row) => ({ ...row, ref: row.ref || row.id || uid(), structure_ref: row.structure_ref || row.structure_id || "" })));
      setEdges((body.edges || []).map(edgeForEdit));
      const loadedPens = (body.penetrations || []).map(penForEdit);
      const present = new Set(loadedPens.map((p) => p.pen_type));
      setPens([...loadedPens, ...initialPenetrations().filter((p) => !present.has(p.pen_type))]);
      setSummary(body.summary || {});
    } else {
      setLocalDraft(null);
      setExisting({
        id: full.id, if_match: full.updated_at, status: full.status, editable: full.editable,
        source: full.source || "field", revision_number: full.revision_number,
        provider: full.provider ?? null, report_id: full.report_id ?? null,
        reported_area_sqft: full.reported_area_sqft ?? null, notes: full.notes ?? null,
      });
      setReadonly(!full.editable);
      setStructures((full.structures || []).map((row) => ({ ...row, ref: row.id || row.ref || uid(), included_in_scope: row.included_in_scope !== false })));
      setFacets((full.facets || []).map((row) => ({ ...row, ref: row.id || row.ref || uid(), structure_ref: row.structure_id || row.structure_ref || "" })));
      setEdges((full.edges || []).map(edgeForEdit));
      const loadedPens = (full.penetrations || []).map(penForEdit);
      const present = new Set(loadedPens.map((p) => p.pen_type));
      setPens([...loadedPens, ...initialPenetrations().filter((p) => !present.has(p.pen_type))]);
      setSummary(full.summary || {});
    }
    setUsingCached(!!stale);
    setCachedAt(cached || null);
  }, []);

  const load = useCallback(async () => {
    // Highest priority: the salesperson's in-progress working draft (unsaved edits) always wins so nothing
    // typed before Save is lost across navigate/background/restart.
    const wd = await loadMeasurementWorkingDraft(scope);
    if (wd && wd.working) {
      hydrateWorking(wd);
      const pend = wd.base ? await currentMeasurementMutation(wd.base.id) : (wd.local_client_id ? await currentMeasurementCreate(wd.local_client_id) : null);
      const pendingActive = pend && (pend.state === "pending" || pend.state === "failed");
      setSyncStatus(pendingActive ? (isSyncing() ? "Syncing" : "Waiting to sync") : "Saved on device");
      setConflict(null);
      return;
    }
    const draft = await loadMeasurementDraft(scope);
    const listResult = await cache.measurements(scope);
    const head = measurementKeys.pickCurrent(listResult.data || []);
    const pendingCreate = draft ? await currentMeasurementCreate(draft.client_id) : null;

    if (head) {
      // Capture the durable local optimistic detail BEFORE the read-through can overwrite it.
      let optimistic = null;
      try { optimistic = await getCache(measurementKeys.detailKey(head.id)); } catch (e) { /* best effort */ }
      const pu = await currentMeasurementMutation(head.id);
      const pendingUpdate = pu && (pu.state === "pending" || pu.state === "failed") ? pu : null;
      const detailResult = await cache.measurement(head.id);

      const view = resolveMeasurementView({
        serverDetail: detailResult.data, serverStale: listResult.stale || detailResult.stale,
        optimistic, draft: (pendingCreate && draft) ? draft : null,
        pendingUpdate, pendingCreate, isSyncing: isSyncing(),
      });

      if (view.detail) {
        // Local work wins → restore it into the cache the read-through just clobbered (durability).
        if (view.kind === "local_update" || view.kind === "conflict") await cacheMeasurementDetail(view.detail);
        hydrate(view.detail, view.kind === "server_cached", detailResult.cachedAt || listResult.cachedAt);
        setSyncStatus(view.status);
        setConflict(view.conflict ? { serverDetail: view.serverDetail, revisionId: head.id } : null);
        // Clear the local draft ONLY when the authoritative server copy is showing and nothing is pending.
        if (view.kind === "server" && !pendingCreate) await clearMeasurementDraft(scope);
        return;
      }
    }

    if (draft) {
      hydrate(draft, true, draft.updated_at);
      setSyncStatus(isSyncing() ? "Syncing" : "Waiting to sync");
      setConflict(null);
      return;
    }
    setExisting(null);
    setLocalDraft(null);
    setStructures([]);
    setFacets([]);
    setEdges([]);
    setPens(initialPenetrations());
    setSummary({});
    setReadonly(false);
    setUsingCached(!!listResult.stale);
    setCachedAt(listResult.cachedAt || null);
    setSyncStatus(null);
    setConflict(null);
  }, [scope, hydrate]);

  // Autosave the working draft as the salesperson edits — debounced, local only (no network per keystroke).
  useEffect(() => {
    if (readonly) return;
    const cur = formJson();
    if (captureBaseline.current) { baselineRef.current = cur; captureBaseline.current = false; return; }
    if (cur === baselineRef.current) {
      // All edits reverted to the authoritative baseline — clear any stale working draft so an older
      // autosaved value can never resurrect after a restart.
      if (autosaveTimer.current) { clearTimeout(autosaveTimer.current); autosaveTimer.current = null; }
      clearMeasurementWorkingDraft(scope);
      return;
    }
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(async () => {
      autosaveTimer.current = null;
      const okSave = await persistWorking();
      // Only claim "Saved on device" after the durable local write actually succeeded.
      setSyncStatus((s) => (s === "Waiting to sync" || s === "Syncing" || s === "Needs review") ? s : (okSave ? "Saved on device" : "Local save failed — retry"));
    }, 700);
    return () => {};
  }, [structures, facets, edges, pens, summary, readonly, formJson, persistWorking, scope]);

  // Flush the working draft immediately when RoofSpan backgrounds so nothing in-flight is lost.
  useEffect(() => {
    const sub = AppState.addEventListener("change", (next) => {
      if (next === "background" || next === "inactive") {
        if (autosaveTimer.current) { clearTimeout(autosaveTimer.current); autosaveTimer.current = null; }
        if (!readonly && formJson() !== baselineRef.current) persistWorking();
      }
    });
    return () => { try { sub && sub.remove && sub.remove(); } catch (e) {} };
  }, [readonly, formJson, persistWorking]);

  const onUseOffice = useCallback(async () => {
    if (!conflict) return;
    await discardMeasurementUpdate(conflict.revisionId);
    if (conflict.serverDetail) await cacheMeasurementDetail(conflict.serverDetail);
    setConflict(null);
    await load();
  }, [conflict, load]);

  const onKeepMine = useCallback(async () => {
    if (!conflict || !conflict.serverDetail) return;
    await rebaseMeasurementUpdate(conflict.revisionId, conflict.serverDetail.updated_at);
    setConflict(null);
    await load();
  }, [conflict, load]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const totals = useMemo(() => {
    const scopedRefs = new Set(structures.filter((st) => st.included_in_scope !== false).map((st) => st.ref));
    const area = facets.reduce((sum, f) => sum + (parseFloat(f.area_sqft) || 0), 0);
    const takeoffArea = facets.reduce((sum, f) => {
      const included = !f.structure_ref || scopedRefs.has(f.structure_ref);
      return sum + (included ? (parseFloat(f.area_sqft) || 0) : 0);
    }, 0);
    const edge = {};
    edges.forEach((e) => { edge[e.edge_type] = (edge[e.edge_type] || 0) + (parseFloat(e.length_ft) || 0); });
    const pen = pens.reduce((sum, p) => sum + (parseInt(p.quantity) || 0), 0);
    return { area, takeoffArea, squares: area / 100, takeoffSquares: takeoffArea / 100, edge, pen };
  }, [structures, facets, edges, pens]);

  const addStructure = () => setStructures((a) => [...a, { ref: uid(), name: "", structure_type: "main_house", included_in_scope: true }]);
  const addFacet = () => setFacets((a) => [...a, { ref: uid(), facet_label: `F${a.length + 1}`, pitch_rise: 6, area_sqft: "", structure_ref: "" }]);
  const addEdge = () => setEdges((a) => [...a, newEdge()]);
  const setS = (i, k, v) => setStructures((a) => a.map((x, idx) => idx === i ? { ...x, [k]: v } : x));
  const setF = (i, k, v) => setFacets((a) => a.map((x, idx) => idx === i ? { ...x, [k]: v } : x));
  const setE = (i, k, v) => setEdges((a) => a.map((x, idx) => {
    if (idx !== i) return x;
    const nx = { ...x, [k]: v };
    nx.length_ft = (parseFloat(nx.ft) || 0) + (parseFloat(nx.in) || 0) / 12;
    return nx;
  }));
  const setP = (i, k, v) => setPens((a) => a.map((x, idx) => idx === i ? { ...x, [k]: v } : x));
  const bumpPen = (i, d) => setPens((a) => a.map((x, idx) => idx === i ? { ...x, quantity: Math.max(0, (parseInt(x.quantity) || 0) + d) } : x));

  const buildBody = (markComplete) => ({
    ...scope,
    source: existing?.source || "field",
    mark_field_complete: !!markComplete,
    // Preserve system/import metadata the salesperson doesn't edit — omitting it makes the backend
    // full-document replace ERASE it (rev.provider/report_id/reported_area_sqft/notes = payload value).
    provider: existing?.provider ?? (localDraft?.body?.provider ?? null),
    report_id: existing?.report_id ?? (localDraft?.body?.report_id ?? null),
    reported_area_sqft: existing?.reported_area_sqft ?? (localDraft?.body?.reported_area_sqft ?? null),
    notes: existing?.notes ?? (localDraft?.body?.notes ?? null),
    structures: structures.map((st, i) => ({
      ref: st.ref, name: st.name || "", structure_type: st.structure_type || "main_house",
      included_in_scope: st.included_in_scope !== false,
      stories: numberOrNull(st.stories), approx_height_ft: numberOrNull(st.approx_height_ft),
      attachment: st.attachment || null, notes: st.notes || null, sort: i,
    })),
    facets: facets.map((f, i) => ({
      ref: f.ref, structure_ref: f.structure_ref || null, facet_label: f.facet_label || `F${i + 1}`,
      pitch_rise: numberOrNull(f.pitch_rise), area_sqft: parseFloat(f.area_sqft) || 0,
      width_ft: numberOrNull(f.width_ft), length_ft: numberOrNull(f.length_ft),
      // Preserve technical values Field never shows (sketch/office/import geometry) — never erase them.
      orientation_azimuth: f.orientation_azimuth != null ? f.orientation_azimuth : null,
      geometry: f.geometry != null ? f.geometry : null,
      roof_material: f.roof_material || null, notes: f.notes || null, sort: i,
    })),
    edges: edges.map(edgeToBody),
    penetrations: pens.filter((p) => (parseInt(p.quantity) || 0) > 0).map((p, i) => ({
      ref: p.ref || p.id || p._k, pen_type: p.pen_type, quantity: parseInt(p.quantity) || 1, facet_ref: p.facet_ref || null,
      diameter_in: numberOrNull(p.diameter_in), width_in: numberOrNull(p.width_in), length_in: numberOrNull(p.length_in),
      notes: p.notes || null, sort: i,
    })),
    summary,
  });

  const save = async (markComplete) => {
    if (readonly) {
      Alert.alert("Locked", "This measurement is verified/locked. Ask the office to return it to the field to edit.");
      return;
    }
    const body = buildBody(markComplete);
    if (existing) {
      const optimistic = {
        id: existing.id, updated_at: existing.if_match, status: markComplete ? "field_complete" : existing.status,
        editable: true, source: existing.source, revision_number: existing.revision_number,
        // Carry ALL preserved revision metadata so a second save-before-sync (which reads this optimistic
        // copy back through hydrate) never turns hidden/system values into null.
        provider: body.provider, report_id: body.report_id, reported_area_sqft: body.reported_area_sqft, notes: body.notes,
        structures: body.structures, facets: body.facets, edges: body.edges, penetrations: body.penetrations, summary: body.summary,
      };
      await cacheMeasurementDetail(optimistic);
      await queueMutation({
        kind: "measurement_update", method: "put", path: `/mobile/measurements/${existing.id}`,
        body, ifMatch: existing.if_match, label: "Roof measurement",
      });
    } else {
      const draft = localDraft
        ? measurementKeys.mergeDraft(localDraft, body)
        : measurementKeys.makeDraft(scope, body, queueCore.uuidv4());
      setLocalDraft(draft);
      await saveMeasurementDraft(scope, draft);
      await queueMutation({
        kind: "measurement", method: "post", path: "/mobile/measurements", body,
        label: "Roof measurement", clientId: draft.client_id,
      });
    }
    if (autosaveTimer.current) { clearTimeout(autosaveTimer.current); autosaveTimer.current = null; }
    savedGuard.current = true;   // #13: block any in-flight/late autosave from recreating the working draft
    await clearMeasurementWorkingDraft(scope);
    baselineRef.current = formJson();
    Alert.alert("Saved", markComplete ? "Measurement marked Field Complete and queued to sync." : "Measurement saved and queued to sync.");
    navigation.goBack();
  };

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ paddingBottom: 60 }}>
      <Text style={s.h}>Roof measurements</Text>
      {existing && <Text style={s.status} testID="meas-status">Revision {existing.revision_number || ""} · {String(existing.status || "draft").replace("_", " ")}{readonly ? " · locked" : ""}</Text>}
      {!existing && localDraft && <Text style={s.status}>Local draft · waiting to sync</Text>}
      {syncStatus && <View style={[s.syncPill, syncStatus === "Needs review" ? s.syncWarn : (syncStatus === "Synced" ? s.syncOk : s.syncPend)]}><Text style={s.syncPillT} testID="meas-sync-status">{syncStatus}</Text></View>}
      {conflict && (
        <View style={s.conflict} testID="meas-conflict-banner">
          <Text style={s.conflictT}>Measurement changed in Office</Text>
          <Text style={s.conflictSub}>Your unsynced changes are safe. Choose which version to keep.</Text>
          <View style={s.rowline}>
            <TouchableOpacity style={s.conflictBtn} onPress={onKeepMine} testID="meas-keep-mine"><Text style={s.conflictBtnT}>Keep my changes</Text></TouchableOpacity>
            <TouchableOpacity style={[s.conflictBtn, s.conflictBtnAlt]} onPress={onUseOffice} testID="meas-use-office"><Text style={[s.conflictBtnT, { color: C.brand }]}>Use Office version</Text></TouchableOpacity>
          </View>
        </View>
      )}
      {usingCached && <View style={s.offline}><Text style={s.offlineT}>Offline/cached measurement{cachedAt ? ` · saved ${new Date(cachedAt).toLocaleString()}` : ""}</Text></View>}

      <View style={s.totals} testID="meas-totals">
        <Totm label="Area" value={`${totals.area.toFixed(0)} sf`} />
        <Totm label="Squares" value={totals.squares.toFixed(2)} />
        <Totm label="Takeoff" value={totals.takeoffSquares.toFixed(2)} />
        <Totm label="Penetr." value={totals.pen} />
      </View>

      <Section title="Structures" onAdd={!readonly && addStructure} addTestID="meas-add-structure">
        {structures.map((st, i) => (
          <View key={st.ref} style={s.card} testID={`meas-structure-${i}`}>
            <TextInput style={s.input} placeholder="Name (e.g. Main House)" value={st.name || ""} editable={!readonly} onChangeText={(v) => setS(i, "name", v)} />
            <View style={s.chips}>{STRUCTURE_TYPES.map(([v, l]) => <Chip key={v} label={l} active={st.structure_type === v} disabled={readonly} onPress={() => setS(i, "structure_type", v)} />)}</View>
            <View style={s.chips}>
              <Chip label={st.included_in_scope !== false ? "Included in estimate" : "Excluded from estimate"} active={st.included_in_scope !== false} disabled={readonly} onPress={() => setS(i, "included_in_scope", st.included_in_scope === false)} />
              <Chip label="Attached" active={st.attachment === "attached"} disabled={readonly} onPress={() => setS(i, "attachment", st.attachment === "attached" ? null : "attached")} />
              <Chip label="Detached" active={st.attachment === "detached"} disabled={readonly} onPress={() => setS(i, "attachment", st.attachment === "detached" ? null : "detached")} />
            </View>
            <View style={s.rowline}>
              <TextInput style={[s.input, s.half]} keyboardType="numeric" placeholder="Stories" value={st.stories != null ? String(st.stories) : ""} editable={!readonly} onChangeText={(v) => setS(i, "stories", v)} />
              <TextInput style={[s.input, s.half, s.leftGap]} keyboardType="numeric" placeholder="Height ft" value={st.approx_height_ft != null ? String(st.approx_height_ft) : ""} editable={!readonly} onChangeText={(v) => setS(i, "approx_height_ft", v)} />
            </View>
            <TextInput style={s.input} placeholder="Structure notes" value={st.notes || ""} editable={!readonly} onChangeText={(v) => setS(i, "notes", v)} />
            {existing?.id && st.id ? (
              <TouchableOpacity testID={`sketch-roof-${i}`} style={s.sketchBtn} onPress={() => navigation.navigate("RoofSketch", { revision_id: existing.id, structure_id: st.id, structure_name: st.name || "Roof", editable: !readonly })}>
                <Text style={s.sketchBtnText}>{st.has_sketch ? "Edit Roof Sketch" : "Sketch Roof"}</Text>
              </TouchableOpacity>
            ) : (
              <Text style={s.sketchHint} testID={`sketch-roof-disabled-${i}`}>Save the measurement first to create this structure before sketching the roof.</Text>
            )}
          </View>
        ))}
      </Section>

      <Section title="Roof planes" onAdd={!readonly && addFacet} addTestID="meas-add-facet">
        {facets.map((f, i) => (
          <View key={f.ref} style={s.card} testID={`meas-facet-${i}`}>
            <View style={s.rowline}>
              <TextInput style={[s.input, { width: 70 }]} value={f.facet_label || ""} editable={!readonly} onChangeText={(v) => setF(i, "facet_label", v)} />
              <TextInput style={[s.input, { flex: 1, marginLeft: 8 }]} keyboardType="numeric" placeholder="Area sq ft" value={String(f.area_sqft ?? "")} editable={!readonly} onChangeText={(v) => setF(i, "area_sqft", v)} />
            </View>
            <Text style={s.small}>Pitch (x/12)</Text>
            <View style={s.chips}>{PITCHES.map((p) => <Chip key={p} label={`${p}`} active={Number(f.pitch_rise) === p} disabled={readonly} onPress={() => setF(i, "pitch_rise", p)} />)}</View>
            {!!structures.length && <><Text style={s.small}>Structure</Text><View style={s.chips}>{structures.map((st) => <Chip key={st.ref} label={st.name || "Structure"} active={f.structure_ref === st.ref} disabled={readonly} onPress={() => setF(i, "structure_ref", st.ref)} />)}</View></>}
            <View style={s.rowline}>
              <TextInput style={[s.input, s.half]} keyboardType="numeric" placeholder="Width ft" value={f.width_ft != null ? String(f.width_ft) : ""} editable={!readonly} onChangeText={(v) => setF(i, "width_ft", v)} />
              <TextInput style={[s.input, s.half, s.leftGap]} keyboardType="numeric" placeholder="Length ft" value={f.length_ft != null ? String(f.length_ft) : ""} editable={!readonly} onChangeText={(v) => setF(i, "length_ft", v)} />
            </View>
            <TextInput style={s.input} placeholder="Roof material" value={f.roof_material || ""} editable={!readonly} onChangeText={(v) => setF(i, "roof_material", v)} />
            <TextInput style={s.input} placeholder="Facet notes" value={f.notes || ""} editable={!readonly} onChangeText={(v) => setF(i, "notes", v)} />
            {f.id ? <View style={s.photoBox}><Text style={s.small}>Facet photos</Text><PhotoSection recordType="measurement_facet" recordId={f.id} /></View> : null}
          </View>
        ))}
      </Section>

      <Section title="Roof lines (ft / in)" onAdd={!readonly && addEdge} addTestID="meas-add-edge">
        {edges.map((e, i) => (
          <View key={e._k} style={s.card} testID={`meas-edge-${i}`}>
            <View style={s.chips}>{EDGE_TYPES.map(([v, l]) => <Chip key={v} label={l} active={e.edge_type === v} disabled={readonly} onPress={() => setE(i, "edge_type", v)} />)}</View>
            <View style={s.rowline}>
              <TextInput style={[s.input, { width: 90 }]} keyboardType="numeric" placeholder="ft" value={String(e.ft ?? "")} editable={!readonly} onChangeText={(v) => setE(i, "ft", v)} />
              <TextInput style={[s.input, { width: 90, marginLeft: 8 }]} keyboardType="numeric" placeholder="in" value={String(e.in ?? "")} editable={!readonly} onChangeText={(v) => setE(i, "in", v)} />
              <Text style={[s.small, { marginLeft: 10, alignSelf: "center" }]}>{(parseFloat(e.length_ft) || 0).toFixed(1)} LF</Text>
            </View>
            {!!facets.length && <><Text style={s.small}>Primary roof plane</Text><View style={s.chips}>{facets.map((f) => <Chip key={f.ref} label={f.facet_label || "Plane"} active={e.facet_ref === f.ref} disabled={readonly} onPress={() => setE(i, "facet_ref", e.facet_ref === f.ref ? "" : f.ref)} />)}</View>
              <Text style={s.small}>Secondary roof plane (valley/ridge)</Text><View style={s.chips}>{facets.map((f) => <Chip key={f.ref} label={f.facet_label || "Plane"} active={e.facet_ref_secondary === f.ref} disabled={readonly} onPress={() => setE(i, "facet_ref_secondary", e.facet_ref_secondary === f.ref ? "" : f.ref)} />)}</View></>}
            <TextInput style={s.input} placeholder="Label (optional)" value={e.label || ""} editable={!readonly} onChangeText={(v) => setE(i, "label", v)} />
            <TextInput style={s.input} placeholder="Line notes (optional)" value={e.notes || ""} editable={!readonly} onChangeText={(v) => setE(i, "notes", v)} />
          </View>
        ))}
      </Section>

      <Section title="Penetrations">
        {pens.map((p, i) => (
          <View key={p._k} style={s.card} testID={`meas-pen-${p.pen_type}-${i}`}>
            <View style={s.penTop}>
              <Text style={s.penLabel}>{PEN_TYPES.find((t) => t[0] === p.pen_type)?.[1] || p.pen_type}</Text>
              <View style={s.counter}>
                <TouchableOpacity style={s.cbtn} disabled={readonly} onPress={() => bumpPen(i, -1)}><Text style={s.cbtnT}>−</Text></TouchableOpacity>
                <Text style={s.count}>{p.quantity || 0}</Text>
                <TouchableOpacity style={s.cbtn} disabled={readonly} onPress={() => bumpPen(i, 1)}><Text style={s.cbtnT}>+</Text></TouchableOpacity>
              </View>
            </View>
            {(parseInt(p.quantity) || 0) > 0 && <>
              {!!facets.length && <><Text style={s.small}>Roof plane</Text><View style={s.chips}>{facets.map((f) => <Chip key={f.ref} label={f.facet_label || "Plane"} active={p.facet_ref === f.ref} disabled={readonly} onPress={() => setP(i, "facet_ref", f.ref)} />)}</View></>}
              <View style={s.rowline}>
                <TextInput style={[s.input, { flex: 1 }]} keyboardType="numeric" placeholder="Diameter in" value={p.diameter_in != null ? String(p.diameter_in) : ""} editable={!readonly} onChangeText={(v) => setP(i, "diameter_in", v)} />
                <TextInput style={[s.input, { flex: 1, marginLeft: 6 }]} keyboardType="numeric" placeholder="Width in" value={p.width_in != null ? String(p.width_in) : ""} editable={!readonly} onChangeText={(v) => setP(i, "width_in", v)} />
                <TextInput style={[s.input, { flex: 1, marginLeft: 6 }]} keyboardType="numeric" placeholder="Length in" value={p.length_in != null ? String(p.length_in) : ""} editable={!readonly} onChangeText={(v) => setP(i, "length_in", v)} />
              </View>
              <TextInput style={s.input} placeholder="Penetration notes" value={p.notes || ""} editable={!readonly} onChangeText={(v) => setP(i, "notes", v)} />
              {p.id ? <PhotoSection recordType="measurement_penetration" recordId={p.id} /> : null}
            </>}
          </View>
        ))}
      </Section>

      <Section title="Existing roof, decking & conditions">
        <View style={s.card}>
          <TextInput style={s.input} placeholder="Existing covering (e.g. architectural shingle)" value={summary.existing_covering_type || ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, existing_covering_type: v }))} />
          <TextInput style={s.input} placeholder="Existing roof condition" value={summary.existing_condition || ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, existing_condition: v }))} />
          <TextInput style={s.input} placeholder="Existing underlayment" value={summary.existing_underlayment || ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, existing_underlayment: v }))} />
          <View style={s.rowline}>
            <TextInput style={[s.input, s.half]} keyboardType="numeric" placeholder="Layers" value={summary.existing_layers != null ? String(summary.existing_layers) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, existing_layers: numberOrNull(v) }))} />
            <TextInput style={[s.input, s.half, s.leftGap]} placeholder="Deck type" value={summary.deck_type || ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, deck_type: v }))} />
          </View>
          <View style={s.rowline}>
            <TextInput style={[s.input, s.half]} keyboardType="numeric" placeholder="Damaged deck SF" value={summary.damaged_deck_sf != null ? String(summary.damaged_deck_sf) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, damaged_deck_sf: numberOrNull(v) }))} />
            <TextInput style={[s.input, s.half, s.leftGap]} keyboardType="numeric" placeholder="Replacement sheets" value={summary.replacement_sheets != null ? String(summary.replacement_sheets) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, replacement_sheets: numberOrNull(v) }))} />
          </View>
          <View style={s.rowline}>
            <TextInput style={[s.input, s.half]} keyboardType="numeric" placeholder="Measured drip edge LF" value={summary.drip_edge_lf != null ? String(summary.drip_edge_lf) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, drip_edge_lf: numberOrNull(v) }))} />
            <TextInput style={[s.input, s.half, s.leftGap]} keyboardType="numeric" placeholder="Ridge vent LF" value={summary.ridge_vent_lf != null ? String(summary.ridge_vent_lf) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, ridge_vent_lf: numberOrNull(v) }))} />
          </View>
          <View style={s.rowline}>
            <TextInput style={[s.input, s.half]} keyboardType="numeric" placeholder="Deck thickness in" value={summary.deck_thickness_in != null ? String(summary.deck_thickness_in) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, deck_thickness_in: numberOrNull(v) }))} />
            <TextInput style={[s.input, s.half, s.leftGap]} keyboardType="numeric" placeholder="Soffit intake LF" value={summary.intake_soffit_vent_lf != null ? String(summary.intake_soffit_vent_lf) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, intake_soffit_vent_lf: numberOrNull(v) }))} />
          </View>
          <View style={s.chips}>
            {[["full_redeck", "Full re-deck"], ["steep_access", "Steep access"], ["high_access", "High access"], ["restricted_access", "Restricted"], ["long_carry", "Long carry"], ["landscaping_protection", "Landscape protection"]].map(([k, l]) => (
              <Chip key={k} label={l} active={!!summary[k]} disabled={readonly} onPress={() => setSummary((x) => ({ ...x, [k]: !x[k] }))} />
            ))}
          </View>
          <TextInput style={[s.input, { minHeight: 70 }]} placeholder="Condition / access notes" value={summary.conditions_notes || ""} multiline editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, conditions_notes: v }))} />
        </View>
      </Section>

      <Section title="Gutters (optional)" onAdd={false}>
        <TouchableOpacity style={s.disclosure} onPress={() => setShowGutters((v) => !v)} testID="meas-gutters-toggle">
          <Text style={s.disclosureT}>{showGutters ? "Hide gutter details" : "Add gutter details"}</Text>
        </TouchableOpacity>
        {showGutters && (
          <View style={s.card}>
            <View style={s.rowline}>
              <TextInput style={[s.input, s.half]} keyboardType="numeric" placeholder="Gutter LF" value={summary.gutter_lf != null ? String(summary.gutter_lf) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, gutter_lf: numberOrNull(v) }))} />
              <TextInput style={[s.input, s.half, s.leftGap]} placeholder="Gutter size" value={summary.gutter_size || ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, gutter_size: v }))} />
            </View>
            <View style={s.rowline}>
              <TextInput style={[s.input, s.half]} placeholder="Gutter type" value={summary.gutter_type || ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, gutter_type: v }))} />
              <TextInput style={[s.input, s.half, s.leftGap]} keyboardType="numeric" placeholder="Downspout count" value={summary.downspout_count != null ? String(summary.downspout_count) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, downspout_count: numberOrNull(v) }))} />
            </View>
            <View style={s.rowline}>
              <TextInput style={[s.input, s.half]} keyboardType="numeric" placeholder="Downspout LF" value={summary.downspout_lf != null ? String(summary.downspout_lf) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, downspout_lf: numberOrNull(v) }))} />
              <TextInput style={[s.input, s.half, s.leftGap]} keyboardType="numeric" placeholder="Gutter guard LF" value={summary.gutter_guard_lf != null ? String(summary.gutter_guard_lf) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, gutter_guard_lf: numberOrNull(v) }))} />
            </View>
            <TextInput style={s.input} placeholder="Gutter notes" value={summary.gutter_notes || ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, gutter_notes: v }))} />
          </View>
        )}
      </Section>

      {existing?.id ? <Section title="General measurement photos"><PhotoSection recordType="measurement_revision" recordId={existing.id} /></Section> : <Text style={[s.small, { marginBottom: 12 }]}>Save and sync the measurement once before attaching roof/facet photos.</Text>}

      {!readonly && <>
        <TouchableOpacity style={s.btn} onPress={() => save(false)} testID="meas-save"><Text style={s.btnText}>Save measurement</Text></TouchableOpacity>
        <TouchableOpacity style={[s.btn, s.btnOutline]} onPress={() => save(true)} testID="meas-field-complete"><Text style={[s.btnText, { color: C.brand }]}>Save & Mark Field Complete</Text></TouchableOpacity>
      </>}
    </ScrollView>
  );
}

function Totm({ label, value }) {
  return <View style={{ alignItems: "center", flex: 1 }}><Text style={s.totV}>{value}</Text><Text style={s.totL}>{label}</Text></View>;
}
function Chip({ label, active, onPress, disabled }) {
  return <TouchableOpacity style={[s.chip, active && s.chipOn]} disabled={disabled} onPress={onPress}><Text style={[s.chipT, active && s.chipTOn]}>{label}</Text></TouchableOpacity>;
}
function Section({ title, onAdd, children, addTestID }) {
  return <View style={{ marginBottom: 18 }}><View style={s.secHead}><Text style={s.secTitle}>{title}</Text>{onAdd ? <TouchableOpacity onPress={onAdd} testID={addTestID}><Text style={s.add}>+ Add</Text></TouchableOpacity> : null}</View>{children}</View>;
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  h: { fontSize: 22, fontWeight: "800", color: C.ink },
  status: { color: C.sub, marginTop: 2, marginBottom: 8, textTransform: "capitalize" },
  syncPill: { alignSelf: "flex-start", borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, marginBottom: 8 },
  syncPillT: { fontSize: 12, fontWeight: "800" },
  syncOk: { backgroundColor: "#DCFCE7" },
  syncPend: { backgroundColor: "#FEF9C3" },
  syncWarn: { backgroundColor: "#FEE2E2" },
  conflict: { backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FECACA", borderRadius: 12, padding: 12, marginBottom: 10 },
  conflictT: { color: "#991B1B", fontWeight: "800", fontSize: 15 },
  conflictSub: { color: "#7F1D1D", fontSize: 12, marginTop: 2, marginBottom: 8 },
  conflictBtn: { flex: 1, backgroundColor: C.brand, borderRadius: 10, paddingVertical: 11, alignItems: "center", marginRight: 8 },
  conflictBtnAlt: { backgroundColor: "#fff", borderWidth: 1, borderColor: C.brand, marginRight: 0 },
  conflictBtnT: { color: "#fff", fontWeight: "800", fontSize: 13 },
  disclosure: { paddingVertical: 8 },
  disclosureT: { color: C.brand, fontWeight: "800", fontSize: 14 },
  offline: { padding: 8, borderRadius: 8, backgroundColor: "#FEF3C7", marginBottom: 10 },
  offlineT: { color: "#92400E", fontWeight: "700", fontSize: 12 },
  totals: { flexDirection: "row", backgroundColor: "#fff", borderRadius: 12, padding: 14, marginBottom: 18, borderWidth: 1, borderColor: C.line },
  totV: { fontSize: 17, fontWeight: "800", color: C.ink },
  totL: { fontSize: 10, color: C.sub, textTransform: "uppercase", marginTop: 2 },
  secHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  secTitle: { fontSize: 16, fontWeight: "800", color: C.ink },
  add: { color: C.brand, fontWeight: "800", fontSize: 15 },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 12, marginBottom: 10, borderWidth: 1, borderColor: C.line },
  sketchBtn: { marginTop: 10, backgroundColor: C.brand, borderRadius: 10, paddingVertical: 12, alignItems: "center" },
  sketchBtnText: { color: "#fff", fontWeight: "800", fontSize: 15 },
  sketchHint: { marginTop: 10, color: C.sub, fontSize: 12, fontStyle: "italic" },
  input: { backgroundColor: "#fff", borderRadius: 10, padding: 11, fontSize: 15, borderWidth: 1, borderColor: C.line, marginBottom: 8 },
  rowline: { flexDirection: "row", alignItems: "center" },
  half: { flex: 1 },
  leftGap: { marginLeft: 8 },
  small: { fontSize: 12, color: C.sub, marginBottom: 6, fontWeight: "600" },
  chips: { flexDirection: "row", flexWrap: "wrap", marginBottom: 4 },
  chip: { paddingHorizontal: 11, paddingVertical: 8, borderRadius: 20, borderWidth: 1, borderColor: C.line, marginRight: 6, marginBottom: 6, backgroundColor: "#fff" },
  chipOn: { backgroundColor: C.brand, borderColor: C.brand },
  chipT: { color: C.sub, fontWeight: "700", fontSize: 12 },
  chipTOn: { color: "#fff" },
  penTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 6 },
  penLabel: { fontSize: 15, fontWeight: "700", color: C.ink, flex: 1 },
  counter: { flexDirection: "row", alignItems: "center" },
  cbtn: { width: 38, height: 38, borderRadius: 10, backgroundColor: "#F1F5F9", alignItems: "center", justifyContent: "center" },
  cbtnT: { fontSize: 22, fontWeight: "800", color: C.ink },
  count: { width: 42, textAlign: "center", fontSize: 18, fontWeight: "800", color: C.ink },
  photoBox: { marginTop: 8, borderTopWidth: 1, borderTopColor: C.line, paddingTop: 8 },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 18, alignItems: "center", marginTop: 8 },
  btnOutline: { backgroundColor: "#fff", borderWidth: 2, borderColor: C.brand },
  btnText: { color: "#fff", fontSize: 17, fontWeight: "800" },
});
