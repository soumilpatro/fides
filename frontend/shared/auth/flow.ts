import { ApiError } from "../api/errors";
export function detectedTimezone(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { return ""; }
}
export function maskedPhone(phone: string): string {
  return phone.length > 4 ? `${phone.slice(0, 3)} •••• ${phone.slice(-2)}` : "your phone";
}
export function retryDeadline(error: unknown): number | null {
  return error instanceof ApiError && error.retryAfterSeconds !== null ? Date.now() + error.retryAfterSeconds * 1000 : null;
}
/** Basic signup UX checks; the server remains authoritative. */
export function profileReady(name: string, timezone: string): boolean {
  const normalized = name.normalize("NFC");
  const length = Array.from(normalized.trim()).length;
  return length >= 1 && length <= 100 && !/\p{Cc}/u.test(normalized) &&
    timezone.trim().length >= 1 && timezone.trim().length <= 64;
}
