import { ApiError, isBackendError } from "./errors";
import type { AccessTokenSource } from "./types";

export interface RequestOptions<TBody> {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: TBody;
  idempotencyKey?: string;
  signal?: AbortSignal;
}
/** No endpoint calls, persistence, refresh, logging, retries, or optimistic state. */
export function createApiClient(config: {
  baseUrl: string;
  accessToken?: AccessTokenSource;
  fetcher?: typeof fetch;
}) {
  const base = new URL(config.baseUrl);
  if (
    !["http:", "https:"].includes(base.protocol) ||
    base.username ||
    base.password ||
    base.search ||
    base.hash
  )
    throw new Error("Invalid API base URL");
  const prefix = base.href.replace(/\/$/, "");
  return async function request<TResponse, TBody = never>(
    path: string,
    options: RequestOptions<TBody> = {},
  ): Promise<TResponse> {
    // Keep bearer credentials pinned to the configured origin and API prefix.
    if (
      !/^\/[a-zA-Z0-9]/.test(path) ||
      path.includes("\\") ||
      /(?:^|\/)\.{1,2}(?:\/|$)/.test(path) ||
      /%2e|%2f|%5c/i.test(path)
    )
      throw new Error("Expected an API-relative path");
    const method = options.method ?? "GET";
    if (method === "GET" && options.body !== undefined)
      throw new Error("GET cannot have a body");
    const headers = new Headers({ Accept: "application/json" });
    if (options.body !== undefined)
      headers.set("Content-Type", "application/json");
    if (options.idempotencyKey)
      headers.set("Idempotency-Key", options.idempotencyKey);
    const token = await config.accessToken?.();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    let response: Response;
    try {
      response = await (config.fetcher ?? fetch)(prefix + path, {
        method,
        headers,
        body:
          options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: options.signal,
        credentials: "omit",
        cache: "no-store",
        redirect: "error",
      });
    } catch (error) {
      if (options.signal?.aborted) throw error;
      throw new ApiError("NETWORK_ERROR", "Unable to reach Fides.", null);
    }
    const requestId = response.headers.get("X-Request-ID");
    if (response.status === 204 && response.ok) return undefined as TResponse;
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      throw new ApiError(
        "INVALID_RESPONSE",
        "Unable to read the server response.",
        response.status,
        requestId,
      );
    }
    if (!response.ok) {
      if (isBackendError(data))
        throw new ApiError(
          data.error.code,
          data.error.message,
          response.status,
          requestId,
        );
      throw new ApiError(
        "HTTP_ERROR",
        "The request could not be completed.",
        response.status,
        requestId,
      );
    }
    // Type parameters describe the wire boundary; they do not validate untrusted JSON.
    return data as TResponse;
  };
}
