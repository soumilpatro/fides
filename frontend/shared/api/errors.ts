export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number | null,
    public readonly requestId: string | null = null,
    public readonly retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export function isBackendError(
  value: unknown,
): value is { error: { code: string; message: string } } {
  if (!value || typeof value !== "object" || !("error" in value)) return false;
  const error = value.error;
  return (
    !!error &&
    typeof error === "object" &&
    "code" in error &&
    typeof error.code === "string" &&
    "message" in error &&
    typeof error.message === "string"
  );
}
