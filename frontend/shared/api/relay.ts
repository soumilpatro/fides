import { connectionUuid } from "./connections";
export function isAllowedApiRoute(method: string, path: string[]) {
  if (!path.length || path.some(part => !/^[a-zA-Z0-9-]+$/.test(part))) return false;
  const endpoint = path.join("/");
  if (method === "GET" && endpoint === "me") return true;
  if (method === "POST" && ["auth/otp/request", "auth/otp/verify", "auth/refresh", "auth/logout"].includes(endpoint)) return true;
  if (path[0] === "commitments") {
    if (path.length === 1) return method === "GET" || method === "POST";
    if (!connectionUuid.test(path[1])) return false;
    if (path.length === 2) return method === "GET";
    return path.length === 3 && (method === "GET" ? ["terms", "installments"].includes(path[2]) :
      method === "POST" && ["confirm", "reject", "cancel"].includes(path[2]));
  }
  if (path[0] !== "connections") return false;
  if (path.length === 1) return method === "GET" || method === "POST";
  if (!connectionUuid.test(path[1])) return false;
  if (path.length === 2) return method === "GET" || method === "DELETE";
  return path.length === 3 && method === "POST" && ["accept", "reject", "block"].includes(path[2]);
}
