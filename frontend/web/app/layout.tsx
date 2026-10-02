import type { Metadata } from "next";
import type { CSSProperties, ReactNode } from "react";
import localFont from "next/font/local";
import {
  colors,
  spacing,
  radii,
  typography,
  controls,
  statusColors,
} from "@fides/shared/tokens/index";
import { AuthProvider } from "../features/auth/AuthProvider";
import "./globals.css";
const manrope = localFont({
  src: [
    {
      path: "../../node_modules/@expo-google-fonts/manrope/400Regular/Manrope_400Regular.ttf",
      weight: "400",
    },
    {
      path: "../../node_modules/@expo-google-fonts/manrope/600SemiBold/Manrope_600SemiBold.ttf",
      weight: "600",
    },
    {
      path: "../../node_modules/@expo-google-fonts/manrope/700Bold/Manrope_700Bold.ttf",
      weight: "700",
    },
  ],
  variable: "--font-manrope",
  display: "swap",
});
const inter = localFont({
  src: "../../node_modules/@expo-google-fonts/inter/400Regular/Inter_400Regular.ttf",
  variable: "--font-inter",
  display: "swap",
});
export const metadata: Metadata = {
  title: "Fides",
  description: "One shared record. A little more certainty.",
};
const variables = {
  "--canvas": colors.canvas,
  "--surface": colors.surface,
  "--ink": colors.text.primary,
  "--signal": colors.brand.signal,
  "--human": colors.brand.human,
  "--border": colors.border,
  ...Object.fromEntries(Object.entries(statusColors).flatMap(([status, values]) => Object.entries(values).map(([key, value]) => [`--status-${status.toLowerCase()}-${key}`, value]))),
  ...Object.fromEntries(
    Object.entries(spacing).map(([key, value]) => [
      `--space-${key}`,
      `${value}px`,
    ]),
  ),
  ...Object.fromEntries(
    Object.entries(radii).map(([key, value]) => [
      `--radius-${key}`,
      `${value}px`,
    ]),
  ),
  ...Object.fromEntries(
    Object.entries(typography.size).map(([key, value]) => [
      `--type-${key}`,
      `${value}px`,
    ]),
  ),
  "--control-height": `${controls.button}px`,
} as CSSProperties;
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${manrope.variable} ${inter.variable}`}
      style={variables}
    >
      <body>
        <AuthProvider>
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
