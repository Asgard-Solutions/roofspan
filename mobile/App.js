import React, { useEffect } from "react";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator, View, Text } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { AuthProvider, useAuth } from "./src/auth";
import { startAutoSync } from "./src/sync";
import { C } from "./src/theme";
import Login from "./src/screens/Login";
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

function Shell() {
  const { user, ready } = useAuth();
  useEffect(() => {
    const unsub = startAutoSync();
    return () => unsub && unsub();
  }, []);
  if (!ready)
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>
        <ActivityIndicator />
      </View>
    );
  if (!user) return <Login />;
  return (
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
  );
}

export default function App() {
  return (
    <AuthProvider>
      <StatusBar style="dark" />
      <NavigationContainer>
        <Shell />
      </NavigationContainer>
    </AuthProvider>
  );
}
