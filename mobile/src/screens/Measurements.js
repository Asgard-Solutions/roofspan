import React, { useCallback, useMemo, useState } from "react";
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api";
import { useAuth } from "../auth";
import { queueMutation } from "../sync";
import { C } from "../theme";
import PhotoSection from "../components/PhotoSection";

const STRUCTURE_TYPES = [
  ["main_house", "Main"], ["attached_garage", "Att. Garage"], ["detached_garage", "Det. Garage"],
  ["porch", "Porch"], ["addition", "Addition"], ["shed", "Shed"], ["other", "Other"],
];
const PITCHES = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12];
const EDGE_TYPES = [
  ["eave", "Eave"], ["rake", "Rake"], ["ridge", "Ridge"], ["hip", "Hip"], ["valley", "Valley"],
  ["sidewall", "Sidewall"], ["headwall", "Headwall"],
];
const PEN_TYPES = [
  ["pipe_boot", "Pipe boots"], ["static_vent", "Static vents"], ["skylight", "Skylights"],
  ["turbine", "Turbines"], ["exhaust_vent", "Exhaust vents"], ["chimney", "Chimneys"],
];
const uid = () => "r" + Math.random().toString(36).slice(2, 10);

export default function Measurements({ route, navigation }) {
  const { lead_id, property_id } = route.params || {};
  const { user } = useAuth();
  const [existing, setExisting] = useState(null);       // {id, if_match, status, editable}
  const [structures, setStructures] = useState([]);
  const [facets, setFacets] = useState([]);
  const [edges, setEdges] = useState([]);
  const [pens, setPens] = useState(PEN_TYPES.map(([t]) => ({ _k: uid(), pen_type: t, quantity: 0 })));
  const [summary, setSummary] = useState({});
  const [readonly, setReadonly] = useState(false);

  const load = useCallback(async () => {
    try {
      const params = lead_id ? { lead_id } : { property_id };
      const list = (await api.get(`/mobile/measurements`, { params })).data;
      if (list && list.length) {
        const head = list[0];
        const full = (await api.get(`/mobile/measurements/${head.id}`)).data;
        setExisting({ id: full.id, if_match: full.updated_at, status: full.status, editable: full.editable });
        setReadonly(!full.editable);
        setStructures((full.structures || []).map((s) => ({ ...s, ref: s.id })));
        setFacets((full.facets || []).map((f) => ({ ...f, ref: f.id, structure_ref: f.structure_id || "" })));
        setEdges((full.edges || []).map((e) => ({ ...e, _k: e.id, facet_ref: e.facet_id || "" })));
        const byType = {};
        (full.penetrations || []).forEach((p) => { byType[p.pen_type] = (byType[p.pen_type] || 0) + (p.quantity || 0); });
        setPens(PEN_TYPES.map(([t]) => ({ _k: uid(), pen_type: t, quantity: byType[t] || 0 })));
        setSummary(full.summary || {});
      }
    } catch (e) { /* offline: start blank */ }
  }, [lead_id, property_id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const totals = useMemo(() => {
    const area = facets.reduce((s, f) => s + (parseFloat(f.area_sqft) || 0), 0);
    const edge = {};
    edges.forEach((e) => { edge[e.edge_type] = (edge[e.edge_type] || 0) + (parseFloat(e.length_ft) || 0); });
    const pen = pens.reduce((s, p) => s + (parseInt(p.quantity) || 0), 0);
    return { area, squares: area / 100, edge, pen };
  }, [facets, edges, pens]);

  const addStructure = () => setStructures((a) => [...a, { ref: uid(), name: "", structure_type: "main_house" }]);
  const addFacet = () => setFacets((a) => [...a, { ref: uid(), facet_label: `F${a.length + 1}`, pitch_rise: 6, area_sqft: "" }]);
  const addEdge = () => setEdges((a) => [...a, { _k: uid(), edge_type: "eave", ft: "", in: "", length_ft: 0 }]);
  const setS = (i, k, v) => setStructures((a) => a.map((x, idx) => idx === i ? { ...x, [k]: v } : x));
  const setF = (i, k, v) => setFacets((a) => a.map((x, idx) => idx === i ? { ...x, [k]: v } : x));
  const setE = (i, k, v) => setEdges((a) => a.map((x, idx) => {
    if (idx !== i) return x;
    const nx = { ...x, [k]: v };
    nx.length_ft = (parseFloat(nx.ft) || 0) + (parseFloat(nx.in) || 0) / 12;
    return nx;
  }));
  const bumpPen = (i, d) => setPens((a) => a.map((x, idx) => idx === i ? { ...x, quantity: Math.max(0, (parseInt(x.quantity) || 0) + d) } : x));

  const buildBody = (markComplete) => ({
    lead_id: lead_id || null, property_id: property_id || null, mark_field_complete: !!markComplete,
    structures: structures.map((s, i) => ({ ref: s.ref, name: s.name, structure_type: s.structure_type, sort: i })),
    facets: facets.map((f, i) => ({ ref: f.ref, structure_ref: f.structure_ref || null, facet_label: f.facet_label, pitch_rise: f.pitch_rise == null || f.pitch_rise === "" ? null : parseFloat(f.pitch_rise), area_sqft: parseFloat(f.area_sqft) || 0, sort: i })),
    edges: edges.map((e, i) => ({ edge_type: e.edge_type, length_ft: parseFloat(e.length_ft) || 0, facet_ref: e.facet_ref || null, sort: i })),
    penetrations: pens.filter((p) => (parseInt(p.quantity) || 0) > 0).map((p, i) => ({ pen_type: p.pen_type, quantity: parseInt(p.quantity), sort: i })),
    summary,
  });

  const save = async (markComplete) => {
    if (readonly) { Alert.alert("Locked", "This measurement is verified/locked. Ask the office to return it to the field to edit."); return; }
    const body = buildBody(markComplete);
    if (existing) {
      await queueMutation({ kind: "measurement_update", method: "put", path: `/mobile/measurements/${existing.id}`, body, ifMatch: existing.if_match, label: "Roof measurement" });
    } else {
      await queueMutation({ kind: "measurement", method: "post", path: "/mobile/measurements", body, label: "Roof measurement" });
    }
    Alert.alert("Saved", markComplete ? "Measurement marked Field Complete (will sync)." : "Measurement queued (will sync).");
    navigation.goBack();
  };

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ paddingBottom: 60 }}>
      <Text style={s.h}>Roof measurements</Text>
      {existing && <Text style={s.status} testID="meas-status">Rev {existing.status ? existing.status.replace("_", " ") : ""}{readonly ? " · locked" : ""}</Text>}

      {/* Live totals */}
      <View style={s.totals} testID="meas-totals">
        <Totm label="Area" value={`${totals.area.toFixed(0)} sf`} />
        <Totm label="Squares" value={totals.squares.toFixed(2)} />
        <Totm label="Facets" value={facets.length} />
        <Totm label="Penetr." value={totals.pen} />
      </View>

      {/* Structures */}
      <Section title="Structures" onAdd={!readonly && addStructure} addTestID="meas-add-structure">
        {structures.map((st, i) => (
          <View key={st.ref} style={s.card} testID={`meas-structure-${i}`}>
            <TextInput style={s.input} placeholder="Name (e.g. Main House)" value={st.name} editable={!readonly} onChangeText={(v) => setS(i, "name", v)} testID={`meas-structure-name-${i}`} />
            <View style={s.chips}>
              {STRUCTURE_TYPES.map(([v, l]) => (
                <Chip key={v} label={l} active={st.structure_type === v} disabled={readonly} onPress={() => setS(i, "structure_type", v)} />
              ))}
            </View>
          </View>
        ))}
      </Section>

      {/* Facets */}
      <Section title="Roof facets" onAdd={!readonly && addFacet} addTestID="meas-add-facet">
        {facets.map((f, i) => (
          <View key={f.ref} style={s.card} testID={`meas-facet-${i}`}>
            <View style={s.rowline}>
              <TextInput style={[s.input, { width: 70 }]} value={f.facet_label} editable={!readonly} onChangeText={(v) => setF(i, "facet_label", v)} testID={`meas-facet-label-${i}`} />
              <TextInput style={[s.input, { flex: 1, marginLeft: 8 }]} keyboardType="numeric" placeholder="Area sq ft" value={String(f.area_sqft ?? "")} editable={!readonly} onChangeText={(v) => setF(i, "area_sqft", v)} testID={`meas-facet-area-${i}`} />
            </View>
            <Text style={s.small}>Pitch (x/12)</Text>
            <View style={s.chips}>
              {PITCHES.map((p) => <Chip key={p} label={`${p}`} active={Number(f.pitch_rise) === p} disabled={readonly} onPress={() => setF(i, "pitch_rise", p)} />)}
            </View>
            {structures.length > 0 && (
              <>
                <Text style={s.small}>Structure</Text>
                <View style={s.chips}>
                  {structures.map((st) => <Chip key={st.ref} label={st.name || "Structure"} active={f.structure_ref === st.ref} disabled={readonly} onPress={() => setF(i, "structure_ref", st.ref)} />)}
                </View>
              </>
            )}
            {f.id ? (
              <View style={{ marginTop: 8, borderTopWidth: 1, borderTopColor: C.line, paddingTop: 8 }}>
                <Text style={s.small}>Facet photos</Text>
                <PhotoSection recordType="measurement_facet" recordId={f.id} />
              </View>
            ) : null}
          </View>
        ))}
      </Section>

      {/* Edges */}
      <Section title="Edges (ft / in)" onAdd={!readonly && addEdge} addTestID="meas-add-edge">
        {edges.map((e, i) => (
          <View key={e._k} style={s.card} testID={`meas-edge-${i}`}>
            <View style={s.chips}>
              {EDGE_TYPES.map(([v, l]) => <Chip key={v} label={l} active={e.edge_type === v} disabled={readonly} onPress={() => setE(i, "edge_type", v)} />)}
            </View>
            <View style={s.rowline}>
              <TextInput style={[s.input, { width: 90 }]} keyboardType="numeric" placeholder="ft" value={String(e.ft ?? "")} editable={!readonly} onChangeText={(v) => setE(i, "ft", v)} testID={`meas-edge-ft-${i}`} />
              <TextInput style={[s.input, { width: 90, marginLeft: 8 }]} keyboardType="numeric" placeholder="in" value={String(e.in ?? "")} editable={!readonly} onChangeText={(v) => setE(i, "in", v)} testID={`meas-edge-in-${i}`} />
              <Text style={[s.small, { marginLeft: 10, alignSelf: "center" }]}>{(parseFloat(e.length_ft) || 0).toFixed(1)} LF</Text>
            </View>
          </View>
        ))}
      </Section>

      {/* Penetration counters */}
      <Section title="Penetrations">
        {pens.map((p, i) => (
          <View key={p._k} style={s.penRow} testID={`meas-pen-${p.pen_type}`}>
            <Text style={s.penLabel}>{PEN_TYPES.find((t) => t[0] === p.pen_type)?.[1] || p.pen_type}</Text>
            <View style={s.counter}>
              <TouchableOpacity style={s.cbtn} disabled={readonly} onPress={() => bumpPen(i, -1)} testID={`meas-pen-minus-${p.pen_type}`}><Text style={s.cbtnT}>−</Text></TouchableOpacity>
              <Text style={s.count} testID={`meas-pen-count-${p.pen_type}`}>{p.quantity}</Text>
              <TouchableOpacity style={s.cbtn} disabled={readonly} onPress={() => bumpPen(i, 1)} testID={`meas-pen-plus-${p.pen_type}`}><Text style={s.cbtnT}>+</Text></TouchableOpacity>
            </View>
          </View>
        ))}
      </Section>

      {/* Existing roof / conditions */}
      <Section title="Existing roof & conditions">
        <View style={s.card}>
          <TextInput style={s.input} placeholder="Existing covering (e.g. 3-tab asphalt)" value={summary.existing_covering_type || ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, existing_covering_type: v }))} testID="meas-covering" />
          <View style={s.rowline}>
            <TextInput style={[s.input, { flex: 1 }]} keyboardType="numeric" placeholder="Layers" value={summary.existing_layers != null ? String(summary.existing_layers) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, existing_layers: v ? parseInt(v) : null }))} testID="meas-layers" />
            <TextInput style={[s.input, { flex: 1, marginLeft: 8 }]} keyboardType="numeric" placeholder="Ridge vent LF" value={summary.ridge_vent_lf != null ? String(summary.ridge_vent_lf) : ""} editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, ridge_vent_lf: v ? parseFloat(v) : null }))} testID="meas-ridgevent" />
          </View>
          <View style={s.chips}>
            {[["full_redeck", "Full re-deck"], ["steep_access", "Steep"], ["high_access", "High"], ["restricted_access", "Restricted"]].map(([k, l]) => (
              <Chip key={k} label={l} active={!!summary[k]} disabled={readonly} onPress={() => setSummary((x) => ({ ...x, [k]: !x[k] }))} />
            ))}
          </View>
          <TextInput style={[s.input, { minHeight: 60 }]} placeholder="Condition / access notes" value={summary.conditions_notes || ""} multiline editable={!readonly} onChangeText={(v) => setSummary((x) => ({ ...x, conditions_notes: v }))} testID="meas-notes" />
        </View>
      </Section>

      {existing?.id ? (
        <Section title="General measurement photos">
          <PhotoSection recordType="measurement_revision" recordId={existing.id} />
        </Section>
      ) : (
        <Text style={[s.small, { marginBottom: 12 }]}>Save the measurement first to attach photos to facets or the roof overall.</Text>
      )}

      {!readonly && (
        <>
          <TouchableOpacity style={s.btn} onPress={() => save(false)} testID="meas-save"><Text style={s.btnText}>Save measurement</Text></TouchableOpacity>
          <TouchableOpacity style={[s.btn, s.btnOutline]} onPress={() => save(true)} testID="meas-field-complete"><Text style={[s.btnText, { color: C.brand }]}>Save & Mark Field Complete</Text></TouchableOpacity>
        </>
      )}
    </ScrollView>
  );
}

function Totm({ label, value }) {
  return <View style={{ alignItems: "center", flex: 1 }}><Text style={s.totV}>{value}</Text><Text style={s.totL}>{label}</Text></View>;
}
function Chip({ label, active, onPress, disabled }) {
  return (
    <TouchableOpacity style={[s.chip, active && s.chipOn]} disabled={disabled} onPress={onPress}>
      <Text style={[s.chipT, active && s.chipTOn]}>{label}</Text>
    </TouchableOpacity>
  );
}
function Section({ title, onAdd, children, addTestID }) {
  return (
    <View style={{ marginBottom: 18 }}>
      <View style={s.secHead}>
        <Text style={s.secTitle}>{title}</Text>
        {onAdd ? <TouchableOpacity onPress={onAdd} testID={addTestID}><Text style={s.add}>+ Add</Text></TouchableOpacity> : null}
      </View>
      {children}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  h: { fontSize: 22, fontWeight: "800", color: C.ink },
  status: { color: C.sub, marginTop: 2, marginBottom: 8, textTransform: "capitalize" },
  totals: { flexDirection: "row", backgroundColor: "#fff", borderRadius: 12, padding: 14, marginBottom: 18, borderWidth: 1, borderColor: C.line },
  totV: { fontSize: 18, fontWeight: "800", color: C.ink },
  totL: { fontSize: 11, color: C.sub, textTransform: "uppercase", marginTop: 2 },
  secHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  secTitle: { fontSize: 16, fontWeight: "800", color: C.ink },
  add: { color: C.brand, fontWeight: "800", fontSize: 15 },
  card: { backgroundColor: "#fff", borderRadius: 12, padding: 12, marginBottom: 10, borderWidth: 1, borderColor: C.line },
  input: { backgroundColor: "#fff", borderRadius: 10, padding: 12, fontSize: 16, borderWidth: 1, borderColor: C.line, marginBottom: 8 },
  rowline: { flexDirection: "row", alignItems: "center" },
  small: { fontSize: 12, color: C.sub, marginBottom: 6, fontWeight: "600" },
  chips: { flexDirection: "row", flexWrap: "wrap", marginBottom: 4 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 20, borderWidth: 1, borderColor: C.line, marginRight: 6, marginBottom: 6, backgroundColor: "#fff" },
  chipOn: { backgroundColor: C.brand, borderColor: C.brand },
  chipT: { color: C.sub, fontWeight: "700", fontSize: 13 },
  chipTOn: { color: "#fff" },
  penRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: "#fff", borderRadius: 12, padding: 12, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  penLabel: { fontSize: 15, fontWeight: "700", color: C.ink },
  counter: { flexDirection: "row", alignItems: "center" },
  cbtn: { width: 40, height: 40, borderRadius: 10, backgroundColor: "#F1F5F9", alignItems: "center", justifyContent: "center" },
  cbtnT: { fontSize: 22, fontWeight: "800", color: C.ink },
  count: { width: 44, textAlign: "center", fontSize: 18, fontWeight: "800", color: C.ink },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 18, alignItems: "center", marginTop: 8 },
  btnOutline: { backgroundColor: "#fff", borderWidth: 2, borderColor: C.brand },
  btnText: { color: "#fff", fontSize: 17, fontWeight: "800" },
});
