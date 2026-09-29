/** TD-012 is open. No storage adapter is selected or installed in F0. */
export interface SessionCredentials {
  access_token: string;
  refresh_token: string;
  token_type: "Bearer";
  access_expires_at: string;
  refresh_expires_at: string;
}
export interface SessionStore {
  read(): Promise<SessionCredentials | null>;
  write(credentials: SessionCredentials): Promise<void>;
  clear(): Promise<void>;
}
