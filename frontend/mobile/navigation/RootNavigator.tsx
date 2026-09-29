import { AppShell } from "../components/shell/AppShell";
import { FoundationScreen } from "../app/FoundationScreen";
/** One root screen only. Product routes and navigation libraries are out of F0. */
export function RootNavigator() {
  return (
    <AppShell>
      <FoundationScreen />
    </AppShell>
  );
}
