import { ApiError } from "../api/errors";
import type { AuthApi, CredentialResponse, SessionCredentials } from "../api/auth";
import type { CurrentUser } from "../api/types";

// Structural boundary implemented by independent platform storage adapters.
export interface SessionStorage {
  read(): Promise<SessionCredentials | null>;
  write(credentials: SessionCredentials): Promise<void>;
  clear(): Promise<void>;
}
export type AuthState = { status: "loading" } | { status: "anonymous"; error?: string } |
  { status: "authenticated"; user: CurrentUser };
export function safeMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Unable to continue. Please try again.";
}
const invalid = (error: unknown) => error instanceof ApiError &&
  (error.status === 401 || ["ACCOUNT_DEACTIVATED", "ACCOUNT_UNAVAILABLE"].includes(error.code));
export function credentialsOnly(value: CredentialResponse): SessionCredentials {
  return { access_token: value.access_token, refresh_token: value.refresh_token,
    token_type: value.token_type, access_expires_at: value.access_expires_at,
    refresh_expires_at: value.refresh_expires_at };
}
export function validCredentials(value: unknown): value is SessionCredentials {
  if (!value || typeof value !== "object") return false;
  const v = value as SessionCredentials;
  return v.token_type === "Bearer" && typeof v.access_token === "string" &&
    typeof v.refresh_token === "string" && !!v.access_token && !!v.refresh_token &&
    typeof v.access_expires_at === "string" && typeof v.refresh_expires_at === "string" &&
    Number.isFinite(Date.parse(v.access_expires_at)) && Number.isFinite(Date.parse(v.refresh_expires_at));
}
/** Serializes credential operations, including refresh rotation and logout.
 * No transport retries, cached profile, platform storage, or financial behavior.
 */
export class AuthSession {
  private credentials: SessionCredentials | null = null;
  private state: AuthState = { status: "loading" };
  private listeners = new Set<() => void>();
  private tail: Promise<unknown> = Promise.resolve();
  private restoration: Promise<void> | null = null;
  private recovery: Promise<void> | null = null;
  constructor(private store: SessionStorage, private api: AuthApi) {}
  accessToken = () => this.credentials?.access_token ?? null;
  expiresAt = () => this.credentials?.access_expires_at ?? null;
  snapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private publish(state: AuthState) { this.state = state; this.listeners.forEach(l => l()); }
  private exclusive<T>(run: () => Promise<T>): Promise<T> {
    const result = this.tail.then(run, run); this.tail = result.catch(() => undefined); return result;
  }
  private async clear() {
    this.credentials = null;
    await this.store.clear();
  }
  private async rotate() {
    if (!this.credentials || Date.parse(this.credentials.refresh_expires_at) <= Date.now())
      throw new ApiError("REFRESH_TOKEN_EXPIRED", "Your session has expired. Please log in again.", 401);
    const response = await this.api.refreshSession(this.credentials.refresh_token);
    const next = credentialsOnly(response);
    // Replace old memory credentials immediately; never reuse them if storage fails.
    this.credentials = next;
    try { await this.store.write(next); } catch { await this.clear(); throw new Error("Session storage unavailable"); }
  }
  private async reconcile(rotated = false) {
    if (!this.credentials) { this.publish({ status: "anonymous" }); return; }
    if (Date.parse(this.credentials.access_expires_at) <= Date.now()) { await this.rotate(); rotated = true; }
    let user: CurrentUser;
    try { user = await this.api.getMe(); }
    catch (error) {
      if (!rotated && error instanceof ApiError && ["AUTH_TOKEN_EXPIRED", "INVALID_AUTH_TOKEN"].includes(error.code)) {
        await this.rotate(); user = await this.api.getMe();
      } else throw error;
    }
    this.publish({ status: "authenticated", user });
  }
  private async failure(error: unknown) {
    if (invalid(error)) { try { await this.clear(); } catch { /* Memory is already cleared. */ } }
    this.publish({ status: "anonymous", error: safeMessage(error) });
  }
  bootstrap = (): Promise<void> => {
    if (this.restoration) return this.restoration;
    this.restoration = this.exclusive(async () => {
      this.publish({ status: "loading" });
      try {
        const value = await this.store.read();
        if (value && !validCredentials(value)) { await this.clear(); this.publish({ status: "anonymous" }); return; }
        this.credentials = value;
        await this.reconcile();
      } catch (error) { await this.failure(error); }
    }).finally(() => { this.restoration = null; });
    return this.restoration;
  };
  establish = (response: CredentialResponse) => this.exclusive(async () => {
    this.publish({ status: "loading" });
    try {
      this.credentials = credentialsOnly(response);
      try { await this.store.write(this.credentials); } catch { await this.clear(); throw new Error("Session storage unavailable"); }
      await this.reconcile();
    } catch (error) { await this.failure(error); throw error; }
  });
  refresh = (): Promise<void> => {
    if (this.recovery) return this.recovery;
    const requestedToken = this.credentials?.refresh_token;
    this.recovery = this.exclusive(async () => {
      this.publish({ status: "loading" });
      try {
        // A queued bootstrap may already have completed this rotation.
        if (!requestedToken || this.credentials?.refresh_token === requestedToken) await this.rotate();
        await this.reconcile(true);
      }
      catch (error) { await this.failure(error); }
    }).finally(() => { this.recovery = null; });
    return this.recovery;
  };
  reconcileUser = (user: CurrentUser) => {
    if (this.state.status !== "authenticated" || this.state.user.id !== user.id || user.status !== "ACTIVE") throw new Error("Unavailable account.");
    this.publish({status:"authenticated",user});
  };
  clearDeactivated = () => this.exclusive(async () => {
    try { await this.clear(); } finally { this.publish({status:"anonymous"}); }
  });
  logout = () => this.exclusive(async () => {
    this.publish({ status: "loading" });
    try { if (this.credentials) await this.api.logout(); }
    catch { /* Local exit remains possible when credentials or transport fail. */ }
    finally {
      try { await this.clear(); this.publish({ status: "anonymous" }); }
      catch { this.publish({ status: "anonymous", error: "Secure storage could not be cleared. Please retry sign out." }); }
    }
  });
}
