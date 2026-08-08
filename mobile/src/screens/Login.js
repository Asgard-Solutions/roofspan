import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useAuth } from "../auth";
import { C } from "../theme";

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async () => {
    setBusy(true);
    try {
      await login(email.trim(), password);
    } catch (e) {
      Alert.alert("Sign in failed", "Check your email and password.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={s.wrap}>
      <Text style={s.brand}>RoofSpan</Text>
      <Text style={s.sub}>Field</Text>
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
  brand: { color: "#fff", fontSize: 40, fontWeight: "800" },
  sub: { color: C.brand, fontSize: 20, fontWeight: "700", marginBottom: 28 },
  input: { backgroundColor: "#fff", borderRadius: 12, padding: 16, fontSize: 18, marginBottom: 14 },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 18, alignItems: "center", marginTop: 6 },
  btnText: { color: "#fff", fontSize: 18, fontWeight: "700" },
});
