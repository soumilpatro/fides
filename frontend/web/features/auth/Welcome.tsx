"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Brand } from "../../components/Brand";
import { Button, LoadingState } from "../../components/ui";
import { useAuth } from "./useAuth";
export function Welcome() {
  const { state, session } = useAuth();
  const router = useRouter();
  useEffect(() => { if (state.status === "authenticated") router.replace("/app/overview"); }, [state, router]);
  if (state.status !== "anonymous") return <main className="auth-page"><Brand /><LoadingState message="Restoring your session…" /></main>;
  return <main className="auth-page" id="main-content">
    <div className="auth-brand"><Brand /><span className="micro">A SHARED RECORD</span></div>
    <section className="auth-card welcome-card">
      <p className="eyebrow">BUILT ON CLARITY</p><h1>One shared record.<br />A little more certainty.</h1>
      <p>A calm place for the commitments you make together.</p>
      <div className="auth-actions"><Link className="button button--primary" href="/signup">Create account</Link><Link className="button button--secondary" href="/login">Log in</Link></div>
      {state.error && <><p role="alert">{state.error}</p><Button variant="quiet" onClick={() => void session.bootstrap()}>Retry session recovery</Button><Button variant="quiet" onClick={() => void session.logout()}>Clear local session</Button></>}
      <p className="supporting">Phone verification keeps your account yours.</p>
    </section>
  </main>;
}
