"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { AuthIntent, OtpChallenge } from "@fides/shared/api/auth";
import { detectedTimezone, maskedPhone, retryDeadline, profileReady } from "@fides/shared/auth/flow";
import { safeMessage } from "@fides/shared/auth/session";
import { Brand } from "../../components/Brand";
import { Button, ErrorState, LoadingState, TextField } from "../../components/ui";
import { useAuth } from "./useAuth";

export function AuthFlow({ intent }: { intent: AuthIntent }) {
  const { state, session, api } = useAuth();
  const router = useRouter();
  const [step, setStep] = useState<"phone" | "otp" | "profile">("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState("");
  const [challenge, setChallenge] = useState<OtpChallenge | null>(null);
  const [deadline, setDeadline] = useState(0);
  const [blockedUntil, setBlockedUntil] = useState(0);
  const [now, setNow] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = useRef(false);
  const generation = useRef(0);
  useEffect(() => { const lifecycle = generation; const id = setInterval(() => setNow(Date.now()), 1000); return () => { clearInterval(id); lifecycle.current++; }; }, []);
  useEffect(() => { if (state.status === "authenticated") router.replace("/app/overview"); }, [state, router]);
  const expired = !!challenge && now >= Date.parse(challenge.expires_at);
  const wait = Math.max(0, Math.ceil((deadline - now) / 1000));
  async function perform(action: () => Promise<void>) {
    if (running.current) return;
    running.current = true; setBusy(true); setError("");
    try { await action(); }
    catch (failure) { setError(safeMessage(failure)); setNow(Date.now()); const until = retryDeadline(failure); if (until) { setDeadline(until); setBlockedUntil(until); } }
    finally { running.current = false; setBusy(false); }
  }
  function requestCode() {
    return perform(async () => {
      const current = generation.current;
      const next = await api.requestOtp(intent, phone);
      if (current !== generation.current) return;
      setChallenge(next); setCode(""); setDeadline(Date.now() + next.resend_after_seconds * 1000); setNow(Date.now()); setStep("otp");
    });
  }
  function verify() {
    return perform(async () => {
      if (!challenge) return;
      const current = generation.current;
      const result = await api.verifyOtp(intent === "signup" ? { challenge_id: challenge.challenge_id, code, display_name: name, timezone } : { challenge_id: challenge.challenge_id, code });
      setCode("");
      if (current !== generation.current) return;
      await session.establish(result);
    });
  }
  if (state.status !== "anonymous") return <main className="auth-page"><Brand /><LoadingState message="Resolving your session…" /></main>;
  return <main className="auth-page" id="main-content">
    <div className="auth-brand"><Link href="/"><Brand /></Link><span className="micro">A SHARED RECORD</span></div>
    <section className="auth-card">
      <p className="eyebrow">{intent === "signup" ? "CREATE ACCOUNT" : "WELCOME BACK"}</p>
      <h1>{step === "phone" ? (intent === "signup" ? "Start with your phone." : "Log in to Fides.") : step === "otp" ? "Check your messages." : "A little about you."}</h1>
      <p>{step === "phone" ? "We’ll send a six-digit verification code." : step === "otp" ? `Enter the code sent to ${maskedPhone(phone)}.` : "Review your name and timezone to finish creating your account."}</p>
      <form className="auth-form" onSubmit={event => {
        event.preventDefault();
        if (busy || Date.now() < blockedUntil || (step !== "phone" && expired) || (step === "profile" && !profileReady(name, timezone))) return;
        if (step === "phone") void requestCode();
        else if (step === "otp" && intent === "signup") { setTimezone(detectedTimezone()); setStep("profile"); }
        else void verify();
      }}>
        {step === "phone" ? <TextField label="Phone number" type="tel" inputMode="tel" autoComplete="tel" placeholder="+ country code and phone number" value={phone} onChange={e => setPhone(e.target.value)} required maxLength={32} disabled={busy} hint="Use international format, beginning with +." /> : step === "otp" ? <TextField label="Six-digit code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" minLength={6} maxLength={6} value={code} onChange={e => setCode(e.target.value)} disabled={busy || expired} required /> : <>
          <TextField label="Display name" autoComplete="name" value={name} onChange={e => setName(e.target.value)} required disabled={busy} hint="1–100 characters. Your name will be shown to people you interact with." />
          <TextField label="Timezone" value={timezone} onChange={e => setTimezone(e.target.value)} required maxLength={64} disabled={busy} hint="Review the detected IANA timezone, or enter your own if detection is unavailable." />
        </>}
        {expired && <p role="alert">This challenge has expired. Request another code.</p>}
        {error && <ErrorState message={error} />}
        <Button type="submit" disabled={busy || now < blockedUntil || (step === "phone" ? !phone.trim() || wait > 0 : expired || (step === "otp" ? !/^[0-9]{6}$/.test(code) : !profileReady(name, timezone)))}>{busy ? "Please wait…" : step === "phone" ? "Send verification code" : step === "otp" && intent === "signup" ? "Continue" : "Verify and continue"}</Button>
        {step === "profile" && <Button variant="quiet" disabled={busy} onClick={() => { setCode(""); setStep("otp"); }}>Edit verification code</Button>}
        {step !== "phone" && <>
          <p className="supporting" role="status">{expired ? "Code expired" : `Valid until ${new Date(challenge!.expires_at).toLocaleTimeString()}`}{wait > 0 ? ` · Resend in ${wait}s` : ""}</p>
          <Button variant="secondary" disabled={busy || wait > 0} onClick={() => void requestCode()}>Resend code</Button>
          <Button variant="quiet" disabled={busy} onClick={() => { generation.current++; setCode(""); setChallenge(null); setStep("phone"); setError(""); }}>Change phone number</Button>
        </>}
        {step === "phone" && wait > 0 && <p role="status">Try again in {wait}s.</p>}
        {step !== "phone" && now < blockedUntil && <p role="status">Try again in {Math.ceil((blockedUntil - now) / 1000)}s.</p>}
      </form>
      <Link className="auth-back" href="/">Back to welcome</Link>
    </section>
  </main>;
}
