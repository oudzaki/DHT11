import axios from "axios";
import type { TokenPair } from "../types";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

// Client authentifié (Bearer) — pour routes protégées
const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: false,
  timeout: 10000,
});

// Client public — pour routes AllowAny (readings)
export const pub = axios.create({
  baseURL: BASE_URL,
  withCredentials: false,
  timeout: 10000,
});

export function getTokens(): TokenPair | null {
  const access = localStorage.getItem("access_token");
  const refresh = localStorage.getItem("refresh_token");
  if (access && refresh) return { access, refresh };
  return null;
}

export function setTokens(tokens: TokenPair | null) {
  if (!tokens) {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
  } else {
    localStorage.setItem("access_token", tokens.access);
    localStorage.setItem("refresh_token", tokens.refresh);
  }
}

// Interceptor d'auth UNIQUEMENT pour `api` (pas pour `pub`)
api.interceptors.request.use((config) => {
  const tk = getTokens();
  if (tk?.access) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${tk.access}`;
  }
  return config;
});

console.log("API baseURL =", BASE_URL);

// ✅ on garde `api` en export par défaut pour compat avec auth.ts
export default api;
