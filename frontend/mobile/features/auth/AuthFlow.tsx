import { useEffect, useRef, useState } from "react";
import { KeyboardAvoidingView, Platform, StyleSheet, View } from "react-native";
import type { AuthIntent, OtpChallenge } from "@fides/shared/api/auth";
import { detectedTimezone, maskedPhone, retryDeadline, profileReady } from "@fides/shared/auth/flow";
import { safeMessage } from "@fides/shared/auth/session";
import { spacing } from "@fides/shared/tokens/index";
import { Body, Button, ErrorState, Screen, TextField, Title } from "../../components/ui";
import { Brand } from "../../components/Brand";
import { useAuth } from "./useAuth";
export function AuthFlow({ intent, onBack }: { intent: AuthIntent; onBack: () => void }) {
  const { api, session } = useAuth();
  const [step, setStep] = useState<"phone" | "otp" | "profile">("phone");
  const [phone, setPhone] = useState(""); const [code, setCode] = useState("");
  const [name, setName] = useState(""); const [timezone, setTimezone] = useState("");
  const [challenge, setChallenge] = useState<OtpChallenge | null>(null);
  const [deadline, setDeadline] = useState(0); const [now, setNow] = useState(0);
  const [blockedUntil, setBlockedUntil] = useState(0);
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const running = useRef(false); const generation = useRef(0);
  useEffect(() => { const lifecycle = generation; const timer = setInterval(() => setNow(Date.now()), 1000); return () => { clearInterval(timer); lifecycle.current++; }; }, []);
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
      setCode(""); if (current !== generation.current) return;
      await session.establish(result);
    });
  }
  function next() {
    if (busy || Date.now() < blockedUntil || (step !== "phone" && expired) || (step === "profile" && !profileReady(name, timezone))) return;
    if (step === "phone") void requestCode();
    else if (step === "otp" && intent === "signup") { setTimezone(detectedTimezone()); setStep("profile"); }
    else void verify();
  }
  return <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}><Screen>
    <Brand /><Body supporting>{intent === "signup" ? "Create account" : "Log in"}</Body>
    <Title>{step === "phone" ? "Start with your phone." : step === "otp" ? "Check your messages." : "A little about you."}</Title>
    <Body>{step === "phone" ? "We’ll send a six-digit verification code." : step === "otp" ? `Enter the code sent to ${maskedPhone(phone)}.` : "Review your name and timezone to finish creating your account."}</Body>
    <View style={styles.form}>
      {step === "phone" ? <TextField label="Phone number" keyboardType="phone-pad" autoComplete="tel" autoCapitalize="none" value={phone} onChangeText={setPhone} editable={!busy} maxLength={32} hint="International format, beginning with +." /> : step === "otp" ? <TextField label="Six-digit code" keyboardType="number-pad" autoComplete="one-time-code" textContentType="oneTimeCode" value={code} onChangeText={setCode} maxLength={6} editable={!busy && !expired} /> : <>
        <TextField label="Display name" autoComplete="name" value={name} onChangeText={setName} editable={!busy} hint="1–100 characters. Shown to people you interact with." />
        <TextField label="Timezone" value={timezone} onChangeText={setTimezone} autoCapitalize="none" autoCorrect={false} maxLength={64} editable={!busy} hint="Review the detected IANA timezone, or enter your own." />
      </>}
      {expired && <ErrorState message="This challenge has expired. Request another code." />}
      {error ? <ErrorState message={error} /> : null}
      <Button title={busy ? "Please wait…" : step === "phone" ? "Send verification code" : step === "otp" && intent === "signup" ? "Continue" : "Verify and continue"} onPress={next} disabled={busy || now < blockedUntil || (step === "phone" ? !phone.trim() || wait > 0 : expired || (step === "otp" ? !/^[0-9]{6}$/.test(code) : !profileReady(name, timezone)))} />
      {step === "profile" && <Button title="Edit verification code" variant="quiet" disabled={busy} onPress={() => { setCode(""); setStep("otp"); }} />}
      {step !== "phone" && <>
        <Body supporting>{expired ? "Code expired" : `Valid until ${new Date(challenge!.expires_at).toLocaleTimeString()}`}{wait > 0 ? ` · Resend in ${wait}s` : ""}</Body>
        <Button title="Resend code" variant="secondary" onPress={() => void requestCode()} disabled={busy || wait > 0} />
        <Button title="Change phone number" variant="quiet" onPress={() => { generation.current++; setCode(""); setChallenge(null); setStep("phone"); setError(""); }} disabled={busy} />
      </>}
      {step === "phone" && wait > 0 && <Body>Try again in {wait}s.</Body>}
      {step !== "phone" && now < blockedUntil && <Body>Try again in {Math.ceil((blockedUntil - now) / 1000)}s.</Body>}
      <Button title="Back to welcome" variant="quiet" disabled={busy} onPress={onBack} />
    </View>
  </Screen></KeyboardAvoidingView>;
}
const styles = StyleSheet.create({ flex: { flex: 1 }, form: { gap: spacing.lg } });
