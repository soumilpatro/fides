// Existing Node runner and workspace TypeScript: no added test framework.
const fs = require("node:fs");
const ts = require("typescript");
require.extensions[".ts"] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, filename);
const test = require("node:test");
const assert = require("node:assert/strict");
const { AuthSession, validCredentials, safeMessage } = require("../shared/auth/session.ts");
const { createAuthApi } = require("../shared/api/auth.ts");
const { ApiError } = require("../shared/api/errors.ts");
const user = { id: "user", display_name: "Server name", timezone: "Europe/London", status: "ACTIVE", phone_e164: "+12025550198", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
function credentials(suffix = "old", expired = false) {
  return { access_token: `access-${suffix}`, refresh_token: `refresh-${suffix}`, token_type: "Bearer", access_expires_at: new Date(Date.now() + (expired ? -1000 : 60000)).toISOString(), refresh_expires_at: new Date(Date.now() + 3600000).toISOString() };
}
function setup(initial = null, overrides = {}) {
  let stored = initial; const writes = []; const calls = { refresh: [], me: 0 };
  const store = { read: async () => stored, write: async value => { stored = { ...value }; writes.push(value); }, clear: async () => { stored = null; } };
  const api = { refreshSession: async token => { calls.refresh.push(token); return { ...credentials("new"), user }; }, getMe: async () => { calls.me++; return user; }, logout: async () => ({ logged_out: true }), ...overrides };
  return { session: new AuthSession(store, api), store, calls, writes, stored: () => stored };
}
test("anonymous bootstrap never requests /me", async () => {
  const f = setup(); assert.equal(f.session.snapshot().status, "loading"); await f.session.bootstrap();
  assert.deepEqual(f.session.snapshot(), { status: "anonymous" }); assert.equal(f.calls.me, 0);
});
test("persistence excludes cached user and reconciles authoritative /me", async () => {
  const f = setup(); await f.session.establish({ ...credentials(), user: { ...user, display_name: "Cached" } });
  assert.deepEqual(f.session.snapshot(), { status: "authenticated", user }); assert.deepEqual(Object.keys(f.stored()).sort(), Object.keys(credentials()).sort());
});
test("restoration stays loading until /me resolves", async () => {
  let complete; const f = setup(credentials(), { getMe: () => new Promise(resolve => { complete = resolve; }) });
  const pending = f.session.bootstrap(); await new Promise(setImmediate); assert.equal(f.session.snapshot().status, "loading");
  complete(user); await pending; assert.equal(f.session.snapshot().status, "authenticated");
});
test("expired access rotates both tokens in one write", async () => {
  const f = setup(credentials("old", true)); await f.session.bootstrap(); assert.deepEqual(f.calls.refresh, ["refresh-old"]);
  assert.equal(f.writes.length, 1); assert.equal(f.stored().refresh_token, "refresh-new"); assert.equal(f.session.accessToken(), "access-new");
});
test("concurrent refreshes share one flight", async () => {
  const f = setup(credentials()); await f.session.bootstrap(); await Promise.all([f.session.refresh(), f.session.refresh(), f.session.refresh()]);
  assert.deepEqual(f.calls.refresh, ["refresh-old"]);
});
test("/me token expiry permits exactly one refresh", async () => {
  let count = 0; const f = setup(credentials(), { getMe: async () => { if (++count === 1) throw new ApiError("AUTH_TOKEN_EXPIRED", "Expired", 401); return user; } });
  await f.session.bootstrap(); assert.equal(f.calls.refresh.length, 1); assert.equal(count, 2);
});
test("a rejected rotated token does not rotate again", async () => {
  let fail = false; const f = setup(credentials(), { getMe: async () => { if (fail) throw new ApiError("INVALID_AUTH_TOKEN", "Invalid", 401); return user; } });
  await f.session.bootstrap(); fail = true; await f.session.refresh(); assert.equal(f.calls.refresh.length, 1);
  assert.equal(f.stored(), null); assert.equal(f.session.accessToken(), null);
});
for (const code of ["INVALID_REFRESH_TOKEN", "REFRESH_TOKEN_EXPIRED", "SESSION_REVOKED", "ACCOUNT_DEACTIVATED", "ACCOUNT_UNAVAILABLE"]) {
  test(`${code} clears session without retry`, async () => {
    let count = 0; const f = setup(credentials("old", true), { refreshSession: async () => { count++; throw new ApiError(code, "Unavailable", code.startsWith("ACCOUNT") ? 403 : 401); } });
    await f.session.bootstrap(); assert.equal(count, 1); assert.equal(f.stored(), null); assert.equal(f.session.snapshot().status, "anonymous");
  });
}
test("transient failure hides protected UI and supports explicit retry", async () => {
  let count = 0; const f = setup(credentials(), { getMe: async () => { if (++count === 1) throw new ApiError("NETWORK_ERROR", "Unable to reach Fides.", null); return user; } });
  await f.session.bootstrap(); assert.equal(count, 1); assert.equal(f.session.snapshot().status, "anonymous"); assert.ok(f.stored());
  await f.session.bootstrap(); assert.equal(f.session.snapshot().status, "authenticated");
});
test("storage write failure cannot retain previous refresh credentials", async () => {
  const f = setup(credentials()); await f.session.bootstrap(); f.store.write = async () => { throw new Error("private detail"); };
  await f.session.refresh(); assert.equal(f.stored(), null); assert.equal(f.session.accessToken(), null);
  assert.equal(f.session.snapshot().error, "Unable to continue. Please try again.");
});
test("logout clears local credentials despite server/network failure", async () => {
  const f = setup(credentials(), { logout: async () => { throw new Error("network"); } }); await f.session.bootstrap(); await f.session.logout();
  assert.equal(f.stored(), null); assert.equal(f.session.accessToken(), null); assert.deepEqual(f.session.snapshot(), { status: "anonymous" });
});
test("logout after rotation revokes current access token", async () => {
  let release; let observed; const f = setup(credentials(), { refreshSession: () => new Promise(resolve => { release = () => resolve({ ...credentials("new"), user }); }), logout: async () => { observed = f.session.accessToken(); return { logged_out: true }; } });
  await f.session.bootstrap(); const rotation = f.session.refresh(); const exit = f.session.logout(); await new Promise(setImmediate); release(); await Promise.all([rotation, exit]);
  assert.equal(observed, "access-new"); assert.equal(f.stored(), null);
});
test("invalid stored shape is cleared, internal errors remain generic", async () => {
  const f = setup({ access_token: "incomplete" }); await f.session.bootstrap(); assert.equal(f.stored(), null); assert.equal(f.calls.me, 0);
  assert.equal(validCredentials(null), false); assert.equal(validCredentials(credentials()), true);
  assert.equal(safeMessage(new Error("private detail")), "Unable to continue. Please try again.");
});
test("auth API exact payloads and bearer only on protected operations", async () => {
  const calls = []; const api = createAuthApi({ baseUrl: "https://api.example/api/v1", accessToken: () => "access-test", fetcher: async (url, init) => { calls.push({ url, ...init }); return Response.json(url.endsWith("/me") ? user : { ...credentials(), user }); } });
  await api.requestOtp("signup", "+12025550198"); await api.verifyOtp({ challenge_id: "challenge", code: "123456", display_name: "Name", timezone: "Europe/London" });
  await api.verifyOtp({ challenge_id: "challenge", code: "654321" }); await api.refreshSession("refresh-old"); await api.getMe(); await api.logout();
  assert.deepEqual(calls.slice(0, 4).map(c => JSON.parse(c.body)), [{ intent: "signup", phone: "+12025550198" }, { challenge_id: "challenge", code: "123456", display_name: "Name", timezone: "Europe/London" }, { challenge_id: "challenge", code: "654321" }, { refresh_token: "refresh-old" }]);
  assert.ok(calls.slice(0, 4).every(c => !c.headers.has("Authorization"))); assert.ok(calls.slice(4).every(c => c.headers.get("Authorization") === "Bearer access-test"));
  assert.ok(calls.every(c => c.credentials === "omit" && c.cache === "no-store" && c.redirect === "error"));
});
test("OTP error retains backend code/message/Retry-After with no retry", async () => {
  let count = 0; const api = createAuthApi({ baseUrl: "https://api.example/api/v1", fetcher: async () => { count++; return Response.json({ error: { code: "OTP_RATE_LIMITED", message: "Please wait." } }, { status: 429, headers: { "Retry-After": "60" } }); } });
  await assert.rejects(api.requestOtp("login", "+12025550198"), error => error.code === "OTP_RATE_LIMITED" && error.message === "Please wait." && error.retryAfterSeconds === 60); assert.equal(count, 1);
});
test("queued bootstrap/refresh cannot rotate the same old credential twice", async () => {
  const f = setup(credentials()); await f.session.bootstrap();
  f.stored().access_expires_at = new Date(Date.now() - 1000).toISOString();
  await Promise.all([f.session.bootstrap(), f.session.refresh()]); assert.deepEqual(f.calls.refresh, ["refresh-old"]);
});
test("transport deadline aborts a hung auth call without retry", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] }); let count = 0;
  const api = createAuthApi({ baseUrl: "https://api.example/api/v1", fetcher: async (_, init) => {
    count++; return new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(new Error("aborted"))));
  } });
  const pending = api.logout(); const rejection = assert.rejects(pending, error => error.code === "NETWORK_ERROR");
  await Promise.resolve(); t.mock.timers.tick(15000); await rejection; assert.equal(count, 1);
});
test("signup UX counts Unicode names and never supplies a timezone fallback", () => {
  const { profileReady, detectedTimezone, maskedPhone } = require("../shared/auth/flow.ts");
  assert.equal(profileReady("😀".repeat(100), "Europe/London"), true);
  assert.equal(profileReady("a".repeat(101), "Europe/London"), false);
  assert.equal(profileReady("Name\n", "Europe/London"), false);
  assert.equal(profileReady("Name", "  "), false);
  assert.equal(typeof detectedTimezone(), "string"); assert.equal(maskedPhone("+12025550198").includes("5550198"), false);
});
test("native SessionStore writes both credentials as one secure record", async () => {
  const Module = require("node:module"); const load = Module._load; const writes = []; let saved = null;
  const fakeSecure = { WHEN_UNLOCKED_THIS_DEVICE_ONLY: 4, getItemAsync: async () => saved, setItemAsync: async (key, value, options) => { writes.push({key,value,options}); saved = value; }, deleteItemAsync: async () => { saved = null; } };
  Module._load = function(request, parent, main) {
    if (request === "expo-secure-store") return fakeSecure;
    if (request === "react-native") return { Platform: { OS: "ios" } };
    return load.call(this, request, parent, main);
  };
  let store; const path = require.resolve("../mobile/features/auth/session/session-store.ts");
  try { delete require.cache[path]; store = require(path).secureSessionStore(); } finally { Module._load = load; delete require.cache[path]; }
  const value = credentials(); await store.write(value); assert.equal(writes.length, 1); assert.deepEqual(JSON.parse(writes[0].value), value);
  assert.equal(writes[0].options.keychainAccessible, 4); assert.deepEqual(await store.read(), JSON.parse(saved));
  await store.clear(); assert.equal(await store.read(), null);
});
test("web SessionStore copies credentials in memory and starts empty on recreation", async () => {
  const { memorySessionStore } = require("../web/features/auth/session/session-store.ts"); const store = memorySessionStore();
  const value = credentials(); await store.write(value); value.refresh_token = "changed-outside-store";
  assert.equal((await store.read()).refresh_token, "refresh-old"); assert.equal(await memorySessionStore().read(), null);
  await store.clear(); assert.equal(await store.read(), null);
});
test("secure deletion failure is surfaced without keeping protected UI", async () => {
  const f = setup(credentials()); await f.session.bootstrap(); f.store.clear = async () => { throw new Error("storage unavailable"); };
  await f.session.logout(); assert.equal(f.session.accessToken(), null); assert.equal(f.session.snapshot().status, "anonymous");
  assert.match(f.session.snapshot().error, /retry sign out/);
});
