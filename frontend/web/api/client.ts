import { createApiClient } from "@fides/shared/api/request";
import type { AccessTokenSource } from "@fides/shared/api/types";

// Lazy construction keeps the foundation preview independent of backend configuration.
export function createClient(accessToken?: AccessTokenSource) {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl)
    throw new Error("Configure the API base URL before making requests");
  return createApiClient({ baseUrl, accessToken });
}
