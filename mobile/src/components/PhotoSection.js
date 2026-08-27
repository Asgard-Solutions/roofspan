import React, { useCallback, useState } from "react";
import { View, Text, Image, ScrollView, TouchableOpacity, TextInput, StyleSheet, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import * as ImagePicker from "expo-image-picker";
import * as FileSystem from "expo-file-system/legacy";
import { api } from "../api";
import { API_BASE } from "../config";
import { getToken } from "../auth";
import { queueMutation, pendingSummary, syncNow, removeMutation, replacePhoto } from "../sync";
import queue from "../queue";
import { C, badge } from "../theme";

const EXT_TO_TYPE = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", heic: "image/heic", heif: "image/heif" };
const TYPE_TO_EXT = { "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic", "image/heif": "heif" };

// Preset categories (mirrors backend _CATS). Configurable admin intentionally NOT built (K.I.S.S.).
const CATEGORIES = ["Overview", "Roof", "Damage", "Exterior", "Interior", "Measurement", "Before", "After", "Other"];
const PHOTO_DIR = FileSystem.documentDirectory + "roofspan_photos/";

// Field photo capture + offline queue. Captured/selected files are copied to the app's document
// directory so they survive restarts, then queued (upload on reconnect). The local copy is kept.
export default function PhotoSection({ recordType, recordId }) {
  const [serverPhotos, setServerPhotos] = useState([]);
  const [pending, setPending] = useState([]);
  const [category, setCategory] = useState("Overview");
  const [note, setNote] = useState("");
  const [token, setToken] = useState(null);

  const load = useCallback(async () => {
    getToken().then(setToken);
    try {
      const r = await api.get("/mobile/photos", { params: { record_type: recordType, record_id: recordId } });
      setServerPhotos(r.data || []);
    } catch (e) { /* offline: keep last */ }
    const { items } = await pendingSummary();
    setPending(items.filter((m) => m.kind === "photo" && m.state !== "synced" && m.body && m.body.record_id === recordId));
  }, [recordType, recordId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Copy a picked/captured asset into durable storage and return {uri,name,type}, or null (with an
  // alert) if the format is unsupported / the copy fails. Shared by capture, library, and replace.
  const buildPhoto = async (asset) => {
    try {
      let type = (asset.mimeType || "").toLowerCase();
      let ext = ((asset.fileName || "").split(".").pop() || asset.uri.split(".").pop() || "").toLowerCase().replace(/[^a-z0-9]/g, "");
      if (!type) type = EXT_TO_TYPE[ext] || "";
      if (!ext) ext = TYPE_TO_EXT[type] || "";
      if (!type || !queue.SUPPORTED_PHOTO_TYPES.includes(type)) {
        Alert.alert("Unsupported photo", "That image format isn't supported. Please choose a JPEG, PNG, WEBP, or HEIC photo.");
        return null;
      }
      await FileSystem.makeDirectoryAsync(PHOTO_DIR, { intermediates: true }).catch(() => {});
      const dest = `${PHOTO_DIR}${Date.now()}.${ext || "jpg"}`;
      await FileSystem.copyAsync({ from: asset.uri, to: dest });
      return { uri: dest, name: `photo.${ext || "jpg"}`, type };
    } catch (e) {
      Alert.alert("Error", "Could not save photo.");
      return null;
    }
  };

  const captureFrom = async (source) => {
    if (source === "camera") {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) { Alert.alert("Permission needed", "Camera access is required."); return null; }
      const res = await ImagePicker.launchCameraAsync({ quality: 0.6, allowsEditing: false });
      return !res.canceled && res.assets && res.assets[0] ? res.assets[0] : null;
    }
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) { Alert.alert("Permission needed", "Photo library access is required."); return null; }
    const res = await ImagePicker.launchImageLibraryAsync({ quality: 0.6, mediaTypes: ["images"] });
    return !res.canceled && res.assets && res.assets[0] ? res.assets[0] : null;
  };

  const persistAndQueue = async (asset) => {
    const photo = await buildPhoto(asset);
    if (!photo) return;
    await queueMutation({
      kind: "photo",
      method: "post",
      path: "/mobile/photos",
      body: { record_type: recordType, record_id: recordId, category, description: note || null },
      photo,
      label: `${category} photo`,
    });
    setNote("");
    await load();
    Alert.alert("Saved", "Photo saved and queued (will upload when online).");
  };

  const retryItem = async () => { await syncNow(); await load(); };

  const removeItem = (m) => {
    Alert.alert(
      "Remove failed photo?",
      "This photo cannot be uploaded because its local file is unavailable. Removing it will only remove this failed photo upload. Other offline work will not be affected.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Remove", style: "destructive", onPress: async () => { await removeMutation(m.client_id); await load(); } },
      ]
    );
  };

  // Re-shoot a failed photo, keeping its category/note/record and idempotency key.
  const replaceItem = (m) => {
    Alert.alert(
      "Replace photo",
      "Choose a new photo for this upload. Your note and category are kept.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Take photo", onPress: () => doReplace(m, "camera") },
        { text: "Library", onPress: () => doReplace(m, "library") },
      ]
    );
  };
  const doReplace = async (m, source) => {
    const asset = await captureFrom(source);
    if (!asset) return;
    const photo = await buildPhoto(asset);
    if (!photo) return;
    await replacePhoto(m.client_id, photo);
    await load();
  };

  const takePhoto = async () => { const a = await captureFrom("camera"); if (a) persistAndQueue(a); };
  const pickPhoto = async () => { const a = await captureFrom("library"); if (a) persistAndQueue(a); };

  return (
    <View testID="photo-section">
      <Text style={s.h}>Photos</Text>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.cats}>
        {CATEGORIES.map((c) => (
          <TouchableOpacity key={c} style={[s.cat, category === c && s.catOn]} onPress={() => setCategory(c)} testID={`photo-cat-${c}`}>
            <Text style={[s.catText, category === c && s.catTextOn]}>{c}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <TextInput style={s.input} placeholder="Optional note…" value={note} onChangeText={setNote} testID="photo-note-input" />

      <View style={s.btnRow}>
        <TouchableOpacity style={s.btn} onPress={takePhoto} testID="photo-take"><Text style={s.btnText}>Take photo</Text></TouchableOpacity>
        <TouchableOpacity style={s.btnOutline} onPress={pickPhoto} testID="photo-pick"><Text style={s.btnOutlineText}>Library</Text></TouchableOpacity>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.grid}>
        {pending.map((m) => {
          const uri = m && m.photo && typeof m.photo.uri === "string" ? m.photo.uri : null;
          const failed = m.state === "failed";
          const b = m.body || {};
          return (
            <View key={m.client_id} style={s.thumb} testID={`photo-pending-${m.client_id}`}>
              {uri ? (
                <Image source={{ uri }} style={s.img} onError={() => {}} />
              ) : (
                <View style={[s.img, s.imgMissing]} testID={`photo-missing-${m.client_id}`}>
                  <Text style={s.imgMissingText}>{failed ? "Photo needs attention" : "Photo file unavailable"}</Text>
                </View>
              )}
              <View style={[s.pill, { backgroundColor: badge[m.state] ? badge[m.state].bg : badge.pending.bg }]}>
                <Text style={[s.pillText, { color: badge[m.state] ? badge[m.state].fg : badge.pending.fg }]}>{(badge[m.state] || badge.pending).label}</Text>
              </View>
              <Text style={s.cap}>{b.category || "Photo"}</Text>
              {failed ? (
                <>
                  <Text style={s.errText} testID={`photo-error-${m.client_id}`}>{m.error || "Upload failed"}</Text>
                  <View style={s.recoverRow}>
                    <TouchableOpacity style={s.retryBtn} onPress={retryItem} testID={`photo-retry-${m.client_id}`}><Text style={s.retryText}>Retry</Text></TouchableOpacity>
                    <TouchableOpacity style={s.replaceBtn} onPress={() => replaceItem(m)} testID={`photo-replace-${m.client_id}`}><Text style={s.replaceText}>Replace</Text></TouchableOpacity>
                    <TouchableOpacity style={s.removeBtn} onPress={() => removeItem(m)} testID={`photo-remove-${m.client_id}`}><Text style={s.removeText}>Remove</Text></TouchableOpacity>
                  </View>
                </>
              ) : null}
            </View>
          );
        })}
        {serverPhotos.map((p) => (
          <View key={p.id} style={s.thumb} testID={`photo-synced-${p.id}`}>
            <Image source={{ uri: `${API_BASE}${p.content_url}`, headers: token ? { Authorization: `Bearer ${token}` } : undefined }} style={s.img} />
            <View style={[s.pill, { backgroundColor: badge.synced.bg }]}><Text style={[s.pillText, { color: badge.synced.fg }]}>Synced</Text></View>
            <Text style={s.cap}>{p.category || "—"}</Text>
          </View>
        ))}
        {pending.length === 0 && serverPhotos.length === 0 && <Text style={s.empty}>No photos yet.</Text>}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  h: { fontSize: 16, fontWeight: "700", color: C.ink, marginTop: 20, marginBottom: 8 },
  cats: { flexGrow: 0, marginBottom: 10 },
  cat: { borderWidth: 2, borderColor: C.line, borderRadius: 20, paddingVertical: 8, paddingHorizontal: 14, marginRight: 8 },
  catOn: { borderColor: C.brand, backgroundColor: "#FFF7ED" },
  catText: { color: C.sub, fontWeight: "700" },
  catTextOn: { color: C.brand },
  input: { backgroundColor: "#fff", borderRadius: 12, padding: 12, fontSize: 15, borderWidth: 1, borderColor: C.line, marginBottom: 10 },
  btnRow: { flexDirection: "row", gap: 10 },
  btn: { flex: 1, backgroundColor: C.brand, borderRadius: 12, padding: 14, alignItems: "center" },
  btnText: { color: "#fff", fontWeight: "800" },
  btnOutline: { flex: 1, borderWidth: 2, borderColor: C.brand, borderRadius: 12, padding: 12, alignItems: "center" },
  btnOutlineText: { color: C.brand, fontWeight: "800" },
  grid: { marginTop: 12, flexGrow: 0 },
  thumb: { marginRight: 10, width: 110 },
  img: { width: 110, height: 110, borderRadius: 10, backgroundColor: "#E2E8F0" },
  imgMissing: { alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: C.line, padding: 6 },
  imgMissingText: { fontSize: 11, fontWeight: "700", color: C.sub, textAlign: "center" },
  errText: { fontSize: 11, color: "#B91C1C", marginTop: 2, fontWeight: "600" },
  recoverRow: { flexDirection: "row", gap: 6, marginTop: 6 },
  retryBtn: { flex: 1, backgroundColor: C.brand, borderRadius: 8, paddingVertical: 6, alignItems: "center" },
  retryText: { color: "#fff", fontWeight: "800", fontSize: 12 },
  replaceBtn: { flex: 1, borderWidth: 1, borderColor: C.brand, borderRadius: 8, paddingVertical: 6, alignItems: "center" },
  replaceText: { color: C.brand, fontWeight: "800", fontSize: 12 },
  removeBtn: { flex: 1, borderWidth: 1, borderColor: "#B91C1C", borderRadius: 8, paddingVertical: 6, alignItems: "center" },
  removeText: { color: "#B91C1C", fontWeight: "800", fontSize: 12 },
  pill: { position: "absolute", top: 6, left: 6, borderRadius: 8, paddingVertical: 2, paddingHorizontal: 6 },
  pillText: { fontSize: 10, fontWeight: "800" },
  cap: { fontSize: 12, color: C.sub, marginTop: 4, fontWeight: "700" },
  empty: { color: C.sub, fontStyle: "italic", paddingVertical: 20 },
});
