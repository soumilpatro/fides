import { createApiClient } from "./request";
import type { CurrentUser } from "./types";

export interface SessionCredentials {
  access_token: string;
  refresh_token: string;
  token_type: "Bearer";
  access_expires_at: string;
  refresh_expires_at: string;
}
export interface CredentialResponse extends SessionCredentials { user: CurrentUser }
export type AuthIntent = "signup" | "login";
export interface OtpChallenge {
  challenge_id: string;
  expires_at: string;
  resend_after_seconds: number;
  message: "Verification requested.";
}
export type VerifyRequest = { challenge_id: string; code: string } &
  ({ display_name: string; timezone: string } | { display_name?: never; timezone?: never });
export function createAuthApi(config: Parameters<typeof createApiClient>[0]) {
  // A hung transport must not trap verification, restoration, or logout forever.
  // This is a client transport deadline, not an OTP expiry/cooldown or retry.
  const fetcher: typeof fetch = async (input, init) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try { return await (config.fetcher ?? fetch)(input, { ...init, signal: controller.signal }); }
    finally { clearTimeout(timer); }
  };
  const publicRequest = createApiClient({ ...config, fetcher, accessToken: undefined });
  const protectedRequest = createApiClient({ ...config, fetcher });
  return {
    requestOtp: (intent: AuthIntent, phone: string) =>
      publicRequest<OtpChallenge, { intent: AuthIntent; phone: string }>("/auth/otp/request", { method: "POST", body: { intent, phone } }),
    verifyOtp: (body: VerifyRequest) => publicRequest<CredentialResponse, VerifyRequest>("/auth/otp/verify", { method: "POST", body }),
    refreshSession: (refresh_token: string) => publicRequest<CredentialResponse, { refresh_token: string }>("/auth/refresh", { method: "POST", body: { refresh_token } }),
    logout: () => protectedRequest<{ logged_out: true }>("/auth/logout", { method: "POST" }),
    getMe: () => protectedRequest<CurrentUser>("/me"),
  };
}
export type AuthApi = ReturnType<typeof createAuthApi>;
