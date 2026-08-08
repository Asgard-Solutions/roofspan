import Constants from "expo-constants";

export const API_BASE =
  (Constants.expoConfig && Constants.expoConfig.extra && Constants.expoConfig.extra.apiBase) ||
  process.env.EXPO_PUBLIC_API_BASE ||
  "https://roofspan-core.preview.emergentagent.com";

export const API = `${API_BASE}/api`;
