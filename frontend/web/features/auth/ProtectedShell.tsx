"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Brand } from "../../components/Brand";
import { Button, LoadingState, Screen } from "../../components/ui";
import { useAuth } from "./useAuth";
const destinations = [["overview", "Overview"], ["connections", "Connections"], ["activity", "Activity"], ["notifications", "Notifications"], ["profile", "Profile / Settings"]];
export function ProtectedShell({ children }: { children: ReactNode }) {
  const { state, session } = useAuth(); const router = useRouter(); const path = usePathname();
  useEffect(() => { if (state.status === "anonymous") router.replace("/"); }, [state, router]);
  if (state.status !== "authenticated") return <main className="auth-page"><LoadingState message="Resolving your session…" /></main>;
  return <div className="app-shell"><a className="skip-link" href="#main-content">Skip to content</a>
    <aside className="sidebar"><Link href="/app/overview"><Brand /></Link>
      <nav aria-label="Fides">{destinations.map(([route, label]) => <Link key={route} href={`/app/${route}`} aria-current={((route === "overview" && path.startsWith("/app/commitments")) || path === `/app/${route}` || path.startsWith(`/app/${route}/`)) ? "page" : undefined}>{label}</Link>)}</nav>
      <div className="sidebar-footer"><p>{state.user.display_name}</p><Button variant="quiet" onClick={() => void session.logout()}>Log out</Button></div>
    </aside><Screen>{children}</Screen></div>;
}
