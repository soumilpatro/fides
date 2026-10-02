import { Text, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { useFonts } from "expo-font";
import { Manrope_400Regular } from "@expo-google-fonts/manrope/400Regular";
import { Manrope_600SemiBold } from "@expo-google-fonts/manrope/600SemiBold";
import { Manrope_700Bold } from "@expo-google-fonts/manrope/700Bold";
import { Inter_400Regular } from "@expo-google-fonts/inter/400Regular";
import { colors, spacing } from "@fides/shared/tokens/index";
import { AuthProvider } from "../features/auth/AuthProvider";
import { RootNavigator } from "../navigation/RootNavigator";
export default function App() {
  const [loaded, error] = useFonts({
    Manrope: Manrope_400Regular,
    ManropeSemiBold: Manrope_600SemiBold,
    ManropeBold: Manrope_700Bold,
    Inter: Inter_400Regular,
  });
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      {!loaded ? (
        <View
          style={{
            flex: 1,
            padding: spacing.lg,
            backgroundColor: colors.canvas,
          }}
        >
          <Text
            accessibilityRole={error ? "alert" : "text"}
            style={{ color: colors.text.primary }}
          >
            {error
              ? "Unable to load Fides fonts. Please restart the app."
              : "Loading Fides…"}
          </Text>
        </View>
      ) : (
        <AuthProvider>
          <RootNavigator />
        </AuthProvider>
      )}
    </SafeAreaProvider>
  );
}
