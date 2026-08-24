import React, { useState } from "react";
import { View, Text, ScrollView, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { queueMutation } from "../sync";
import { getCache, putCache } from "../storage";
import { C } from "../theme";

// Create a Lead from the field. Works offline: the create is queued (durable) and appears in the
// list immediately as "waiting to sync". If opened from a canvass Property, property_id is preset
// and the server reuses that Property + auto-assigns the Lead to the caller (idempotent, no dup).
export default function NewLead({ route, navigation }) {
  const preset = (route.params || {});
  const [name, setName] = useState(preset.name || "");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [address, setAddress] = useState(preset.address || "");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!name.trim() && !preset.property_id) return Alert.alert("Name required", "Enter a lead/customer name.");
    setSaving(true);
    const body = { name: name.trim() || null, phone: phone || null, email: email || null, address: address || null, notes: notes || null };
    if (preset.property_id) body.property_id = preset.property_id;
    const m = await queueMutation({ kind: "lead_create", method: "post", path: "/mobile/leads", body, label: "New lead" });
    // Optimistic: show in the list right away (temporary id = client id until Office acknowledges).
    try {
      const list = (await getCache("leads")) || [];
      list.unshift({ id: m.client_id, name: body.name || address || "New lead", address: body.address,
                     property_id: preset.property_id || null, status: "new", _pending: true });
      await putCache("leads", list);
    } catch (e) { /* best-effort */ }
    setSaving(false);
    Alert.alert("Saved offline", "We'll sync this lead when RoofSpan Office is available.");
    navigation.goBack();
  };

  return (
    <ScrollView style={s.wrap} contentContainerStyle={{ paddingBottom: 40 }}>
      <Text style={s.h}>New lead</Text>
      <Field label="Name" value={name} onChange={setName} testID="newlead-name" />
      <Field label="Phone" value={phone} onChange={setPhone} keyboardType="phone-pad" testID="newlead-phone" />
      <Field label="Email" value={email} onChange={setEmail} keyboardType="email-address" testID="newlead-email" />
      <Field label="Address" value={address} onChange={setAddress} testID="newlead-address" />
      <Field label="Notes" value={notes} onChange={setNotes} multiline testID="newlead-notes" />
      <TouchableOpacity style={[s.btn, saving && { opacity: 0.6 }]} onPress={save} disabled={saving} testID="newlead-save">
        <Text style={s.btnText}>{saving ? "Saving…" : "Save lead"}</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

function Field({ label, value, onChange, multiline, keyboardType, testID }) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={s.label}>{label}</Text>
      <TextInput style={[s.input, multiline && { minHeight: 70 }]} value={value} onChangeText={onChange}
        multiline={multiline} keyboardType={keyboardType} testID={testID} autoCapitalize={keyboardType === "email-address" ? "none" : "sentences"} />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#F8FAFC", padding: 16 },
  h: { fontSize: 24, fontWeight: "800", color: C.ink, marginBottom: 14 },
  label: { fontSize: 13, color: C.sub, fontWeight: "600", marginBottom: 4 },
  input: { backgroundColor: "#fff", borderRadius: 12, padding: 14, fontSize: 16, borderWidth: 1, borderColor: C.line },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 16, alignItems: "center", marginTop: 8 },
  btnText: { color: "#fff", fontSize: 16, fontWeight: "800" },
});
