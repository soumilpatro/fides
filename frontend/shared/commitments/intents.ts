import { ApiError } from "../api/errors";
export interface MutationIntent { key: string; payload: string; blocked: boolean; needsReconcile: boolean }
// Keys are operation identifiers, not authentication credentials. No persistent storage.
let sequence = 0;
const runId = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
export const newIntentKey = () => "f3-" + runId + "-" + (++sequence).toString(36);
export function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") return "{" + Object.entries(value).sort(([a],[b]) => a.localeCompare(b)).map(([k,v]) => JSON.stringify(k)+":"+canonical(v)).join(",") + "}";
  return JSON.stringify(value);
}
export function ambiguous(error: unknown) {
  return !(error instanceof ApiError) || error.status === null || error.status >= 500 ||
    ["NETWORK_ERROR","INVALID_RESPONSE","CONFLICT","IDEMPOTENCY_CONFLICT"].includes(error.code);
}
// Pure synchronous intent state survives feature remounts inside the same AuthProvider.
export class MutationIntents {
  private values = new Map<string, MutationIntent>();
  get(scope: string) { return this.values.get(scope); }
  begin(scope: string, body: unknown, makeKey = newIntentKey) {
    const payload = canonical(body), previous = this.values.get(scope);
    if (previous && previous.payload !== payload) throw new Error("Resolve the pending request before changing its payload.");
    if (previous?.blocked || previous?.needsReconcile) throw new Error("Refresh the pending request before retrying.");
    const intent = previous ?? { key: makeKey(), payload, blocked: false, needsReconcile: false };
    this.values.set(scope, intent); return intent;
  }
  failed(scope: string, error: unknown) {
    if (!ambiguous(error)) { this.values.delete(scope); return; }
    const intent = this.values.get(scope);
    if (intent) { intent.needsReconcile = true; intent.blocked = error instanceof ApiError && error.code === "IDEMPOTENCY_CONFLICT"; }
  }
  reconciled(scope: string) { const intent = this.values.get(scope); if (intent) intent.needsReconcile = false; }
  succeeded(scope: string) { this.values.delete(scope); }
}
