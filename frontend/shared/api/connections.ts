import { createApiClient } from "./request";
import { ApiError } from "./errors";

export type ConnectionStatus = "PENDING" | "ACCEPTED" | "BLOCKED" | "REMOVED";
export interface Participant { id: string; display_name: string }
export interface Connection {
  id: string; status: ConnectionStatus; requester: Participant; recipient: Participant;
  created_at: string; updated_at: string;
}
export const connectionUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function identifier(id: string) {
  if (!connectionUuid.test(id)) throw new ApiError("NOT_FOUND", "Unavailable resource.", 404);
  return id;
}
// Project the closed response; never retain extra profile data supplied by transport.
export function connectionResponse(value: unknown): Connection {
  const fail = () => { throw new ApiError("INVALID_RESPONSE", "Unable to read the server response.", null); };
  if (!value || typeof value !== "object") return fail();
  const row = value as Connection;
  const participant = (p: Participant): Participant => {
    if (!p || typeof p.id !== "string" || !connectionUuid.test(p.id) || typeof p.display_name !== "string") return fail();
    return { id: p.id, display_name: p.display_name };
  };
  if (typeof row.id !== "string" || !connectionUuid.test(row.id) ||
    !["PENDING", "ACCEPTED", "BLOCKED", "REMOVED"].includes(row.status) ||
    typeof row.created_at !== "string" || !Number.isFinite(Date.parse(row.created_at)) ||
    typeof row.updated_at !== "string" || !Number.isFinite(Date.parse(row.updated_at))) return fail();
  return { id: row.id, status: row.status, requester: participant(row.requester), recipient: participant(row.recipient),
    created_at: row.created_at, updated_at: row.updated_at };
}
export function createConnectionsApi(config: Parameters<typeof createApiClient>[0]) {
  const fetcher: typeof fetch = async (input, init) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try { return await (config.fetcher ?? fetch)(input, { ...init, signal: controller.signal }); }
    finally { clearTimeout(timer); }
  };
  const request = createApiClient({ ...config, fetcher });
  const result = async (pending: Promise<unknown>) => connectionResponse(await pending);
  const path = (id: string) => "/connections/" + identifier(id);
  return {
    createConnection: (phone: string) => result(request("/connections", { method: "POST", body: { phone } })),
    listConnections: async () => {
      const data = await request<unknown>("/connections");
      if (!Array.isArray(data)) throw new ApiError("INVALID_RESPONSE", "Unable to read the server response.", null);
      return data.map(connectionResponse);
    },
    getConnection: (id: string) => result(request(path(id))),
    acceptConnection: (id: string) => result(request(path(id) + "/accept", { method: "POST" })),
    rejectConnection: (id: string) => result(request(path(id) + "/reject", { method: "POST" })),
    blockConnection: (id: string) => result(request(path(id) + "/block", { method: "POST" })),
    removeConnection: (id: string) => result(request(path(id), { method: "DELETE" })),
  };
}
export type ConnectionsApi = ReturnType<typeof createConnectionsApi>;
