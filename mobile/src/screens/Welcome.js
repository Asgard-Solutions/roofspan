import React from "react";
import { View, Text, TouchableOpacity, StyleSheet, Image } from "react-native";
import { C } from "../theme";

export default function Welcome({ navigation }) {
  return (
    <View style={s.wrap}>
      <Image source={require("../../assets/icon.png")} style={s.logo} resizeMode="cover" />
      <Text style={s.brand}>Welcome to RoofSpan</Text>
      <Text style={s.tag}>
        RoofSpan Mobile connects to your company's RoofSpan system. Your company administrator must
        set up RoofSpan Office and create your account before you can sign in.
      </Text>
      <TouchableOpacity style={s.btn} onPress={() => navigation.navigate("Connect")} testID="connect-to-roofspan">
        <Text style={s.btnText}>Connect to RoofSpan</Text>
      </TouchableOpacity>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, padding: 28, justifyContent: "center", backgroundColor: C.bg },
  logo: { width: 88, height: 88, borderRadius: 20, marginBottom: 22, alignSelf: "flex-start" },
  brand: { color: "#fff", fontSize: 34, fontWeight: "800" },
  tag: { color: "#94A3B8", fontSize: 16, lineHeight: 24, marginTop: 14, marginBottom: 36 },
  btn: { backgroundColor: C.brand, borderRadius: 12, padding: 18, alignItems: "center" },
  btnText: { color: "#fff", fontSize: 18, fontWeight: "700" },
});
