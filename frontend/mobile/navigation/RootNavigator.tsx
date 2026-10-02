import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import type { AuthIntent } from "@fides/shared/api/auth";
import { colors, controls, spacing, typography } from "@fides/shared/tokens/index";
import { Brand } from "../components/Brand";
import { Body, Button, EmptyState, LoadingState, Screen, Title } from "../components/ui";
import { AuthFlow } from "../features/auth/AuthFlow";
import { useAuth } from "../features/auth/useAuth";
import { Connections } from "../features/connections/Connections";
import { FoundationScreen } from "../app/FoundationScreen";
export function RootNavigator() {
  const { state } = useAuth();
  if (state.status === "loading") return <SafeAreaView style={styles.safe}><Screen><LoadingState message="Resolving your session…" /></Screen></SafeAreaView>;
  return <SafeAreaView style={styles.safe}>{state.status === "authenticated" ? <AuthenticatedShell /> : <Anonymous />}</SafeAreaView>;
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
  const { state, session } = useAuth(); const [destination, setDestination] = useState<string>("Home");
  if (state.status !== "authenticated") return null;
  return <>
    <View style={styles.header}><Brand /><Pressable accessibilityRole="button" accessibilityLabel="Notifications" onPress={() => setDestination("Notifications")} style={styles.entry}><Text style={styles.label}>🔔 Notifications</Text></Pressable></View>
    {destination === "Connections" ? <Connections key={state.user.id} /> : <Screen><Title>{destination}</Title><Body>Welcome, {state.user.display_name}.</Body><EmptyState title="Your account is ready." message="This destination is reserved for a future release." />
      {destination === "Home" && <Button title="Create commitment · future release" disabled onPress={() => {}} />}
      {destination === "Profile" && <Button title="Log out" variant="quiet" onPress={() => void session.logout()} />}
    </Screen>}
    <View style={styles.tabs}>{tabs.map(tab => <Pressable key={tab} accessibilityRole="tab" accessibilityState={{ selected: tab === destination }} onPress={() => setDestination(tab)} style={styles.tab}><Text style={[styles.label, destination === tab && styles.selected]}>{tab}</Text></Pressable>)}</View>
  </>;
}
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.canvas },
  header: { padding: spacing.md, flexDirection: "row", alignItems: "center", justifyContent: "space-between", borderBottomWidth: 1, borderColor: colors.border },
  entry: { minHeight: controls.button, justifyContent: "center", padding: spacing.sm },
  label: { fontFamily: "Manrope", fontSize: typography.size.supporting, color: colors.text.primary },
  tabs: { flexDirection: "row", borderTopWidth: 1, borderColor: colors.border },
  tab: { flex: 1, minHeight: controls.button, alignItems: "center", justifyContent: "center", paddingVertical: spacing.sm },
  selected: { color: colors.brand.signal, fontFamily: "ManropeBold" },
});
