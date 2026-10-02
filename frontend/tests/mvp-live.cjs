// Local current-main backend only. Disposable development users, approved F5 reads with existing setup endpoints.
const fs=require("node:fs"),ts=require("typescript"),{randomUUID}=require("node:crypto"),assert=require("node:assert/strict");
require.extensions[".ts"]=(m,f)=>m._compile(ts.transpileModule(fs.readFileSync(f,"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,f);
const {createAuthApi}=require("../shared/api/auth.ts"),{AuthSession}=require("../shared/auth/session.ts");
const {createConnectionsApi}=require("../shared/api/connections.ts"),{createCommitmentsApi}=require("../shared/api/commitments.ts");
const {createRepaymentsApi}=require("../shared/api/repayments.ts");
const {createDashboardApi}=require("../shared/api/dashboard.ts"),{createLedgerApi}=require("../shared/api/ledger.ts");
const baseUrl=process.env.FIDES_LIVE_API_URL||"http://127.0.0.1:8000/api/v1";
if(!["127.0.0.1","localhost","[::1]"].includes(new URL(baseUrl).hostname))throw new Error("Local disposable validation only");
// Separate local test client, independent of earlier fixtures.
const http=require("node:http");
const localFetcher=async(url,init)=>new Promise((resolve,reject)=>{
 const request=http.request(url,{method:init.method,headers:Object.fromEntries(init.headers),localAddress:"127.0.0.2"},response=>{
  const chunks=[];response.on("data",chunk=>chunks.push(chunk));response.on("end",()=>resolve(new Response(Buffer.concat(chunks),{status:response.statusCode,headers:response.headers})));
 });request.on("error",reject);if(init.body)request.write(init.body);request.end();
});
const {createExtensionsApi}=require("../shared/api/extensions.ts"),{createNotificationsApi}=require("../shared/api/notifications.ts"),{createProfileApi}=require("../shared/api/profile.ts");
const users=[];let checks={extensions:0,notifications:0,profile:0};let category='extensions';const check=(v,msg)=>{assert.ok(v,msg);checks[category]++;};
(async()=>{try{
for(let attempt=0;users.length<3&&attempt<96;attempt++){
 const phone='+1202'+String(5500000+Math.floor(Math.random()*4000000));let session;
 // Each ordinary local client retains the backend's rate limits. Provider restart references may collide with retained dev challenges.
 const source="127.0.0."+String(10+Math.floor(attempt/16));
 const fetcher=async(url,init)=>new Promise((resolve,reject)=>{const req=http.request(url,{method:init.method,headers:Object.fromEntries(init.headers),localAddress:source},res=>{const parts=[];res.on("data",p=>parts.push(p));res.on("end",()=>resolve(new Response(Buffer.concat(parts),{status:res.statusCode,headers:res.headers})));});req.on("error",reject);if(init.body)req.write(init.body);req.end();});
 const auth=createAuthApi({baseUrl,fetcher,accessToken:()=>session?.accessToken()});let challenge;
 try{challenge=await auth.requestOtp('signup',phone);}catch(e){if(e.status===503)continue;throw e;}
 const response=await auth.verifyOtp({challenge_id:challenge.challenge_id,code:'123456',display_name:'F6 disposable '+users.length,timezone:'Etc/UTC'});let stored=null;
 session=new AuthSession({read:async()=>stored,write:async v=>stored=v,clear:async()=>{stored=null;}},auth);await session.establish(response);
 const config={baseUrl,accessToken:session.accessToken};users.push({phone,id:session.snapshot().user.id,session,auth,connections:createConnectionsApi(config),api:createCommitmentsApi(config),repayments:createRepaymentsApi(config),ledger:createLedgerApi(config),extensions:createExtensionsApi(config),notifications:createNotificationsApi(config),profile:createProfileApi(config)});
}
assert.equal(users.length,3);const [a,b,c]=users;
let link=await a.connections.createConnection(b.phone);link=await b.connections.acceptConnection(link.id);
async function create(terms){const p=await a.api.createCommitment({connection_id:link.id,actor_role:'BORROWER',type:'IOU',principal_amount_minor:10000,currency:'INR',description:'F6 local validation',terms:{due_date:'2026-12-01',interest_type:'NONE',interest_rate_bps:null,grace_period_days:0,installment_dates:null,...terms}},randomUUID());return b.api.confirmCommitment(p.id,randomUUID());}
const parent=await create({});check(parent.status==='ACTIVE');const key=randomUUID(),body={requested_due_date:'2027-01-01',reason:'Local validation'};
const request=await a.extensions.requestExtension(parent.id,body,key);check(request.status==='REQUESTED');check(request.requested_by.id===a.id);check((await a.extensions.listExtensions(parent.id))[0].id===request.id);
for(const action of ['accept','reject']){await assert.rejects(()=>a.extensions[action+'Extension'](request.id,parent.id,randomUUID()),e=>e.code==='FORBIDDEN');checks.extensions++;}
assert.deepEqual(await a.extensions.requestExtension(parent.id,body,key),request);checks.extensions++;
await assert.rejects(()=>a.extensions.requestExtension(parent.id,{...body,reason:'changed'},key),e=>e.code==='IDEMPOTENCY_CONFLICT');checks.extensions++;
await assert.rejects(()=>b.extensions.requestExtension(parent.id,{requested_due_date:'2027-02-01',reason:null},randomUUID()),e=>e.code==='CONFLICT');checks.extensions++;
const acceptKey=randomUUID(),accepted=await b.extensions.acceptExtension(request.id,parent.id,acceptKey);check(accepted.status==='ACCEPTED');check(accepted.decided_by.id===b.id);
assert.deepEqual(await b.extensions.acceptExtension(request.id,parent.id,acceptKey),accepted);checks.extensions++;
const terms=await a.api.getCommitmentTerms(parent.id);check(terms.versions.find(v=>v.id===terms.current_terms_version_id).due_date==='2027-01-01');check((await a.ledger.getCommitmentLedger(parent.id)).items.some(e=>e.event_type==='EXTENSION_ACCEPTED'));
const rejectedRequest=await b.extensions.requestExtension(parent.id,{requested_due_date:'2027-03-01',reason:null},randomUUID());const rejected=await a.extensions.rejectExtension(rejectedRequest.id,parent.id,randomUUID());check(rejected.status==='REJECTED');check((await a.ledger.getCommitmentLedger(parent.id)).items.some(e=>e.event_type==='EXTENSION_REJECTED'));
for(const settings of [{due_date:null},{due_date:null,installment_dates:['2026-12-01','2027-01-01']}]){const p=await create(settings);await assert.rejects(()=>a.extensions.requestExtension(p.id,body,randomUUID()),e=>e.code==='INVALID_STATE');checks.extensions++;}
await a.connections.removeConnection(link.id);check((await b.extensions.listExtensions(parent.id)).length===2);
link=await a.connections.createConnection(b.phone);await b.connections.acceptConnection(link.id);await a.connections.blockConnection(link.id);check((await a.extensions.listExtensions(parent.id)).length===2);
category='notifications';let page=await b.notifications.listNotifications({limit:1});check(page.items.length===1&&!!page.next_cursor);check(page.items[0].read_at===null);check(page.items[0].actor.id===a.id);
const all=[];let cursor;do{const p=await b.notifications.listNotifications({limit:2,...(cursor?{cursor}:{})});all.push(...p.items);cursor=p.next_cursor;}while(cursor);
check(all.every((r,i)=>!i||r.created_at<=all[i-1].created_at));check(all.some(r=>r.type==='EXTENSION_REQUESTED'&&r.extension_request_id===request.id));check(all.some(r=>r.type==='EXTENSION_REJECTED'&&r.extension_request_id===rejected.id));
const read=await b.notifications.markRead(page.items[0].id);check(read.read_at!==null);assert.deepEqual(await b.notifications.markRead(read.id),read);checks.notifications++;
await assert.rejects(()=>a.notifications.markRead(read.id),e=>e.code==='NOT_FOUND');checks.notifications++;
await assert.rejects(()=>c.notifications.markRead(randomUUID()),e=>e.code==='NOT_FOUND');checks.notifications++;
const report=await a.repayments.reportRepayment(parent.id,{amount_minor:1000,currency:'INR',payment_date:'2026-10-01',note:null},randomUUID());page=await b.notifications.listNotifications();check(page.items.some(r=>r.type==='REPAYMENT_REPORTED'&&r.repayment_id===report.id&&r.commitment_id===parent.id));check(!/phone|amount_minor|reason|note|payload|source_ledger/.test(JSON.stringify(page)));
category='profile';const original=await a.auth.getMe();check(original.phone_e164===a.phone);
const updated=await a.profile.updateProfile({display_name:'F6 updated name'});check(updated.display_name==='F6 updated name');a.session.reconcileUser(updated);check(a.session.snapshot().user.display_name===updated.display_name);
const zoned=await a.profile.updateProfile({timezone:'Europe/London'});check(zoned.timezone==='Europe/London');check(zoned.phone_e164===original.phone_e164);a.session.reconcileUser(zoned);
await assert.rejects(()=>a.profile.deactivate(),e=>e.code==='ACCOUNT_HAS_UNRESOLVED_COMMITMENTS');checks.profile++;
const deactivated=await c.profile.deactivate();check(deactivated.status==='DEACTIVATED');await c.session.clearDeactivated();check(c.session.snapshot().status==='anonymous');check(c.session.accessToken()===null);
console.log('Live F6 checks passed: '+JSON.stringify(checks)+'. Stale-base conflict cannot be induced through the approved API because only one pending request can alter single-date terms.');
}finally{for(const u of users)await u.session.logout();}})().catch(e=>{console.error('Live F6 blocked:',e.code||e.name,e.message);process.exitCode=1;});
