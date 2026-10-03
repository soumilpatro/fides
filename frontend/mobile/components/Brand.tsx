import { Image, StyleSheet, View } from "react-native";
import recordLoopLockup from "../assets/fides-record-loop-horizontal-512x171.png";

export function Brand() {
  return <View accessibilityRole="image" accessibilityLabel="Fides" style={styles.lockup}>
    <Image source={recordLoopLockup} resizeMode="contain" style={styles.image} alt="Fides" />
  </View>;
}
const styles = StyleSheet.create({
  lockup: { width: 128, height: 43, justifyContent: "center" },
  image: { width: 128, height: 43 },
});
