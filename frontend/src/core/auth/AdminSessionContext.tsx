import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

type LoginResult = {
  ok: boolean;
  error?: string;
};

type AdminSessionContextValue = {
  ready: boolean;
  authenticated: boolean;
  refresh: () => Promise<void>;
  login: (token: string) => Promise<LoginResult>;
  logout: () => Promise<void>;
};

const AdminSessionContext = createContext<AdminSessionContextValue | null>(null);

async function fetchSessionStatus(): Promise<boolean> {
  const res = await fetch("/api/admin/session/status", {
    credentials: "include",
  });
  if (!res.ok) {
    return false;
  }
  const payload = (await res.json()) as { authenticated?: boolean };
  return !!payload.authenticated;
}

export function AdminSessionProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const isAuthed = await fetchSessionStatus();
      setAuthenticated(isAuthed);
    } finally {
      setReady(true);
    }
  }, []);

  const login = useCallback(async (token: string): Promise<LoginResult> => {
    try {
      const res = await fetch("/api/admin/session/login", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ token }),
      });
      if (!res.ok) {
        const text = await res.text();
        return { ok: false, error: text || `HTTP ${res.status}` };
      }
      setAuthenticated(true);
      return { ok: true };
    } catch (e: any) {
      return { ok: false, error: e?.message ?? String(e) };
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/admin/session/logout", {
        method: "POST",
        credentials: "include",
      });
    } finally {
      setAuthenticated(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const value = useMemo(
    () => ({ ready, authenticated, refresh, login, logout }),
    [authenticated, login, logout, ready, refresh],
  );

  return <AdminSessionContext.Provider value={value}>{children}</AdminSessionContext.Provider>;
}

export function useAdminSession(): AdminSessionContextValue {
  const ctx = useContext(AdminSessionContext);
  if (!ctx) {
    throw new Error("useAdminSession must be used within AdminSessionProvider");
  }
  return ctx;
}
