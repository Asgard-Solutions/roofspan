import React, { useCallback, useMemo, useState } from "react";
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { queueMutation } from "../sync";
import { cache, cacheMeasurementDetail, loadMeasurementDraft, saveMeasurementDraft, clearMeasurementDraft } from "../cache";
import { C } from "../theme";
import PhotoSection from "../components/PhotoSection";

const measurementKeys = require("../measurementCache");
const queueCore = require("../queue");

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

function edgeForEdit(e) {
  const length = Number(e.length_ft || 0);
  const ft = Math.floor(length);
  const inches = Math.round((length - ft) * 12 * 10) / 10;
  return { ...e, _k: e._k || e.id || uid(), facet_ref: e.facet_ref || e.facet_id || "", ft: String(ft || ""), in: String(inches || "") };
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

  const hydrate = useCallback((full, stale = false, cached = null) => {
    if (!full) return;
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
    const draft = await loadMeasurementDraft(scope);
    const listResult = await cache.measurements(scope);
    const head = measurementKeys.pickCurrent(listResult.data || []);
    if (head) {
      const detailResult = await cache.measurement(head.id);
      if (detailResult.data) {
        hydrate(detailResult.data, listResult.stale || detailResult.stale, detailResult.cachedAt || listResult.cachedAt);
        if (!listResult.stale && !detailResult.stale) await clearMeasurementDraft(scope);
        return;
      }
    }
    if (draft) {
      hydrate(draft, true, draft.updated_at);
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
  }, [scope, hydrate]);

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
  const addEdge = () => setEdges((a) => [...a, { _k: uid(), edge_type: "eave", ft: "", in: "", length_ft: 0, facet_ref: "" }]);
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
      roof_material: f.roof_material || null, notes: f.notes || null, sort: i,
    })),
    edges: edges.map((e, i) => ({
      edge_type: e.edge_type || "eave", length_ft: parseFloat(e.length_ft) || 0,
      facet_ref: e.facet_ref || null, label: e.label || null, notes: e.notes || null, sort: i,
    })),
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
    Alert.alert("Saved", markComplete ? "Measurement marked Field Complete and queued to sync." : "Measurement saved locally and queued to sync.");
    navigation.goBack();
  };

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ paddingBottom: 60 }}>
      <Text style={s.h}>Roof measurements</Text>
      {existing && <Text style={s.status} testID="meas-status">Revision {existing.revision_number || ""} · {String(existing.status || "draft").replace("_", " ")}{readonly ? " · locked" : ""}</Text>}
      {!existing && localDraft && <Text style={s.status}>Local draft · waiting to sync</Text>}
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
          </View>
        ))}
      </Section>

      <Section title="Roof facets" onAdd={!readonly && addFacet} addTestID="meas-add-facet">
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

      <Section title="Edges (ft / in)" onAdd={!readonly && addEdge} addTestID="meas-add-edge">
        {edges.map((e, i) => (
          <View key={e._k} style={s.card} testID={`meas-edge-${i}`}>
            <View style={s.chips}>{EDGE_TYPES.map(([v, l]) => <Chip key={v} label={l} active={e.edge_type === v} disabled={readonly} onPress={() => setE(i, "edge_type", v)} />)}</View>
            <View style={s.rowline}>
              <TextInput style={[s.input, { width: 90 }]} keyboardType="numeric" placeholder="ft" value={String(e.ft ?? "")} editable={!readonly} onChangeText={(v) => setE(i, "ft", v)} />
              <TextInput style={[s.input, { width: 90, marginLeft: 8 }]} keyboardType="numeric" placeholder="in" value={String(e.in ?? "")} editable={!readonly} onChangeText={(v) => setE(i, "in", v)} />
              <Text style={[s.small, { marginLeft: 10, alignSelf: "center" }]}>{(parseFloat(e.length_ft) || 0).toFixed(1)} LF</Text>
            </View>
            {!!facets.length && <View style={s.chips}>{facets.map((f) => <Chip key={f.ref} label={f.facet_label || "Facet"} active={e.facet_ref === f.ref} disabled={readonly} onPress={() => setE(i, "facet_ref", f.ref)} />)}</View>}
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
              {!!facets.length && <View style={s.chips}>{facets.map((f) => <Chip key={f.ref} label={f.facet_label || "Facet"} active={p.facet_ref === f.ref} disabled={readonly} onPress={() => setP(i, "facet_ref", f.ref)} />)}</View>}
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
          <View style={s.chips}>
            {[["full_redeck", "Full re-deck"], ["steep_access", "Steep access"], ["high_access", "High access"], ["restricted_access", "Restricted"], ["long_carry", "Long carry"], ["landscaping_protection", "Landscape protection"]].map(([k, l]) => (
              <Chip key={k} label={l} active={!!summary[k]} disabled={readonly} onPress={() => setSummary((x) => ({ ...x, [k]: !x[k] }))} />
            ))}
          </View>
          <TextInput style={[s.input, { minHeight: 70 }]} placeholder="Condition / access notes" value={summary.conditions_notes || ""} multiline editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, conditions_notes: v }))} />
        </View>
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
  offline: { padding: 8, borderRadius: 8, backgroundColor: "#FEF3C7", marginBottom: 10 },
  offlineT: { color: "#92400E", fontWeight: "700", fontSize: 12 },
  totals: { flexDirection: "row", backgroundColor: "#fff", borderRadius: 12, padding: 14, marginBottom: 18, borderWidth: 1, borderColor: C.line },
  totV: { fontSize: 17, fontWeight: "800", color: C.ink },
  totL: { fontSize: 10, color: C.sub, textTransform: "uppercase", marginTop: 2 },
  secHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  secTitle: { fontSize: 16, fontWeight: "800", color: C.ink },
  add: { color: C.brand, fontWeight: "800", fontSize: 15 },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 12, marginBottom: 10, borderWidth: 1, borderColor: C.line },
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
