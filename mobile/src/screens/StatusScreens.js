import React from "react";
import { View, Text, TouchableOpacity, StyleSheet, Linking, Platform } from "react-native";
import { C } from "../theme";
import { usePairing } from "../pairingContext";
import { COPY, STATES } from "../connectionState";

function Screen({ title, message, actionLabel, onAction, secondaryLabel, onSecondary, helper, tone = C.brand, testID, secondaryTestID }) {
  return (
    <View style={s.wrap}>
      <Text style={s.h}>{title}</Text>
      <Text style={s.msg}>{message}</Text>
      {actionLabel ? (
        <TouchableOpacity style={[s.btn, { backgroundColor: tone }]} onPress={onAction} testID={testID}>
          <Text style={s.btnText}>{actionLabel}</Text>
        </TouchableOpacity>
      ) : null}
      {secondaryLabel ? (
        <TouchableOpacity style={s.btnSecondary} onPress={onSecondary} testID={secondaryTestID}>
          <Text style={s.btnSecondaryText}>{secondaryLabel}</Text>
        </TouchableOpacity>
      ) : null}
      {helper ? <Text style={s.helper}>{helper}</Text> : null}
    </View>
  );
}

export function SubscriptionLock() {
  const { retry } = usePairing();
  const c = COPY[STATES.SUBSCRIPTION_INACTIVE];
  return (
    <Screen
      title={c.title}
      message={c.message}
      actionLabel="Try Again"
      onAction={retry}
      helper="Owners and administrators can manage the subscription from RoofSpan Office on the company's Windows computer. If you're a field user, contact your RoofSpan administrator."
      testID="subscription-lock-retry"
    />
  );
}

export function DeviceRevoked() {
  const { unpair } = usePairing();
  const c = COPY[STATES.DEVICE_REVOKED];
  return <Screen title={c.title} message={c.message} actionLabel="Reconnect Device" onAction={unpair} tone={C.brand} testID="device-revoked-reconnect" />;
}

export function ServerUnavailable() {
  const { retry, conn } = usePairing();
  const c = COPY[conn === STATES.OFFLINE ? STATES.OFFLINE : STATES.SERVER_UNAVAILABLE];
  return <Screen title={c.title} message={c.message} actionLabel="Try Again" onAction={retry} tone={C.warn} testID="server-unavailable-retry" />;
}

export function UpdateRequired() {
  const c = COPY[STATES.UPDATE_REQUIRED];
  const open = () => {
    const url = Platform.OS === "ios" ? "https://apps.apple.com/app/roofspan" : "https://play.google.com/store/apps/details?id=com.roofspan.mobile";
    Linking.openURL(url).catch(() => {});
  };
  return <Screen title={c.title} message={c.message} actionLabel="Update App" onAction={open} testID="update-required-btn" />;
}

// Non-blocking optional-update banner (shown once per session over the main app).
export function OptionalUpdateBanner({ onDismiss }) {
  const open = () => {
    const url = Platform.OS === "ios" ? "https://apps.apple.com/app/roofspan" : "https://play.google.com/store/apps/details?id=com.roofspan.mobile";
    Linking.openURL(url).catch(() => {});
  };
  return (
    <View style={s.banner}>
      <Text style={s.bannerText}>RoofSpan update available</Text>
      <View style={{ flexDirection: "row" }}>
        <TouchableOpacity onPress={open} testID="optional-update-btn"><Text style={s.bannerAction}>Update</Text></TouchableOpacity>
        <TouchableOpacity onPress={onDismiss} testID="optional-update-dismiss"><Text style={[s.bannerAction, { color: "#94A3B8" }]}>Not Now</Text></TouchableOpacity>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, padding: 28, justifyContent: "center", backgroundColor: C.bg },
  h: { color: "#fff", fontSize: 26, fontWeight: "800" },
  msg: { color: "#94A3B8", fontSize: 16, lineHeight: 24, marginTop: 14, marginBottom: 30 },
  btn: { borderRadius: 12, padding: 18, alignItems: "center" },
  btnText: { color: "#fff", fontSize: 18, fontWeight: "700" },
  btnSecondary: { borderRadius: 12, padding: 16, alignItems: "center", marginTop: 12, borderWidth: 1, borderColor: "#334155" },
  btnSecondaryText: { color: "#E2E8F0", fontSize: 16, fontWeight: "700" },
  helper: { color: "#64748B", fontSize: 13, lineHeight: 20, marginTop: 18, textAlign: "center" },
  banner: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", backgroundColor: "#1E293B", paddingHorizontal: 16, paddingVertical: 10 },
  bannerText: { color: "#fff", fontWeight: "700" },
  bannerAction: { color: C.brand, fontWeight: "700", marginLeft: 18 },
});
