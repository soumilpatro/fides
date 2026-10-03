// Closed F1–F5 transport relay. No cookie session or credential store.
import { isAllowedApiRoute, isAllowedApiQuery } from "@fides/shared/api/relay";
export const dynamic = "force-dynamic";
async function relay(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const endpoint = path.join("/");
  const allowed = isAllowedApiRoute(request.method, path);
  const requestId = crypto.randomUUID();
  const failure = (status: number, code: string, message: string) => Response.json({ error: { code, message } },
    { status, headers: { "Cache-Control": "no-store", "X-Request-ID": requestId } });
  if (!allowed) return failure(404, "NOT_FOUND", "Unavailable resource.");
  if (!isAllowedApiQuery(path, new URL(request.url).searchParams)) return failure(422, "VALIDATION_ERROR", "Invalid request.");
  const base = process.env.FIDES_BACKEND_API_URL;
  if (!base) return failure(503, "SERVICE_UNAVAILABLE", "Service is temporarily unavailable.");
  try {
    const url = new URL(base);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error();
    const headers = new Headers({ Accept: "application/json", "X-Request-ID": requestId });
    for (const name of ["Authorization", "Content-Type"]) {
      const value = request.headers.get(name); if (value) headers.set(name, value);
    }
    if (request.method === "POST" && (path[0] === "commitments" || path[0] === "repayments" || path[0] === "extension-requests" || path[0] === "closure-requests")) {
      const key = request.headers.get("Idempotency-Key");
      if (!key || !/^[A-Za-z0-9._:-]{1,128}$/.test(key)) return failure(400, "MALFORMED_REQUEST", "Invalid request.");
      headers.set("Idempotency-Key", key);
    }
    const upstream = await fetch(url.href.replace(/\/$/, "") + "/" + endpoint + new URL(request.url).search, {
      method: request.method, headers, body: request.method === "GET" ? undefined : await request.text(),
      cache: "no-store", redirect: "error", signal: request.signal,
    });
    const responseHeaders = new Headers({ "Cache-Control": "no-store", "X-Request-ID": requestId });
    for (const name of ["Content-Type", "X-Request-ID", "WWW-Authenticate", "Retry-After"]) {
      const value = upstream.headers.get(name); if (value) responseHeaders.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch { return failure(503, "SERVICE_UNAVAILABLE", "Service is temporarily unavailable."); }
}
export const GET = relay;
export const POST = relay;
export const DELETE = relay;

export const PATCH = relay;
