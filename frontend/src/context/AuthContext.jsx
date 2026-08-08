import { createContext, useContext, useEffect, useState } from "react";
import { api, setToken, clearToken, getToken } from "@/lib/api";

const AuthContext = createContext(null);
const SENSITIVE = ["owner", "administrator"];

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = loading

  useEffect(() => {
    const t = getToken();
    if (!t) {
      setUser(null);
      return;
    }
    api
      .get("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => {
        clearToken();
        setUser(null);
      });
  }, []);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    setToken(data.access_token);
    setUser(data.user);
    return data.user;
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch (e) {
      // ignore
    }
    clearToken();
    setUser(null);
  };

  const isSensitive = !!user && SENSITIVE.includes(user.role);

  return (
    <AuthContext.Provider value={{ user, login, logout, isSensitive }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
