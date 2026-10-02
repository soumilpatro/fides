// Local current-main backend only. Disposable development users, no F4 endpoints.
const fs=require("node:fs"),ts=require("typescript"),{randomUUID}=require("node:crypto"),assert=require("node:assert/strict");
require.extensions[".ts"]=(m,f)=>m._compile(ts.transpileModule(fs.readFileSync(f,"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,f);
const {createAuthApi}=require("../shared/api/auth.ts"),{AuthSession}=require("../shared/auth/session.ts");
const {createConnectionsApi}=require("../shared/api/connections.ts"),{createCommitmentsApi}=require("../shared/api/commitments.ts");
const {proposalActions}=require("../shared/commitments/model.ts"),{MutationIntents}=require("../shared/commitments/intents.ts");
const baseUrl=process.env.FIDES_LIVE_API_URL||"http://127.0.0.1:8000/api/v1";
if(!["127.0.0.1","localhost","[::1]"].includes(new URL(baseUrl).hostname))throw new Error("Disposable users require a local development backend");
const users=[];let checks=0;const check=()=>{checks++;};
async function expectError(run,code,status){await assert.rejects(run,e=>e.code===code&&e.status===status);}
(async()=>{
 try{
  for(let attempt=0;users.length<3&&attempt<16;attempt++){
   const phone="+1202"+String(5500000+Math.floor(Math.random()*4000000));let session;
   const auth=createAuthApi({baseUrl,accessToken:()=>session?.accessToken()});let challenge;
   try{challenge=await auth.requestOtp("signup",phone);}catch(e){if(e.status===503)continue;throw e;}
   const response=await auth.verifyOtp({challenge_id:challenge.challenge_id,code:"123456",display_name:"F3 disposable "+users.length,timezone:users.length===0?"Asia/Kolkata":"Etc/UTC"});
   let stored=null;session=new AuthSession({read:async()=>stored,write:async v=>{stored=v;},clear:async()=>{stored=null;}},auth);
   await session.establish(response);assert.equal(session.snapshot().status,"authenticated");
   users.push({phone,session,id:session.snapshot().user.id,connections:createConnectionsApi({baseUrl,accessToken:session.accessToken}),api:createCommitmentsApi({baseUrl,accessToken:session.accessToken})});
  }
  assert.equal(users.length,3,"Local fake-provider provisioning unavailable");
  const[a,b,c]=users;let connection=await a.connections.createConnection(b.phone);connection=await b.connections.acceptConnection(connection.id);assert.equal(connection.status,"ACCEPTED");check();
  const terms={due_date:null,interest_type:"NONE",interest_rate_bps:null,grace_period_days:0,installment_dates:null};
  const body={connection_id:connection.id,actor_role:"BORROWER",type:"IOU",principal_amount_minor:10001,currency:"INR",description:"F3 local validation",terms};
  let value=await a.api.createCommitment(body,randomUUID());assert.equal(value.status,"PENDING_CONFIRMATION");check();
  assert.deepEqual(proposalActions(value,a.id),["cancel"]);check();assert.deepEqual(proposalActions(value,b.id),["confirm","reject"]);check();
  value=await b.api.confirmCommitment(value.id,randomUUID());assert.equal(value.status,"ACTIVE");check();
  for(const user of[a,b]){assert.equal((await user.api.getCommitment(value.id)).status,"ACTIVE");check();const projection=await user.api.getCommitmentTerms(value.id);assert.equal(projection.versions[0].schedule_mode,"none");assert.equal(projection.versions[0].due_timezone,"Asia/Kolkata");check();}
  const single={...body,actor_role:"LENDER",type:"PEER_LOAN",currency:"USD",terms:{...terms,due_date:"2027-01-15",grace_period_days:3}};
  let rejected=await a.api.createCommitment(single,randomUUID());check();const singleTerms=await b.api.getCommitmentTerms(rejected.id);assert.equal(singleTerms.versions[0].due_date,"2027-01-15");assert.equal(singleTerms.versions[0].due_timezone,"Etc/UTC");check();
  rejected=await b.api.rejectCommitment(rejected.id,randomUUID());assert.equal(rejected.status,"REJECTED");check();
  let cancelled=await a.api.createCommitment({...body,currency:"GBP"},randomUUID());cancelled=await a.api.cancelCommitment(cancelled.id,randomUUID());assert.equal(cancelled.status,"CANCELLED");check();
  const scheduleBody={...body,terms:{...terms,interest_type:"SIMPLE_FIXED",interest_rate_bps:525,grace_period_days:7,installment_dates:["2027-02-01","2027-03-01","2027-04-01"]}};
  let scheduled=await a.api.createCommitment(scheduleBody,randomUUID());check();
  const projection=await a.api.getCommitmentTerms(scheduled.id);const current=projection.versions.find(v=>v.id===projection.current_terms_version_id);assert.equal(current.interest_rate_bps,525);assert.equal(current.grace_period_days,7);assert.deepEqual(current.installment_dates,scheduleBody.terms.installment_dates);check();
  const installments=await b.api.getCommitmentInstallments(scheduled.id);assert.deepEqual(installments.map(i=>[i.principal_amount_minor,i.interest_amount_minor,i.total_due_minor]),[[3333,175,3508],[3333,175,3508],[3335,175,3510]]);check();
  assert.equal(installments.every(i=>i.status==="PENDING"&&i.currency==="INR"),true);check();
  const stableKey=randomUUID();const original=await a.api.createCommitment(body,stableKey);check();
  assert.deepEqual(await a.api.createCommitment(body,stableKey),original);check();
  await expectError(()=>a.api.createCommitment({...body,description:"changed"},stableKey),"IDEMPOTENCY_CONFLICT",409);check();
  // Lose a real committed response, then explicitly replay the same logical intent.
  const intents=new MutationIntents(),scope=a.id+":new:create";const intent=intents.begin(scope,body,randomUUID);let dropped=false;
  const transport=createCommitmentsApi({baseUrl,accessToken:a.session.accessToken,fetcher:async(url,init)=>{
   const response=await fetch(url,init);if(!dropped&&init.method==="POST"){dropped=true;await response.json();throw new Error("simulated lost acknowledgement");}return response;}});
  try{await transport.createCommitment(body,intent.key);assert.fail("Response loss expected");}catch(error){intents.failed(scope,error);}
  const before=await a.api.listCommitments();intents.reconciled(scope);const replay=await a.api.createCommitment(body,intents.begin(scope,body).key);intents.succeeded(scope);const after=await a.api.listCommitments();assert.equal(after.length,before.length);assert.ok(before.some(r=>r.id===replay.id));check();
  assert.ok(after.length>=6);assert.equal(new Set(after.map(r=>r.id)).size,after.length);check();
  for(const get of[()=>c.api.getCommitment(value.id),()=>c.api.getCommitmentTerms(value.id),()=>c.api.getCommitmentInstallments(value.id)]){await expectError(get,"NOT_FOUND",404);check();}
  const raw=await (await fetch(baseUrl+"/commitments/"+value.id,{headers:{Authorization:"Bearer "+a.session.accessToken()}})).json();
  assert.equal(JSON.stringify(raw).includes(a.phone),false);assert.equal(JSON.stringify(raw).includes(b.phone),false);assert.deepEqual(Object.keys(raw.borrower).sort(),["display_name","id"]);check();
  let pending=await a.api.createCommitment(body,randomUUID());check();await a.connections.blockConnection(connection.id);check();
  await expectError(()=>b.api.confirmCommitment(pending.id,randomUUID()),"INVALID_STATE",409);check();
  for(const user of[a,b]){assert.equal((await user.api.getCommitment(pending.id)).status,"PENDING_CONFIRMATION");await user.api.getCommitmentTerms(pending.id);check();}
  pending=await b.api.rejectCommitment(pending.id,randomUUID());assert.equal(pending.status,"REJECTED");check();
  scheduled=await a.api.cancelCommitment(scheduled.id,randomUUID());assert.equal(scheduled.status,"CANCELLED");check();
  console.log("Live F3: "+checks+" checks passed using 3 disposable users; only auth, Connections and approved F3 routes.");
 } finally {for(const user of users)await user.session.logout();}
})().catch(error=>{console.error("Live F3 blocked:",error.code||error.name);process.exitCode=1;});
