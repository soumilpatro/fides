import { useId, type ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from "react-native";
import {
  colors,
  controls,
  radii,
  spacing,
  typography,
  statusColors,
  type SemanticStatus,
} from "@fides/shared/tokens/index";
import { formatMoney } from "@fides/shared/domain/money";

export function Body({
  children,
  supporting = false,
}: {
  children: ReactNode;
  supporting?: boolean;
}) {
  return (
    <Text style={[styles.body, supporting && styles.supporting]}>
      {children}
    </Text>
  );
}
export function Title({ children }: { children: ReactNode }) {
  return (
    <Text accessibilityRole="header" style={styles.title}>
      {children}
    </Text>
  );
}
export function Micro({ children }: { children: ReactNode }) {
  return <Text style={styles.micro}>{children}</Text>;
}
export function Button({
  title,
  onPress,
  variant = "primary",
  disabled = false,
}: {
  title: string;
  onPress: () => void;
  variant?: "primary" | "secondary" | "quiet" | "destructive";
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={[
        styles.button,
        variant === "primary" && !disabled && styles.primary,
        variant === "destructive" && !disabled && {backgroundColor:statusColors.DISPUTED.background,borderColor:statusColors.DISPUTED.border},
        (variant === "quiet" || disabled) && styles.quiet,
      ]}
    >
      <Text
        style={[
          styles.buttonText,
          variant === "primary" && !disabled && styles.onPrimary,
          variant === "destructive" && !disabled && {color:statusColors.DISPUTED.text},
          disabled && styles.body,
        ]}
      >
        {title}
      </Text>
    </Pressable>
  );
}
export function TextField({
  label,
  hint,
  ...props
}: TextInputProps & { label: string; hint?: string }) {
  const id = useId();
  return (
    <View style={styles.stack}>
      <Text nativeID={id} style={styles.label}>
        {label}
      </Text>
      <TextInput
        {...props}
        accessibilityLabel={label}
        accessibilityLabelledBy={id}
        accessibilityHint={hint}
        placeholderTextColor={colors.text.primary}
        style={[styles.input, props.style]}
      />
      {hint ? <Body supporting>{hint}</Body> : null}
    </View>
  );
}
export function Card({
  children,
  title,
}: {
  children: ReactNode;
  title?: string;
}) {
  return (
    <View style={styles.card}>
      {title ? (
        <Text accessibilityRole="header" style={styles.section}>
          {title}
        </Text>
      ) : null}
      {children}
    </View>
  );
}
/** Presentation only; text carries the authoritative status meaning. */
export function StatusChip({ label, status }: { label: string; status?: SemanticStatus }) {
  const color = status ? statusColors[status] : null;
  return (
    <View style={[styles.chip, color && { backgroundColor: color.background, borderColor: color.border }]}>
      <Text style={[styles.supporting, color && { color: color.text }]}>{label}</Text>
    </View>
  );
}
export function Avatar({ name }: { name: string }) {
  const initials = name
    .trim()
    .split(/\s+/u)
    .slice(0, 2)
    .map((part) => Array.from(part)[0] ?? "")
    .join("");
  return (
    <View
      style={styles.avatar}
      accessible={false}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      <Text style={styles.buttonText}>{initials}</Text>
    </View>
  );
}
export function PersonRow({ name, role }: { name: string; role: string }) {
  return (
    <View style={styles.person}>
      <Avatar name={name} />
      <View style={styles.personText}>
        <Text style={styles.label}>{name}</Text>
        <Body supporting>{role}</Body>
      </View>
    </View>
  );
}
export function Amount({
  minor,
  currency,
  size = "hero",
}: {
  minor: number;
  currency: string;
  size?: "hero" | "card" | "row";
}) {
  return (
    <Text
      style={[
        styles.amount,
        {
          fontSize:
            typography.size[
              size === "hero"
                ? "amountHero"
                : size === "card"
                  ? "amountCard"
                  : "amountRow"
            ],
        },
      ]}
    >
      {formatMoney(minor, currency)}
    </Text>
  );
}
export function Container({ children }: { children: ReactNode }) {
  return <View style={styles.container}>{children}</View>;
}
export function Screen({ children }: { children: ReactNode }) {
  return (
    <ScrollView keyboardShouldPersistTaps="handled" style={styles.screen}>
      <Container>{children}</Container>
    </ScrollView>
  );
}
export function Divider() {
  return <View style={styles.divider} />;
}
export function LoadingState({ message = "Loading…" }: { message?: string }) {
  return (
    <View accessibilityLiveRegion="polite" style={styles.state}>
      <ActivityIndicator
        color={colors.brand.signal}
        accessibilityLabel={message}
      />
      <Body>{message}</Body>
    </View>
  );
}
export function EmptyState({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <View style={styles.state}>
      <Text style={styles.label}>{title}</Text>
      <Body supporting>{message}</Body>
    </View>
  );
}
export function ErrorState({ message }: { message: string }) {
  return (
    <View accessibilityRole="alert" style={styles.state}>
      <Text style={styles.label}>Unable to continue</Text>
      <Body supporting>{message}</Body>
    </View>
  );
}
const styles = StyleSheet.create({
  body: {
    fontFamily: "Manrope",
    fontSize: typography.size.body,
    color: colors.text.primary,
  },
  supporting: {
    fontFamily: "Manrope",
    fontSize: typography.size.supporting,
    color: colors.text.primary,
  },
  title: {
    fontFamily: "ManropeBold",
    fontSize: typography.size.title,
    color: colors.text.primary,
  },
  section: {
    fontFamily: "ManropeBold",
    fontSize: typography.size.section,
    color: colors.text.primary,
  },
  micro: {
    fontFamily: "ManropeBold",
    fontSize: typography.size.micro,
    color: colors.brand.signal,
  },
  label: {
    fontFamily: "ManropeSemiBold",
    fontSize: typography.size.body,
    color: colors.text.primary,
  },
  stack: { gap: spacing.sm },
  button: {
    minHeight: controls.button,
    borderWidth: 1,
    borderColor: colors.brand.signal,
    borderRadius: radii.control,
    padding: spacing.compact,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.canvas,
  },
  primary: { backgroundColor: colors.brand.signal },
  quiet: { borderColor: colors.border },
  buttonText: {
    fontFamily: "ManropeSemiBold",
    fontSize: typography.size.body,
    color: colors.brand.signal,
  },
  onPrimary: { color: colors.canvas },
  input: {
    minHeight: controls.input,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.compact,
    borderRadius: radii.control,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    fontFamily: "Manrope",
    fontSize: typography.size.body,
    color: colors.text.primary,
  },
  card: {
    padding: spacing.lg,
    gap: spacing.md,
    borderRadius: radii.card,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chip: {
    alignSelf: "flex-start",
    borderRadius: radii.compact,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  avatar: {
    width: spacing.section,
    height: spacing.section,
    borderRadius: radii.round,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  person: { flexDirection: "row", gap: spacing.md, alignItems: "center" },
  personText: { flex: 1, gap: spacing.xs },
  amount: {
    fontFamily: "ManropeSemiBold",
    fontVariant: ["tabular-nums"],
    color: colors.text.primary,
  },
  container: {
    padding: spacing.lg,
    gap: spacing.lg,
    width: "100%",
    maxWidth: 768,
    alignSelf: "center",
  },
  screen: { flex: 1, backgroundColor: colors.canvas },
  divider: { borderTopWidth: 1, borderColor: colors.border },
  state: {
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    gap: spacing.sm,
    alignItems: "flex-start",
  },
});
