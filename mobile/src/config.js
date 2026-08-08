import Constants from "expo-constants";

export const API_BASE =
  process.env.EXPO_PUBLIC_API_BASE ||
  (Constants.expoConfig && Constants.expoConfig.extra && Constants.expoConfig.extra.apiBase) ||
  "https://field-photo-capture.preview.emergentagent.com";

export const API = `${API_BASE}/api`;
