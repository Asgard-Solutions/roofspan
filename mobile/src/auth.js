import React, { createContext, useContext, useEffect, useState } from "react";
import * as SecureStore from "expo-secure-store";
import axios from "axios";
import { API } from "./config";

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

  const login = async (email, password) => {
    const r = await axios.post(`${API}/auth/login`, { email, password });
    const { access_token, user: u } = r.data;
    await SecureStore.setItemAsync(TOKEN_KEY, access_token); // secure device storage
    await SecureStore.setItemAsync(USER_KEY, JSON.stringify(u));
    setUser(u);
    return u;
  };

  const logout = async () => {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    await SecureStore.deleteItemAsync(USER_KEY);
    setUser(null);
  };

  return <AuthCtx.Provider value={{ user, ready, login, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
