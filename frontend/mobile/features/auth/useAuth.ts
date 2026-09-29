"use client";
import { useContext } from "react";
import { AuthContext } from "./AuthProvider";
export function useAuth() {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth requires AuthProvider");
  return state;
}
