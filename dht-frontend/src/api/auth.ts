import api, { setTokens, getTokens } from "./client";
import type { TokenPair } from "../types";

export async function login(username: string, password: string): Promise<void> {
  const { data } = await api.post<TokenPair>("/api/auth/token/", { username, password });
  setTokens(data);
}

export async function refreshToken(): Promise<boolean> {
  const tk = getTokens();
  if (!tk?.refresh) return false;
  try {
    const { data } = await api.post<Pick<TokenPair, "access">>("/api/auth/refresh/", {
      refresh: tk.refresh,
    });
    setTokens({ access: data.access, refresh: tk.refresh });
    return true;
  } catch {
    setTokens(null);
    return false;
  }
}
