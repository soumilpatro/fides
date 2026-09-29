"use client";
import { createContext, type ReactNode } from "react";
import type { AuthState } from "./auth.types";

export const AuthContext = createContext<AuthState | undefined>(undefined);
const anonymous: AuthState = { status: "anonymous" };
/** Controlled seam only. F1 will connect a reviewed session implementation. */
export function AuthProvider({
  children,
  state = anonymous,
}: {
  children: ReactNode;
  state?: AuthState;
}) {
  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}
