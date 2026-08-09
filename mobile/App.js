import React, { useEffect, useState } from "react";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { AuthProvider, useAuth } from "./src/auth";
import { PairingProvider, usePairing } from "./src/pairingContext";
import { STATES, COPY } from "./src/connectionState";
import { startAutoSync } from "./src/sync";
import { C } from "./src/theme";
import Login from "./src/screens/Login";
import Welcome from "./src/screens/Welcome";
import Connect from "./src/screens/Connect";
import { SubscriptionLock, DeviceRevoked, ServerUnavailable, UpdateRequired, OptionalUpdateBanner } from "./src/screens/StatusScreens";
import Home from "./src/screens/Home";
import Leads from "./src/screens/Leads";
import LeadDetail from "./src/screens/LeadDetail";
import MapScreen from "./src/screens/MapScreen";
import Jobs from "./src/screens/Jobs";
import JobDetail from "./src/screens/JobDetail";
import Inspection from "./src/screens/Inspection";
import More from "./src/screens/More";

const Tab = createBottomTabNavigator();
const LeadStack = createNativeStackNavigator();
const JobStack = createNativeStackNavigator();
const PairStack = createNativeStackNavigator();

function LeadsNav() {
  return (
    <LeadStack.Navigator>
      <LeadStack.Screen name="Leads" component={Leads} />
      <LeadStack.Screen name="LeadDetail" component={LeadDetail} options={{ title: "Lead" }} />
      <LeadStack.Screen name="Inspection" component={Inspection} />
    </LeadStack.Navigator>
  );
}
function JobsNav() {
  return (
    <JobStack.Navigator>
      <JobStack.Screen name="Jobs" component={Jobs} />
      <JobStack.Screen name="JobDetail" component={JobDetail} options={{ title: "Job" }} />
    </JobStack.Navigator>
  );
}

function PairingFlow() {
  return (
    <PairStack.Navigator screenOptions={{ headerShown: false }}>
      <PairStack.Screen name="Welcome" component={Welcome} />
      <PairStack.Screen name="Connect" component={Connect} />
    </PairStack.Navigator>
  );
}

function Spinner({ label }) {
  return (
    <View style={s.center}>
      <ActivityIndicator color={C.brand} />
      {label ? <Text style={s.spin}>{label}</Text> : null}
    </View>
  );
}

function ConnBanner() {
  const { conn } = usePairing();
  if (conn === STATES.CONNECTED) return null;
  const label = conn === STATES.RECONNECTING ? "Reconnecting…" :
    (COPY[conn] && COPY[conn].title) || "Working offline";
  return <View style={s.connBanner}><Text style={s.connText}>{label}</Text></View>;
}

function MainApp() {
  const { optionalUpdate } = usePairing();
  const [dismissedUpdate, setDismissedUpdate] = useState(false);
  useEffect(() => {
    const unsub = startAutoSync();
    return () => unsub && unsub();
  }, []);
  return (
    <View style={{ flex: 1 }}>
      <ConnBanner />
      {optionalUpdate && !dismissedUpdate ? <OptionalUpdateBanner onDismiss={() => setDismissedUpdate(true)} /> : null}
      <Tab.Navigator
        screenOptions={({ route }) => ({
          headerShown: true,
          tabBarActiveTintColor: C.brand,
          tabBarInactiveTintColor: "#64748B",
          tabBarIcon: ({ color, size, focused }) => {
            const icons = {
              Home: focused ? "home" : "home-outline",
              LeadsTab: focused ? "people" : "people-outline",
              Map: focused ? "map" : "map-outline",
              JobsTab: focused ? "briefcase" : "briefcase-outline",
              More: focused ? "ellipsis-horizontal-circle" : "ellipsis-horizontal-circle-outline",
            };
            return <Ionicons name={icons[route.name] || "ellipse-outline"} size={size} color={color} />;
          },
        })}
      >
        <Tab.Screen name="Home" component={Home} />
        <Tab.Screen name="LeadsTab" component={LeadsNav} options={{ title: "Leads", headerShown: false }} />
        <Tab.Screen name="Map" component={MapScreen} />
        <Tab.Screen name="JobsTab" component={JobsNav} options={{ title: "Jobs", headerShown: false }} />
        <Tab.Screen name="More" component={More} />
      </Tab.Navigator>
    </View>
  );
}

function Root() {
  const { ready: pReady, isPaired, conn } = usePairing();
  const { user, ready: aReady } = useAuth();

  if (!pReady || !aReady) return <Spinner />;
  if (!isPaired) return <PairingFlow />;

  // Hard blocks (apply even when signed in) — never bypass to field workflows.
  if (conn === STATES.UPDATE_REQUIRED) return <UpdateRequired />;
  if (conn === STATES.SUBSCRIPTION_INACTIVE) return <SubscriptionLock />;
  if (conn === STATES.DEVICE_REVOKED) return <DeviceRevoked />;

  if (!user) {
    // Sign-in needs the relay; surface connectivity before showing the form.
    if (conn === STATES.CONNECTING) return <Spinner label="Connecting…" />;
    if (conn === STATES.SERVER_UNAVAILABLE || conn === STATES.OFFLINE) return <ServerUnavailable />;
    return <Login />;
  }
  // Signed in: offline-first — keep the app usable through transient connectivity issues.
  return <MainApp />;
}

export default function App() {
  return (
    <PairingProvider>
      <AuthProvider>
        <StatusBar style="light" />
        <NavigationContainer>
          <Root />
        </NavigationContainer>
      </AuthProvider>
    </PairingProvider>
  );
}

const s = StyleSheet.create({
  center: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: C.bg },
  spin: { color: "#94A3B8", marginTop: 12 },
  connBanner: { backgroundColor: C.warn, paddingVertical: 6, alignItems: "center" },
  connText: { color: "#fff", fontSize: 13, fontWeight: "600" },
});
