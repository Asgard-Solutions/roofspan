import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Alert, ActivityIndicator, Linking } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { C } from "../theme";
import { usePairing } from "../pairingContext";
import { parseQrPayload, normalizeNumericCode, isValidNumericCode, formatNumericCode } from "../pairing";

export default function Connect() {
  const { pair } = usePairing();
  const [mode, setMode] = useState("choose"); // choose | scan | code
  const [permission, requestPermission] = useCameraPermissions();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [scanned, setScanned] = useState(false);

  const submit = async (args) => {
    if (busy) return;
    setBusy(true);
    let r;
    try {
      r = await pair(args);
    } catch (e) {
      r = { ok: false, code: "unreachable" };
    } finally {
      setBusy(false);
    }
    if (!r.ok) {
      const msg =
        r.code === "not_found" ? "That pairing code wasn't found. Generate a new code in RoofSpan Office and try again." :
        r.code === "used" ? "That pairing code was already used. Generate a new code in RoofSpan Office." :
        r.code === "expired" ? "That pairing code has expired. Generate a new code in RoofSpan Office." :
        r.code === "unreachable" ? "RoofSpan could not reach the hosted Control Plane. Check this device's internet connection and try again." :
        r.code === "unavailable" ? "RoofSpan Mobile pairing is temporarily unavailable. Please try again shortly." :
        "Pairing didn't work. Please generate a new code and try again.";
      Alert.alert("Couldn't connect", msg);
      setScanned(false);
    }
    // On success, PairingProvider advances the app to Sign In automatically.
  };

  const onScan = ({ data }) => {
    if (scanned || busy) return;
    setScanned(true);
    const parsed = parseQrPayload(data);
    if (!parsed.ok) {
      const m =
        parsed.reason === "protocol" ? "This QR code isn't compatible with this version of RoofSpan. Please update the app." :
        parsed.reason === "expired" ? "This pairing code has expired. Generate a new code in RoofSpan Office." :
        "That doesn't look like a RoofSpan pairing QR code.";
      Alert.alert("Invalid code", m, [{ text: "OK", onPress: () => setScanned(false) }]);
      return;
    }
    submit({ token: parsed.payload.token });
  };

  if (mode === "choose") {
    return (
      <View style={s.wrap}>
        <Text style={s.h}>Connect this device</Text>
        <Text style={s.sub}>Scan the QR code shown in RoofSpan Office, or enter its six-digit fallback code.</Text>
        <TouchableOpacity style={s.btn} onPress={() => setMode("scan")} testID="scan-qr-btn">
          <Text style={s.btnText}>Scan QR Code</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[s.btn, s.btnAlt]} onPress={() => setMode("code")} testID="enter-code-btn">
          <Text style={[s.btnText, { color: C.brand }]}>Enter Pairing Code</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (mode === "scan") {
    if (!permission) return <View style={s.wrap}><ActivityIndicator color="#fff" /></View>;
    if (!permission.granted) {
      return (
        <View style={s.wrap}>
          <Text style={s.h}>Camera access</Text>
          <Text style={s.sub}>RoofSpan needs your camera to scan the pairing QR code shown in RoofSpan Office.</Text>
          {permission.canAskAgain ? (
            <TouchableOpacity style={s.btn} onPress={requestPermission} testID="grant-camera-btn">
              <Text style={s.btnText}>Allow Camera</Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity style={s.btn} onPress={() => Linking.openSettings()} testID="open-settings-btn">
              <Text style={s.btnText}>Open Settings</Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity style={[s.btn, s.btnAlt]} onPress={() => setMode("code")}>
            <Text style={[s.btnText, { color: C.brand }]}>Enter Pairing Code instead</Text>
          </TouchableOpacity>
        </View>
      );
    }
    return (
      <View style={{ flex: 1, backgroundColor: "#000" }}>
        <CameraView
          style={{ flex: 1 }}
          barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
          onBarcodeScanned={scanned ? undefined : onScan}
          testID="qr-camera"
        />
        <View style={s.scanFoot}>
          {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", textAlign: "center" }}>Point at the RoofSpan pairing QR code</Text>}
          <TouchableOpacity style={[s.btn, s.btnAlt, { marginTop: 12 }]} onPress={() => setMode("code")}>
            <Text style={[s.btnText, { color: C.brand }]}>Enter Pairing Code instead</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  const valid = isValidNumericCode(code);
  return (
    <View style={s.wrap}>
      <Text style={s.h}>Enter Pairing Code</Text>
      <Text style={s.sub}>Type the six-digit code currently shown in RoofSpan Office.</Text>
      <TextInput
        style={s.codeInput}
        placeholder="000 000"
        placeholderTextColor="#64748B"
        keyboardType="number-pad"
        value={formatNumericCode(code)}
        onChangeText={(t) => setCode(normalizeNumericCode(t))}
        maxLength={7}
        testID="pairing-code-input"
      />
      <TouchableOpacity
        style={[s.btn, !valid && { opacity: 0.5 }]}
        disabled={!valid || busy}
        onPress={() => submit({ numeric_code: code })}
        testID="pairing-code-submit"
      >
        <Text style={s.btnText}>{busy ? "Connecting…" : "Connect"}</Text>
      </TouchableOpacity>
      <TouchableOpacity style={[s.btn, s.btnAlt]} onPress={() => setMode("scan")}>
        <Text style={[s.btnText, { color: C.brand }]}>Scan QR Code instead</Text>
      </TouchableOpacity>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, padding: 28, justifyContent: "center", backgroundColor: C.bg },
  h: { color: "#fff", fontSize: 26, fontWeight: "800" },
  sub: { color: "#94A3B8", fontSize: 15, lineHeight: 22, marginTop: 10, marginBottom: 28 },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 18, alignItems: "center", marginTop: 12 },
  btnAlt: { backgroundColor: "#fff" },
  btnText: { color: "#fff", fontSize: 18, fontWeight: "700" },
  codeInput: { backgroundColor: "#fff", borderRadius: 12, padding: 18, fontSize: 28, letterSpacing: 6, textAlign: "center", marginBottom: 8 },
  scanFoot: { position: "absolute", bottom: 40, left: 24, right: 24 },
});
