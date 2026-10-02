// Explicit localhost-only smoke against existing fake-provider development infrastructure.
const fs=require("node:fs"),ts=require("typescript"),assert=require("node:assert/strict");
require.extensions[".ts"]=(module,filename)=>module._compile(ts.transpileModule(fs.readFileSync(filename,"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,filename);
const {createAuthApi}=require("../shared/api/auth.ts");
const {createConnectionsApi}=require("../shared/api/connections.ts");
const {AuthSession}=require("../shared/auth/session.ts");
const {availableConnectionActions,connectionRole,connectionError}=require("../shared/connections/model.ts");
const baseUrl=process.env.FIDES_LIVE_API_URL||"http://127.0.0.1:8000/api/v1";
const base=new URL(baseUrl);
if(!["127.0.0.1","localhost"].includes(base.hostname))throw new Error("Live smoke is localhost-only");
async function expectError(run,code,status){await assert.rejects(run,error=>error.code===code&&error.status===status);}
(async()=>{
 const users=[];
 // Old persisted fake reference IDs can collide after provider restart. Bound fixture provisioning.
 for(let attempt=0;attempt<16&&users.length<3;attempt++){
  const phone="+1202555"+String(1000+Math.floor(Math.random()*9000));
  let session;const api=createAuthApi({baseUrl,accessToken:()=>session?.accessToken()});
  let challenge;
  try{challenge=await api.requestOtp("signup",phone);}
  catch(error){if(error.status===503)continue;throw error;}
  const response=await api.verifyOtp({challenge_id:challenge.challenge_id,code:"123456",display_name:"F2 disposable "+users.length,timezone:"Etc/UTC"});
  let stored=null;session=new AuthSession({read:async()=>stored,write:async v=>{stored=v;},clear:async()=>{stored=null;}},api);
  await session.establish(response);
  assert.equal(session.snapshot().status,"authenticated");
  const connections=createConnectionsApi({baseUrl,accessToken:session.accessToken});
  users.push({phone,session,connections,id:session.snapshot().user.id});
 }
 assert.equal(users.length,3,"Could not provision local fake-provider users");
 const [a,b,c]=users;let checks=0;
 const check=()=>{checks++;};
 let value=await a.connections.createConnection(b.phone);assert.equal(value.status,"PENDING");check();
 assert.equal(connectionRole((await a.connections.listConnections()).find(r=>r.id===value.id),a.id),"requester");check();
 assert.equal(connectionRole((await b.connections.listConnections()).find(r=>r.id===value.id),b.id),"recipient");check();
 await expectError(()=>a.connections.createConnection(b.phone),"CONFLICT",409);check();
 value=await b.connections.acceptConnection(value.id);assert.equal(value.status,"ACCEPTED");check();
 for(const user of[a,b])assert.equal((await user.connections.getConnection(value.id)).status,"ACCEPTED");check();
 const original=value;value=await a.connections.removeConnection(value.id);assert.equal(value.status,"REMOVED");check();
 value=await b.connections.createConnection(a.phone);assert.equal(value.id,original.id);assert.equal(value.created_at,original.created_at);
 assert.equal(value.requester.id,b.id);assert.equal(value.recipient.id,a.id);check();
 value=await a.connections.rejectConnection(value.id);assert.equal(value.status,"REMOVED");check();
 value=await a.connections.createConnection(b.phone);value=await b.connections.blockConnection(value.id);assert.equal(value.status,"BLOCKED");check();
 for(const user of[a,b])assert.deepEqual(availableConnectionActions(value,user.id),[]);check();
 await expectError(()=>a.connections.createConnection(b.phone),"CONFLICT",409);check();
 try{await a.connections.createConnection("+12025550000");assert.fail("Unknown number must be unavailable");}
 catch(error){assert.equal(error.code,"NOT_FOUND");assert.equal(connectionError(error,true),"We couldn't send a connection request to that number.");}check();
 await expectError(()=>c.connections.getConnection(value.id),"NOT_FOUND",404);check();
 for(const user of users)await user.session.logout();
 console.log("Live F2: "+checks+" checks passed with 3 disposable authenticated users; no financial calls.");
})().catch(error=>{console.error("Live F2 blocked:",error.code||error.name);process.exitCode=1;});
