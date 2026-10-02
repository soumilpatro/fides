import { Text } from "react-native";
import { colors, typography } from "@fides/shared/tokens/index";
export function Brand() {
  return <Text accessibilityLabel="Fides" style={{ fontFamily: "ManropeBold", fontSize: typography.size.section, color: colors.text.primary }}>FIDES</Text>;
}
