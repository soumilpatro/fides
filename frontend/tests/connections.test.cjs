const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const Module = require("node:module");
require.extensions[".ts"] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, filename);
const test = require("node:test");
const assert = require("node:assert/strict");
const { createConnectionsApi, connectionResponse } = require("../shared/api/connections.ts");
const rules = require("../shared/connections/model.ts");
const { ApiError } = require("../shared/api/errors.ts");
const { isAllowedApiRoute } = require("../shared/api/relay.ts");
const A="00000000-0000-4000-8000-000000000001", B="00000000-0000-4000-8000-000000000002", C="00000000-0000-4000-8000-000000000003";
const ID="00000000-0000-4000-8000-000000000004";
const row = (status="PENDING") => ({id:ID,status,requester:{id:A,display_name:"Alex"},recipient:{id:B,display_name:"Sam"},
  created_at:"2026-10-02T10:00:00Z",updated_at:"2026-10-02T11:00:00Z"});
for (const [name,method,suffix,args,body] of [
  ["createConnection","POST","",["+12025550198"],{phone:"+12025550198"}],
  ["listConnections","GET","",[],undefined],["getConnection","GET","/"+ID,[ID],undefined],
  ["acceptConnection","POST","/"+ID+"/accept",[ID],undefined],
  ["rejectConnection","POST","/"+ID+"/reject",[ID],undefined],
  ["blockConnection","POST","/"+ID+"/block",[ID],undefined],
  ["removeConnection","DELETE","/"+ID,[ID],undefined],
]) test("wire operation "+name, async () => {
  const calls=[]; const api=createConnectionsApi({baseUrl:"https://fides.example/api/v1",accessToken:()=>"memory-token",
    fetcher:async(url,init)=>{calls.push({url,init});return Response.json(name==="listConnections"?[row()]:row());}});
  await api[name](...args); assert.equal(calls.length,1);
  const {url,init}=calls[0]; assert.equal(url,"https://fides.example/api/v1/connections"+suffix);
  assert.equal(init.method,method);assert.equal(init.headers.get("Authorization"),"Bearer memory-token");
  assert.equal(init.headers.has("Idempotency-Key"),false);assert.equal(init.credentials,"omit");
  assert.equal(init.cache,"no-store");assert.equal(init.body,body?JSON.stringify(body):undefined);
});
test("closed response drops private participant fields",()=>{
  const input={...row(),phone:"+12025550198",requester:{...row().requester,phone_e164:"+12025550198",token:"private"}};
  assert.deepEqual(connectionResponse(input),row());assert.equal(JSON.stringify(connectionResponse(input)).includes("+1202"),false);
});
for(const bad of [null,{}, {...row(),status:"REJECTED"},{...row(),id:"../me"},{...row(),updated_at:null},{...row(),recipient:null}])
test("invalid wire response rejected "+JSON.stringify(bad),()=>assert.throws(()=>connectionResponse(bad),error=>error.code==="INVALID_RESPONSE"));
test("invalid ID cannot dispatch transport",async()=>{
  let calls=0;const api=createConnectionsApi({baseUrl:"https://fides.example/api/v1",fetcher:async()=>{calls++;return Response.json(row());}});
  await assert.rejects(async()=>api.getConnection("../me"));assert.equal(calls,0);
});
for(const status of ["PENDING","ACCEPTED","BLOCKED","REMOVED"]) for(const actor of [A,B,C])
test("role/actions "+status+" "+actor,()=>{
  const value=row(status); assert.equal(rules.connectionRole(value,actor),actor===A?"requester":actor===B?"recipient":null);
  const expected=actor===C?[]:status==="PENDING"?actor===B?["accept","reject","block"]:["remove","block"]:status==="ACCEPTED"?["remove","block"]:[];
  assert.deepEqual(rules.availableConnectionActions(value,actor),expected);
  assert.equal(rules.otherParticipant(value,actor)?.id,actor===A?B:actor===B?A:undefined);
});
test("sectioning preserves server order and includes terminal rows",()=>{
  const values=[row("REMOVED"),{...row(),id:C},row("BLOCKED"),row("ACCEPTED"),{...row(),id:B}];
  const sections=rules.connectionSections(values,A);
  assert.deepEqual(sections.map(s=>s.title),["Sent requests","Connections","Blocked","Removed"]);
  assert.deepEqual(sections[0].rows.map(r=>r.id),[C,B]);
  assert.equal(rules.statusLabel.REMOVED,"Removed"); assert.deepEqual(rules.connectionSections([],A),[]);
});
test("same-party invalid role fails closed",()=>{
  assert.equal(rules.connectionRole({...row(),recipient:row().requester},A),null);
});
test("NOT_FOUND never distinguishes account existence",()=>{
  assert.equal(rules.connectionError(new ApiError("NOT_FOUND","Unavailable resource.",404),true),"We couldn't send a connection request to that number.");
  for(const code of ["NETWORK_ERROR","SERVICE_UNAVAILABLE","HTTP_ERROR"])
    assert.equal(rules.connectionError(new ApiError(code,"private phone token",503)).includes("private"),false);
});
const allowed=[["GET","connections"],["POST","connections"],["GET","connections/"+ID],["DELETE","connections/"+ID],
  ...["accept","reject","block"].map(a=>["POST","connections/"+ID+"/"+a]),["GET","me"],
  ...["otp/request","otp/verify","refresh","logout"].map(a=>["POST","auth/"+a])];
for(const [method,endpoint] of allowed) test("relay allows "+method+" "+endpoint,()=>assert.equal(isAllowedApiRoute(method,endpoint.split("/")),true));
for(const [method,endpoint] of [["PATCH","connections/"+ID],["DELETE","connections"],["POST","connections/"+ID],
  ["GET","connections/"+ID+"/accept"],["POST","connections/"+ID+"/unblock"],["GET","commitments/"+ID+"/repayments"],["GET","summary"],
  ["GET","connections/../me"],["GET","connections/%2e%2e/me"],["GET","connections/"+ID+"/extra"],
  ["GET","connections//"+ID],["POST","auth/../refresh"],["GET","connections/https://x"]])
test("relay rejects "+method+" "+endpoint,()=>assert.equal(isAllowedApiRoute(method,endpoint.split("/")),false));
test("actual DELETE relay forwards only safe headers",async t=>{
  const old=Module._load; Module._load=function(request,parent,main){
    if(request.startsWith("@fides/shared/"))return old.call(this,path.join(__dirname,"../shared",request.slice("@fides/shared/".length)+".ts"),parent,main);
    return old.call(this,request,parent,main);
  };
  let route;try{route=require("../web/app/api/v1/[...path]/route.ts");}finally{Module._load=old;}
  t.mock.method(global,"fetch",async(url,init)=>{
    assert.equal(url,"http://127.0.0.1:8000/api/v1/connections/"+ID);assert.equal(init.method,"DELETE");
    assert.equal(init.headers.get("Authorization"),"Bearer memory");assert.equal(init.headers.has("Cookie"),false);
    assert.equal(init.headers.has("X-Forwarded-For"),false);
    return Response.json(row("REMOVED"),{headers:{"Retry-After":"10","WWW-Authenticate":"Bearer","X-Request-ID":"server-id","Set-Cookie":"private"}});
  });
  const previous=process.env.FIDES_BACKEND_API_URL;process.env.FIDES_BACKEND_API_URL="http://127.0.0.1:8000/api/v1";
  try {
    const response=await route.DELETE(new Request("http://localhost/api/v1/connections/"+ID,{method:"DELETE",headers:{Authorization:"Bearer memory",Cookie:"private","X-Forwarded-For":"private"}}),{params:Promise.resolve({path:["connections",ID]})});
    assert.equal(response.status,200);assert.equal(response.headers.get("Cache-Control"),"no-store");
    assert.equal(response.headers.get("X-Request-ID"),"server-id");assert.equal(response.headers.get("Retry-After"),"10");
    assert.equal(response.headers.get("WWW-Authenticate"),"Bearer");assert.equal(response.headers.has("Set-Cookie"),false);
  }finally{if(previous===undefined)delete process.env.FIDES_BACKEND_API_URL;else process.env.FIDES_BACKEND_API_URL=previous;}
});
// Tiny hook harness uses the existing Node runner; no UI/state/test dependency.
function harness(platform,overrides={}) {
  let current=row();const calls={read:0,mutation:0,recovery:0};
  const connections={listConnections:async()=>{calls.read++;return [current];},getConnection:async()=>current,
    acceptConnection:async()=>{calls.mutation++;current=row("ACCEPTED");return current;},
    rejectConnection:async()=>{calls.mutation++;current=row("REMOVED");return current;},
    blockConnection:async()=>{calls.mutation++;current=row("BLOCKED");return current;},
    removeConnection:async()=>{calls.mutation++;current=row("REMOVED");return current;},...overrides};
  const env={state:{status:"authenticated",user:{id:B}},connections,session:{snapshot:()=>env.state,bootstrap:async()=>{calls.recovery++;}}};
  let index=0;const slots=[];const effects=[];
  const same=(a,b)=>a&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
  const react={
    useState(initial){const i=index++;if(!slots[i])slots[i]={value:typeof initial==="function"?initial():initial};return[slots[i].value,v=>{slots[i].value=typeof v==="function"?v(slots[i].value):v;}];},
    useRef(initial){const i=index++;return slots[i]??(slots[i]={current:initial});},
    useCallback(fn,deps){const i=index++;if(!slots[i]||!same(slots[i].deps,deps))slots[i]={fn,deps};return slots[i].fn;},
    useEffect(fn,deps){const i=index++;if(!slots[i]||!same(slots[i].deps,deps)){slots[i]?.cleanup?.();slots[i]={deps};effects.push(()=>{slots[i].cleanup=fn();});}},
  };
  const old=Module._load;Module._load=function(request,parent,main){
    if(request==="react")return react;if(request==="../auth/useAuth")return{useAuth:()=>env};
    return old.call(this,request,parent,main);
  };
  const file=require.resolve("../"+platform+"/features/connections/useConnections.ts");let hook;
  try{delete require.cache[file];hook=require(file).useConnections;}finally{Module._load=old;delete require.cache[file];}
  const render=()=>{index=0;const result=hook(ID);while(effects.length)effects.shift()();return result;};
  return{render,calls,connections,env};
}
const settle=()=>new Promise(setImmediate);
for(const platform of ["web","mobile"]) {
  test(platform+": no optimistic transition; duplicate mutation guarded",async()=>{
    const h=harness(platform);h.render();await settle();let resolve;
    h.connections.acceptConnection=()=>{h.calls.mutation++;return new Promise(r=>{resolve=r;});};
    const data=h.render();const pending=data.action("accept",data.detail);
    assert.equal(h.render().detail.status,"PENDING");assert.equal(h.render().busy,true);
    await h.render().action("accept",data.detail);assert.equal(h.calls.mutation,1);
    const server={...row("ACCEPTED"),updated_at:"2026-10-02T12:00:00Z"};
    h.connections.getConnection=async()=>server;h.connections.listConnections=async()=>[server];
    resolve(server);await pending;assert.deepEqual(h.render().detail,server);
  });
  test(platform+": ambiguous mutation reconciles; never auto-replays",async()=>{
    const h=harness(platform);h.render();await settle();
    h.connections.blockConnection=async()=>{h.calls.mutation++;h.connections.getConnection=async()=>row("BLOCKED");
      h.connections.listConnections=async()=>[row("BLOCKED")];throw new ApiError("NETWORK_ERROR","Unable to reach Fides.",null);};
    await h.render().action("block",h.render().detail);
    const data=h.render();assert.equal(h.calls.mutation,1);assert.equal(data.detail.status,"BLOCKED");
    assert.equal(data.uncertain,false);assert.ok(data.error);
  });
  test(platform+": failed reconciliation preserves data and disables retry",async()=>{
    const h=harness(platform);h.render();await settle();
    h.connections.rejectConnection=async()=>{h.calls.mutation++;throw new ApiError("NETWORK_ERROR","Unable to reach Fides.",null);};
    h.connections.listConnections=async()=>{throw new ApiError("NETWORK_ERROR","Unable to reach Fides.",null);};
    await h.render().action("reject",h.render().detail);assert.equal(h.render().detail.status,"PENDING");
    assert.equal(h.render().uncertain,true);await h.render().action("reject",h.render().detail);assert.equal(h.calls.mutation,1);
    h.connections.listConnections=async()=>[row("REMOVED")];h.connections.getConnection=async()=>row("REMOVED");
    await h.render().refresh();assert.equal(h.render().uncertain,false);assert.equal(h.render().detail.status,"REMOVED");
  });
  test(platform+": GET auth recovery is bounded and reuses session",async()=>{
    let reads=0;const h=harness(platform,{listConnections:async()=>{if(++reads===1)throw new ApiError("AUTH_TOKEN_EXPIRED","Expired.",401);return[row()];}});
    h.render();await settle();assert.equal(h.calls.recovery,1);assert.equal(reads,2);assert.equal(h.render().detail.status,"PENDING");
  });
  test(platform+": unrelated response fails closed",async()=>{
    const h=harness(platform);h.env.state.user.id=C;h.render();await settle();assert.equal(h.render().detail,null);assert.ok(h.render().error);
  });
}

test("confirmation titles do not duplicate request", () => {
  assert.equal(rules.confirmation("remove", row()).title, "Cancel request?");
  assert.equal(rules.confirmation("reject", row()).title, "Decline request?");
});
test("transport deadline aborts once without replay", async () => {
  const original = global.setTimeout;
  let calls = 0;
  global.setTimeout = callback => original(callback, 5);
  try {
    const api = createConnectionsApi({ baseUrl: "https://fides.example/api/v1", fetcher: async (_url, init) => {
      calls++;
      return new Promise((_resolve, reject) => init.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
    }});
    await assert.rejects(api.createConnection("+12025550198"), error => error.code === "NETWORK_ERROR");
    assert.equal(calls, 1);
  } finally { global.setTimeout = original; }
});
