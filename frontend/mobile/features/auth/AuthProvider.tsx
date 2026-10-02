import { createContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { AppState } from "react-native";
import { createAuthApi, type AuthApi } from "@fides/shared/api/auth";
import { AuthSession, type AuthState } from "@fides/shared/auth/session";
import { secureSessionStore } from "./session/session-store";
export interface AuthContextValue { state: AuthState; session: AuthSession; api: AuthApi }
export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [services] = useState(() => {
    const baseUrl = process.env.EXPO_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    const api = createAuthApi({ baseUrl, accessToken: () => session.accessToken() });
    const session = new AuthSession(secureSessionStore(), api);
    return { session, api };
  });
  const state = useSyncExternalStore(services.session.subscribe, services.session.snapshot, services.session.snapshot);
  useEffect(() => { void services.session.bootstrap(); }, [services]);
  useEffect(() => {
    const subscription = AppState.addEventListener("change", value => {
      // Returning from the SMS app must not unmount an anonymous OTP flow.
      if (value === "active" && services.session.snapshot().status === "authenticated")
        void services.session.bootstrap();
    });
    return () => subscription.remove();
  }, [services]);
  useEffect(() => {
    if (state.status !== "authenticated") return;
    const expires = services.session.expiresAt();
    if (!expires) return;
    const timer = setTimeout(() => { void services.session.refresh(); }, Math.max(0, Date.parse(expires) - Date.now()));
    return () => clearTimeout(timer);
  }, [services, state]);
  return <AuthContext.Provider value={{ ...services, state }}>{children}</AuthContext.Provider>;
}
