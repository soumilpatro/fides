import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import type { AuthIntent } from "@fides/shared/api/auth";
import { colors, controls, spacing, typography } from "@fides/shared/tokens/index";
import { Brand } from "../components/Brand";
import { Body, Button, EmptyState, LoadingState, Screen, Title } from "../components/ui";
import { AuthFlow } from "../features/auth/AuthFlow";
import { useAuth } from "../features/auth/useAuth";
import { AuthContext, type AuthContextValue } from "../features/auth/AuthProvider";
import { ProtectedPresentation } from "./ProtectedModal";
import { Notifications } from "../features/notifications/Notifications";
import { Profile } from "../features/profile/Profile";
import { RepaymentDetail } from "../features/repayments/Repayments";
import type { notificationTarget } from "@fides/shared/notifications/presentation";
import { Activity } from "../features/dashboard/Dashboard";
import { Commitments } from "../features/commitments/Commitments";
import { Connections } from "../features/connections/Connections";
import { FoundationScreen } from "../app/FoundationScreen";
export function RootNavigator() {
  const auth = useAuth();
  const { state } = auth;
  const [retained, setRetained] = useState<AuthContextValue | null>(null);
  const [sessionBoundary, setSessionBoundary] = useState(0);
  // React can batch anonymous -> authenticated into one render. Observe the
  // actual session boundary so even an immediate same-account login resets it.
  useEffect(() => auth.session.subscribe(() => {
    if (auth.session.snapshot().status === "anonymous") {
      setRetained(null);
      setSessionBoundary(previous => previous + 1);
    }
  }), [auth.session]);
  // Retain presentation state only. The live session and API clients remain
  // authoritative; this subtree is hidden and inaccessible while reconciling.
  if (state.status === "authenticated" && retained !== auth) setRetained(auth);
  if (state.status === "anonymous" && retained !== null) setRetained(null);
  const presentation = state.status === "authenticated" ? auth : state.status === "loading" ? retained : null;
  const visible = state.status === "authenticated";
  return <SafeAreaView style={styles.safe}>
    {presentation?.state.status === "authenticated" && <AuthContext.Provider key={presentation.state.user.id + ":" + sessionBoundary} value={presentation}>
      <ProtectedPresentation.Provider value={visible}>
        <View style={visible ? styles.shell : styles.hidden} pointerEvents={visible ? "auto" : "none"}
          accessibilityElementsHidden={!visible} importantForAccessibility={visible ? "auto" : "no-hide-descendants"}>
          <AuthenticatedShell />
        </View>
      </ProtectedPresentation.Provider>
    </AuthContext.Provider>}
    {state.status === "loading" && <Screen><Brand /><LoadingState message="Resolving your session…" /></Screen>}
    {state.status === "anonymous" && <Anonymous />}
  </SafeAreaView>;
}
function Anonymous() {
  const { state, session } = useAuth();
  const [intent, setIntent] = useState<AuthIntent | null>(null);
  const [preview, setPreview] = useState(false);
  if (__DEV__ && preview) return <><Button title="Back to Fides" variant="quiet" onPress={() => setPreview(false)} /><FoundationScreen /></>;
  if (intent) return <AuthFlow key={intent} intent={intent} onBack={() => setIntent(null)} />;
  return <Screen><Brand /><Title>One shared record. A little more certainty.</Title><Body>A calm place for the commitments you make together.</Body>
    <Button title="Create account" onPress={() => setIntent("signup")} /><Button title="Log in" variant="secondary" onPress={() => setIntent("login")} />
    {state.status === "anonymous" && !!state.error && <><Body>{state.error}</Body><Button title="Retry session recovery" variant="quiet" onPress={() => void session.bootstrap()} /><Button title="Clear local session" variant="quiet" onPress={() => void session.logout()} /></>}
    <Body supporting>Phone verification keeps your account yours.</Body>
    {__DEV__ && <Button title="Development foundation preview" variant="quiet" onPress={() => setPreview(true)} />}
  </Screen>;
}
const tabs = ["Home", "Connections", "Activity", "Profile"] as const;
function AuthenticatedShell() {
  const { state } = useAuth(); const [destination, setDestination] = useState<string>("Home");
  const [notificationEntry,setNotificationEntry]=useState<ReturnType<typeof notificationTarget>|null>(null);
  const [commitmentEntry, setCommitmentEntry] = useState<{ connection?: string; create?:boolean; key: number }>({ key: 0 });
  if (state.status !== "authenticated") return null;
  return <>
    <View style={styles.header}><Brand /><Pressable accessibilityRole="button" accessibilityLabel="Notifications" onPress={() => {setNotificationEntry(null);setDestination("Notifications");}} style={styles.entry}><Text style={styles.label}>Notifications</Text></Pressable></View>
    {destination === "Notifications" ? notificationEntry ? notificationEntry.page==="repayment" ? <RepaymentDetail key={notificationEntry.id} id={notificationEntry.id} onBack={()=>setNotificationEntry(null)}/> : <Commitments key={notificationEntry.id} initialDetail={notificationEntry.id} onConnections={()=>setDestination("Connections")}/> : <Notifications onOpen={setNotificationEntry}/> : destination === "Profile" ? <Profile onCommitments={()=>{setCommitmentEntry(previous=>({key:previous.key+1}));setDestination("Home");}}/> : destination === "Connections" ? <Connections key={state.user.id} onCreate={connection => { setCommitmentEntry(previous => ({ connection, key: previous.key + 1 })); setDestination("Home"); }} /> : destination === "Home" ? <Commitments key={state.user.id + ":" + commitmentEntry.key} initialConnection={commitmentEntry.connection} initialCreate={commitmentEntry.create} onConnections={() => setDestination("Connections")} /> : destination === "Activity" ? <Activity key={state.user.id} onCreate={()=>{setCommitmentEntry(previous=>({create:true,key:previous.key+1}));setDestination("Home");}}/> : <Screen><Title>{destination}</Title><Body>Welcome, {state.user.display_name}.</Body><EmptyState title="Your account is ready." message="This destination is reserved for a future release." />

    </Screen>}
    <View style={styles.tabs}>{tabs.map(tab => <Pressable key={tab} accessibilityRole="tab" accessibilityState={{ selected: tab === destination }} onPress={() => { if (tab === "Home") setCommitmentEntry(previous => ({ key: previous.key + 1 })); setDestination(tab); }} style={styles.tab}><Text style={[styles.label, destination === tab && styles.selected]}>{tab}</Text></Pressable>)}</View>
  </>;
}
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.canvas },
  shell: { flex: 1 },
  hidden: { display: "none" },
  header: { padding: spacing.md, flexDirection: "row", alignItems: "center", justifyContent: "space-between", borderBottomWidth: 1, borderColor: colors.border },
  entry: { minHeight: controls.button, justifyContent: "center", padding: spacing.sm },
  label: { fontFamily: "Manrope", fontSize: typography.size.supporting, color: colors.text.primary },
  tabs: { flexDirection: "row", borderTopWidth: 1, borderColor: colors.border },
  tab: { flex: 1, minHeight: controls.button, alignItems: "center", justifyContent: "center", paddingVertical: spacing.sm },
  selected: { color: colors.brand.signal, fontFamily: "ManropeBold" },
});
