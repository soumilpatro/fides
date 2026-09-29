/** B2 MeResponse, copied explicitly from the checked-in backend wire contract. */
export interface CurrentUser {
  id: string;
  phone_e164: string | null;
  display_name: string;
  timezone: string;
  status: "ACTIVE";
  created_at: string;
  updated_at: string;
}
export interface BackendError {
  error: { code: string; message: string };
}
export type AccessTokenSource = () => string | null | Promise<string | null>;
