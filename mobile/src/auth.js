import React, { createContext, useContext, useEffect, useState } from "react";
import * as SecureStore from "expo-secure-store";
import axios from "axios";
import { API } from "./config";
import { signInThroughRelay } from "./relay";
import { setUserScope } from "./storage";

const TOKEN_KEY = "roofspan_token";
const REFRESH_KEY = "roofspan_refresh";
const USER_KEY = "roofspan_user";
const AuthCtx = createContext(null);

export async function getToken() {
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export async function getRefreshToken() {
  return SecureStore.getItemAsync(REFRESH_KEY);
}

// Persist a fresh token pair (used by silent refresh). Missing values are left untouched.
export async function saveTokens({ access_token, refresh_token } = {}) {
  if (access_token) await SecureStore.setItemAsync(TOKEN_KEY, access_token);
  if (refresh_token) await SecureStore.setItemAsync(REFRESH_KEY, refresh_token);
}

export async function clearTokens() {
  await SecureStore.deleteItemAsync(TOKEN_KEY);
  await SecureStore.deleteItemAsync(REFRESH_KEY);
}

// Module-level hook so non-React code (the networking layer) can force a sign-out when a refresh
// token is finally rejected. The AuthProvider registers a handler that clears the signed-in user,
// which routes the app back to the Login screen. Pending offline work is preserved.
let _onSessionExpired = null;
export function setSessionExpiredHandler(cb) { _onSessionExpired = cb; }
export function notifySessionExpired() { if (_onSessionExpired) { try { _onSessionExpired(); } catch (e) {} } }

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      const raw = await SecureStore.getItemAsync(USER_KEY);
      if (raw) { const u = JSON.parse(raw); setUserScope(u.id); setUser(u); }
      setReady(true);
    })();
  }, []);

  // When a refresh finally fails, drop the session (keep offline queue) so the app shows sign-in.
  useEffect(() => {
    setSessionExpiredHandler(() => { setUserScope(null); setUser(null); });
    return () => setSessionExpiredHandler(null);
  }, []);

  const _persist = async (access_token, refresh_token, u) => {
    await SecureStore.setItemAsync(TOKEN_KEY, access_token); // secure device storage
    if (refresh_token) await SecureStore.setItemAsync(REFRESH_KEY, refresh_token);
    await SecureStore.setItemAsync(USER_KEY, JSON.stringify(u));
    setUserScope(u.id); // scope cache + queue to this signed-in salesperson (data isolation §29)
    setUser(u);
    // Kick a sync so any work queued while signed out (or after a session expiry) flushes now.
    try { require("./sync").syncNow(); } catch (e) { /* sync module not ready */ }
    return u;
  };

  const login = async (email, password) => {
    const r = await axios.post(`${API}/auth/login`, { email, password });
    return _persist(r.data.access_token, r.data.refresh_token, r.data.user);
  };

  // Sign in with the local RoofSpan account, transported THROUGH the relay to the local FastAPI.
  const loginViaRelay = async (pairing, email, password) => {
    const r = await signInThroughRelay(pairing, email, password);
    if (!r.ok || !r.data || !r.data.access_token) {
      const err = new Error("relay_login_failed");
      err.code = r.code || (r.status === 401 ? "bad_credentials" : "error");
      throw err;
    }
    return _persist(r.data.access_token, r.data.refresh_token, r.data.user);
  };

  const logout = async () => {
    await clearTokens();
    await SecureStore.deleteItemAsync(USER_KEY);
    setUserScope(null); // stop exposing this user's scoped cache; pending work is retained, not dropped
    setUser(null);
  };

  return <AuthCtx.Provider value={{ user, ready, login, loginViaRelay, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
