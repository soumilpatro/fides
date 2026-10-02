// Isolated visual fixture ONLY. Never imported by the web/mobile applications.
// No database, SMS, product/financial data, real credentials, or persistent state.
const http = require("node:http");
const { randomUUID } = require("node:crypto");
if (process.env.NODE_ENV === "production") throw new Error("Visual fixture is development-only");
const challenges = new Map(); const sessions = new Map(); const accounts = new Map();
const timestamp = () => new Date().toISOString();
function credentials(user) {
  const value = { access_token: `visual-access-${randomUUID()}`, refresh_token: `visual-refresh-${randomUUID()}`, token_type: "Bearer", access_expires_at: new Date(Date.now() + 900000).toISOString(), refresh_expires_at: new Date(Date.now() + 2592000000).toISOString(), user };
  sessions.set(value.access_token, value); return value;
}
http.createServer(async (request, response) => {
  const origin = request.headers.origin;
  if (["http://localhost:8081", "http://127.0.0.1:8081", "http://localhost:3000", "http://127.0.0.1:3000"].includes(origin)) {
    response.setHeader("Access-Control-Allow-Origin", origin); response.setHeader("Vary", "Origin");
    response.setHeader("Access-Control-Allow-Headers", "Authorization,Content-Type");
    response.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
    response.setHeader("Access-Control-Expose-Headers", "Retry-After,X-Request-ID");
  }
  response.setHeader("Cache-Control", "no-store"); response.setHeader("Content-Type", "application/json"); response.setHeader("X-Request-ID", randomUUID());
  if (request.method === "OPTIONS") { response.writeHead(204); response.end(); return; }
  const send = (status, value) => { response.writeHead(status); response.end(JSON.stringify(value)); };
  const error = (status, code, message) => send(status, { error: { code, message } });
  const path = new URL(request.url, "http://localhost").pathname;
  let body = {}; try { let raw = ""; for await (const chunk of request) { raw += chunk; if (raw.length > 4096) throw new Error(); } if (raw) body = JSON.parse(raw); }
  catch { error(400, "MALFORMED_REQUEST", "Malformed request."); return; }
  if (path === "/api/v1/auth/otp/request" && request.method === "POST") {
    if (!/^\+[1-9][0-9]{7,14}$/.test(body.phone ?? "")) return error(422, "INVALID_PHONE", "Enter a valid international phone number.");
    if (!["signup", "login"].includes(body.intent)) return error(422, "VALIDATION_ERROR", "Invalid request.");
    const challenge_id = randomUUID(); const expires_at = new Date(Date.now() + 600000).toISOString();
    challenges.set(challenge_id, { ...body, expires_at }); return send(202, { challenge_id, expires_at, resend_after_seconds: 60, message: "Verification requested." });
  }
  if (path === "/api/v1/auth/otp/verify" && request.method === "POST") {
    const challenge = challenges.get(body.challenge_id);
    if (!challenge) return error(422, "OTP_INVALID_CHALLENGE", "Invalid verification challenge.");
    if (Date.parse(challenge.expires_at) < Date.now()) return error(422, "OTP_EXPIRED", "Verification code expired.");
    if (body.code !== (challenge.intent === "signup" ? "123456" : "654321")) return error(422, "OTP_INVALID", "Verification code is invalid.");
    let user = accounts.get(challenge.phone);
    if (challenge.intent === "signup") {
      if (user) return error(409, "AUTH_FLOW_NOT_ALLOWED", "This authentication flow is not allowed.");
      if (!body.display_name?.trim() || !body.timezone?.trim()) return error(422, "VALIDATION_ERROR", "Name and timezone are required.");
      user = { id: randomUUID(), phone_e164: challenge.phone, display_name: body.display_name, timezone: body.timezone, status: "ACTIVE", created_at: timestamp(), updated_at: timestamp() };
      accounts.set(challenge.phone, user);
    } else if (!user) return error(409, "AUTH_FLOW_NOT_ALLOWED", "This authentication flow is not allowed.");
    challenges.delete(body.challenge_id); return send(200, credentials(user));
  }
  if (path === "/api/v1/auth/refresh" && request.method === "POST") {
    const entry = [...sessions.values()].find(value => value.refresh_token === body.refresh_token);
    if (!entry) return error(401, "INVALID_REFRESH_TOKEN", "Invalid refresh credentials.");
    sessions.delete(entry.access_token); return send(200, credentials(entry.user));
  }
  const token = request.headers.authorization?.replace(/^Bearer /, ""); const entry = sessions.get(token);
  if (path === "/api/v1/me" && request.method === "GET") return entry ? send(200, entry.user) : error(401, "INVALID_AUTH_TOKEN", "Invalid authentication credentials.");
  if (path === "/api/v1/auth/logout" && request.method === "POST") { sessions.delete(token); return send(200, { logged_out: true }); }
  error(404, "NOT_FOUND", "Unavailable resource.");
}).listen(8765, "127.0.0.1", () => console.log("Auth-only visual fixture at http://127.0.0.1:8765/api/v1. No production/backend validation."));
