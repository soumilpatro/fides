"use client";
import { createContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";

import { createAuthApi, type AuthApi } from "@fides/shared/api/auth";
import { AuthSession, type AuthState } from "@fides/shared/auth/session";
import { createConnectionsApi, type ConnectionsApi } from "@fides/shared/api/connections";
import { createCommitmentsApi, type CommitmentsApi } from "@fides/shared/api/commitments";
import { createRepaymentsApi, type RepaymentsApi } from "@fides/shared/api/repayments";
import { MutationIntents } from "@fides/shared/commitments/intents";
import { memorySessionStore } from "./session/session-store";
export interface AuthContextValue { state: AuthState; session: AuthSession; api: AuthApi; connections: ConnectionsApi; commitments: CommitmentsApi; repayments: RepaymentsApi; intents: MutationIntents }
export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [services] = useState(() => {
    const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const baseUrl = new URL(process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1", origin).href;
    const api = createAuthApi({ baseUrl, accessToken: () => session.accessToken() });
    const session = new AuthSession(memorySessionStore(), api);
    const connections = createConnectionsApi({ baseUrl, accessToken: session.accessToken });
    return { session, api, connections, commitments: createCommitmentsApi({ baseUrl, accessToken: session.accessToken }), repayments: createRepaymentsApi({ baseUrl, accessToken: session.accessToken }), intents: new MutationIntents() };
  });
  const state = useSyncExternalStore(services.session.subscribe, services.session.snapshot, services.session.snapshot);
  useEffect(() => { void services.session.bootstrap(); }, [services]);

  useEffect(() => {
    if (state.status !== "authenticated") return;
    const expires = services.session.expiresAt();
    if (!expires) return;
    const timer = setTimeout(() => { void services.session.refresh(); }, Math.max(0, Date.parse(expires) - Date.now()));
    return () => clearTimeout(timer);
  }, [services, state]);
  return <AuthContext.Provider value={{ ...services, state }}>{children}</AuthContext.Provider>;
}
