import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Alert, Image } from "react-native";
import { useAuth } from "../auth";
import { usePairing } from "../pairingContext";
import { C } from "../theme";

export default function Login() {
  const { login, loginViaRelay } = useAuth();
  const { pairing } = usePairing();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async () => {
    setBusy(true);
    try {
      // Paired devices transport credentials through the relay to the local RoofSpan server.
      if (pairing) await loginViaRelay(pairing, email.trim(), password);
      else await login(email.trim(), password);
    } catch (e) {
      const msg = e && e.code === "bad_credentials" ? "Check your email and password."
        : e && (e.code === "tunnel_unavailable" || e.code === "request_timeout")
          ? "Can't reach your company's RoofSpan system right now. Please try again shortly."
          : "Check your email and password.";
      Alert.alert("Sign in failed", msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={s.wrap}>
      <Image source={require("../../assets/icon.png")} style={s.logo} resizeMode="cover" />
      <Text style={s.brand}>RoofSpan</Text>
      <Text style={s.sub}>Field</Text>
      <Text style={s.tag}>Sign in to your RoofSpan account</Text>
      <TextInput style={s.input} placeholder="Email" autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} testID="login-email" />
      <TextInput style={s.input} placeholder="Password" secureTextEntry value={password} onChangeText={setPassword} testID="login-password" />
      <TouchableOpacity style={s.btn} onPress={onSubmit} disabled={busy} testID="login-submit">
        <Text style={s.btnText}>{busy ? "Signing in…" : "Sign in"}</Text>
      </TouchableOpacity>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, padding: 28, justifyContent: "center", backgroundColor: C.bg },
  logo: { width: 96, height: 96, borderRadius: 22, marginBottom: 18 },
  brand: { color: "#fff", fontSize: 40, fontWeight: "800" },
  sub: { color: C.brand, fontSize: 20, fontWeight: "700" },
  tag: { color: "#94A3B8", fontSize: 14, marginTop: 6, marginBottom: 28 },
  input: { backgroundColor: "#fff", borderRadius: 12, padding: 16, fontSize: 18, marginBottom: 14 },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 18, alignItems: "center", marginTop: 6 },
  btnText: { color: "#fff", fontSize: 18, fontWeight: "700" },
});
