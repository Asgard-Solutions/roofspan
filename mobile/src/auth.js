import React, { createContext, useContext, useEffect, useState } from "react";
import * as SecureStore from "expo-secure-store";
import axios from "axios";
import { API } from "./config";
import { signInThroughRelay } from "./relay";

const TOKEN_KEY = "roofspan_token";
const USER_KEY = "roofspan_user";
const AuthCtx = createContext(null);

export async function getToken() {
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      const raw = await SecureStore.getItemAsync(USER_KEY);
      if (raw) setUser(JSON.parse(raw));
      setReady(true);
    })();
  }, []);

  const _persist = async (access_token, u) => {
    await SecureStore.setItemAsync(TOKEN_KEY, access_token); // secure device storage
    await SecureStore.setItemAsync(USER_KEY, JSON.stringify(u));
    setUser(u);
    return u;
  };

  const login = async (email, password) => {
    const r = await axios.post(`${API}/auth/login`, { email, password });
    return _persist(r.data.access_token, r.data.user);
  };

  // Sign in with the local RoofSpan account, transported THROUGH the relay to the local FastAPI.
  const loginViaRelay = async (pairing, email, password) => {
    const r = await signInThroughRelay(pairing, email, password);
    if (!r.ok || !r.data || !r.data.access_token) {
      const err = new Error("relay_login_failed");
      err.code = r.code || (r.status === 401 ? "bad_credentials" : "error");
      throw err;
    }
    return _persist(r.data.access_token, r.data.user);
  };

  const logout = async () => {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    await SecureStore.deleteItemAsync(USER_KEY);
    setUser(null);
  };

  return <AuthCtx.Provider value={{ user, ready, login, loginViaRelay, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
