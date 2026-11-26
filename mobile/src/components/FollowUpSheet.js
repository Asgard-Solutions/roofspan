import React, { useEffect, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Modal } from "react-native";
import { C } from "../theme";
const { DAY_PICKS, TIME_PICKS, KIND_LABELS, pickDate, fmt } = require("../followups");

// Bottom sheet to schedule a follow-up or book an inspection with big tap targets (no date-picker dependency).
export default function FollowUpSheet({ visible, mode, onClose, onSave }) {
  const [kind, setKind] = useState("call");
  const [day, setDay] = useState(1);
  const [hour, setHour] = useState(9);
  const [note, setNote] = useState("");
  useEffect(() => { if (visible) { setKind("call"); setDay(1); setHour(9); setNote(""); } }, [visible, mode]);
  const when = pickDate(day, hour);
  const title = mode === "inspection" ? "Book inspection" : "Schedule follow-up";
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={s.backdrop}>
        <View style={s.sheet} testID="followup-sheet">
          <Text style={s.h}>{title}</Text>
          {mode !== "inspection" && (
            <Row>{Object.entries(KIND_LABELS).map(([k, l]) => <Chip key={k} on={kind === k} label={l} onPress={() => setKind(k)} testID={`fu-kind-${k}`} />)}</Row>
          )}
          <Text style={s.label}>Day</Text>
          <Row>{DAY_PICKS.map(([l, d]) => <Chip key={l} on={day === d} label={l} onPress={() => setDay(d)} testID={`fu-day-${d}`} />)}</Row>
          <Text style={s.label}>Time</Text>
          <Row>{TIME_PICKS.map(([l, h]) => <Chip key={l} on={hour === h} label={l} onPress={() => setHour(h)} testID={`fu-time-${h}`} />)}</Row>
          <TextInput style={s.input} placeholder={mode === "inspection" ? "Gate code, dog in yard…" : "What's the next step?"} value={note} onChangeText={setNote} multiline testID="fu-note" />
          <Text style={s.when} testID="fu-when">{fmt(when)}</Text>
          <View style={s.btns}>
            <TouchableOpacity style={s.ghost} onPress={onClose}><Text style={s.ghostText}>Cancel</Text></TouchableOpacity>
            <TouchableOpacity style={s.btn} onPress={() => onSave({ kind, due_at: when.toISOString(), note: note.trim() || null })} testID="fu-save"><Text style={s.btnText}>Save</Text></TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function Row({ children }) { return <View style={s.row}>{children}</View>; }
function Chip({ on, label, onPress, testID }) {
  return <TouchableOpacity style={[s.chip, on && s.chipOn]} onPress={onPress} testID={testID}><Text style={[s.chipText, on && { color: C.brand }]}>{label}</Text></TouchableOpacity>;
}

const s = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(15,23,42,0.4)" },
  sheet: { backgroundColor: "#fff", borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 18, paddingBottom: 32 },
  h: { fontSize: 20, fontWeight: "800", color: C.ink, marginBottom: 10 },
  label: { fontSize: 13, color: C.sub, fontWeight: "600", marginTop: 10, marginBottom: 6 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 2, borderColor: C.line, borderRadius: 24, paddingVertical: 10, paddingHorizontal: 14 },
  chipOn: { borderColor: C.brand, backgroundColor: "#FFF7ED" },
  chipText: { fontWeight: "700", color: C.ink },
  input: { backgroundColor: "#F8FAFC", borderRadius: 12, padding: 14, fontSize: 16, minHeight: 48, borderWidth: 1, borderColor: C.line, marginTop: 12 },
  when: { marginTop: 10, color: C.sub, fontWeight: "700" },
  btns: { flexDirection: "row", gap: 10, marginTop: 14 },
  btn: { flex: 1, backgroundColor: C.brand, borderRadius: 12, padding: 16, alignItems: "center" },
  btnText: { color: "#fff", fontSize: 16, fontWeight: "800" },
  ghost: { flex: 1, borderRadius: 12, padding: 16, alignItems: "center" },
  ghostText: { color: C.sub, fontWeight: "700" },
});
