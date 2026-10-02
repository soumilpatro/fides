import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import type { SessionCredentials } from "@fides/shared/api/auth";
export type { SessionCredentials } from "@fides/shared/api/auth";
export interface SessionStore {
  read(): Promise<SessionCredentials | null>;
  write(credentials: SessionCredentials): Promise<void>;
  clear(): Promise<void>;
}
const KEY = "fides.session.v1";
const options = { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };
export function secureSessionStore(): SessionStore {
  // Expo web preview has no native keychain: keep browser credentials in memory.
  let preview: SessionCredentials | null = null;
  return {
    read: async () => {
      if (Platform.OS === "web") return preview;
      const raw = await SecureStore.getItemAsync(KEY, options);
      if (!raw) return null;
      try { return JSON.parse(raw) as SessionCredentials; }
      catch { await SecureStore.deleteItemAsync(KEY, options); return null; }
    },
    write: async value => {
      if (Platform.OS === "web") { preview = { ...value }; return; }
      await SecureStore.setItemAsync(KEY, JSON.stringify(value), options);
    },
    clear: async () => {
      preview = null;
      if (Platform.OS !== "web") await SecureStore.deleteItemAsync(KEY, options);
    },
  };
}
