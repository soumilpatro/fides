import type { SessionCredentials } from "@fides/shared/api/auth";
export type { SessionCredentials } from "@fides/shared/api/auth";
export interface SessionStore {
  read(): Promise<SessionCredentials | null>;
  write(credentials: SessionCredentials): Promise<void>;
  clear(): Promise<void>;
}
export function memorySessionStore(): SessionStore {
  let current: SessionCredentials | null = null;
  return {
    read: async () => current ? { ...current } : null,
    write: async value => { current = { ...value }; },
    clear: async () => { current = null; },
  };
}
