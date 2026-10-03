"use client";
import { createContext, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";

import { createAuthApi, type AuthApi } from "@fides/shared/api/auth";
import { AuthSession, type AuthState } from "@fides/shared/auth/session";
import { createConnectionsApi, type ConnectionsApi } from "@fides/shared/api/connections";
import { createCommitmentsApi, type CommitmentsApi } from "@fides/shared/api/commitments";
import { createRepaymentsApi, type RepaymentsApi } from "@fides/shared/api/repayments";
import { createDashboardApi, type DashboardApi } from "@fides/shared/api/dashboard";
import { createLedgerApi, type LedgerApi } from "@fides/shared/api/ledger";
import { createExtensionsApi, type ExtensionsApi } from "@fides/shared/api/extensions";
import { createNotificationsApi, type NotificationsApi } from "@fides/shared/api/notifications";
import { createProfileApi, type ProfileApi } from "@fides/shared/api/profile";
import { createNotificationPreferencesApi, type NotificationPreferencesApi } from "@fides/shared/api/notification-preferences";
import { createDueSummariesApi, type DueSummariesApi } from "@fides/shared/api/due-summaries";
import { createMutualClosureApi, type MutualClosureApi } from "@fides/shared/api/mutual-closure";
import { MutationIntents } from "@fides/shared/commitments/intents";
import { memorySessionStore } from "./session/session-store";
export interface AuthContextValue { state: AuthState; session: AuthSession; api: AuthApi; connections: ConnectionsApi; commitments: CommitmentsApi; repayments: RepaymentsApi; dashboard: DashboardApi; ledger: LedgerApi; extensions: ExtensionsApi; notifications: NotificationsApi; profile: ProfileApi; notificationPreferences: NotificationPreferencesApi; dueSummaries: DueSummariesApi; mutualClosure: MutualClosureApi; intents: MutationIntents }
export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [services] = useState(() => {
    const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const baseUrl = new URL(process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1", origin).href;
    const api = createAuthApi({ baseUrl, accessToken: () => session.accessToken() });
    const session = new AuthSession(memorySessionStore(), api);
    const connections = createConnectionsApi({ baseUrl, accessToken: session.accessToken });
    return { session, api, connections, commitments: createCommitmentsApi({ baseUrl, accessToken: session.accessToken }), repayments: createRepaymentsApi({ baseUrl, accessToken: session.accessToken }), dashboard: createDashboardApi({ baseUrl, accessToken: session.accessToken }), ledger: createLedgerApi({ baseUrl, accessToken: session.accessToken }), extensions: createExtensionsApi({baseUrl,accessToken:session.accessToken}), notifications:createNotificationsApi({baseUrl,accessToken:session.accessToken}), profile:createProfileApi({baseUrl,accessToken:session.accessToken}), notificationPreferences:createNotificationPreferencesApi({baseUrl,accessToken:session.accessToken}), dueSummaries:createDueSummariesApi({baseUrl,accessToken:session.accessToken}), mutualClosure:createMutualClosureApi({baseUrl,accessToken:session.accessToken}), intents: new MutationIntents() };
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
