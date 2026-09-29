import type { ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { colors, spacing, typography } from "@fides/shared/tokens/index";
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <Text style={styles.wordmark}>FIDES</Text>
        <Text style={styles.label}>FOUNDATION / F0</Text>
      </View>
      {children}
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.canvas },
  header: {
    padding: spacing.lg,
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.md,
    justifyContent: "space-between",
    alignItems: "center",
    borderBottomWidth: 1,
    borderColor: colors.border,
  },
  wordmark: {
    fontFamily: "ManropeBold",
    fontSize: typography.size.section,
    color: colors.text.primary,
  },
  label: {
    fontFamily: "Manrope",
    fontSize: typography.size.micro,
    color: colors.text.primary,
  },
});
