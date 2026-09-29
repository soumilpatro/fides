import type { CurrentUser } from "@fides/shared/api/types";
export type AuthState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "authenticated"; user: CurrentUser };
