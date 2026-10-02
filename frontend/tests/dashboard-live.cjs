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
const users=[];let checks=0;const check=(value,message)=>{assert.ok(value,message);checks++;};
(async()=>{try{
for(let attempt=0;users.length<3&&attempt<16;attempt++){
 const phone='+1202'+String(5500000+Math.floor(Math.random()*4000000));let session;const auth=createAuthApi({baseUrl,fetcher:localFetcher,accessToken:()=>session?.accessToken()});let challenge;
 try{challenge=await auth.requestOtp('signup',phone);}catch(e){if(e.status===503)continue;throw e;}
 const response=await auth.verifyOtp({challenge_id:challenge.challenge_id,code:'123456',display_name:'F5 disposable '+users.length,timezone:'Etc/UTC'});let stored=null;
 session=new AuthSession({read:async()=>stored,write:async v=>{stored=v;},clear:async()=>{stored=null;}},auth);await session.establish(response);
 const config={baseUrl,accessToken:session.accessToken};users.push({phone,id:session.snapshot().user.id,session,connections:createConnectionsApi(config),api:createCommitmentsApi(config),repayments:createRepaymentsApi(config),dashboard:createDashboardApi(config),ledger:createLedgerApi(config)});
}
assert.equal(users.length,3);const [a,b,c]=users;
const empty=await a.dashboard.getSummary();check(empty.currencies.every(r=>r.borrowed_outstanding_minor===0&&r.lent_outstanding_minor===0&&r.net_position_minor===0),'zero all 3');check(empty.currencies.map(r=>r.currency).join(',')==='INR,USD,GBP');
let link=await a.connections.createConnection(b.phone);link=await b.connections.acceptConnection(link.id);
const terms={due_date:'2020-01-01',interest_type:'NONE',interest_rate_bps:null,grace_period_days:7,installment_dates:null};
async function create(currency,role){const p=await a.api.createCommitment({connection_id:link.id,actor_role:role,type:'IOU',principal_amount_minor:10000,currency,description:'F5 local validation',terms},randomUUID());return b.api.confirmCommitment(p.id,randomUUID());}
const inr=await create('INR','BORROWER'),usd=await create('USD','LENDER'),gbp=await create('GBP','BORROWER');
let snapshot=await a.dashboard.getSummary();check(snapshot.currencies[0].borrowed_outstanding_minor===10000);check(snapshot.currencies[1].lent_outstanding_minor===10000);check(snapshot.currencies[2].borrowed_outstanding_minor===10000);check((await a.api.getCommitment(inr.id)).status==='ACTIVE','past due date does not infer default');
const payload=amount=>({amount_minor:amount,currency:'INR',payment_date:'2026-01-01',note:'private report note'});
let reported=await a.repayments.reportRepayment(inr.id,payload(2500),randomUUID());check(reported.status==='PENDING_VERIFICATION');assert.deepEqual(await a.dashboard.getSummary(),snapshot);checks++;
await b.repayments.disputeRepayment(reported.id,{decision_note:'private decision'},randomUUID());assert.deepEqual(await a.dashboard.getSummary(),snapshot);checks++;
reported=await a.repayments.reportRepayment(inr.id,payload(2500),randomUUID());await b.repayments.verifyRepayment(reported.id,{decision_note:'private decision'},randomUUID());snapshot=await a.dashboard.getSummary();check(snapshot.currencies[0].borrowed_outstanding_minor===7500);check(snapshot.currencies[1].lent_outstanding_minor===10000&&snapshot.currencies[2].borrowed_outstanding_minor===10000,'currencies independent');
const tail=await a.repayments.reportRepayment(inr.id,payload(7500),randomUUID());await b.repayments.verifyRepayment(tail.id,{decision_note:null},randomUUID());check((await a.api.getCommitment(inr.id)).status==='FULLY_REPAID');check((await a.dashboard.getSummary()).currencies[0].borrowed_outstanding_minor===0);
const ledger=await a.ledger.getCommitmentLedger(inr.id);check(ledger.items[0].event_type==='COMMITMENT_PROPOSED');check(ledger.items[1].event_type==='COMMITMENT_CONFIRMED');
for(const type of ['REPAYMENT_REPORTED','REPAYMENT_VERIFIED','REPAYMENT_DISPUTED'])check(ledger.items.some(e=>e.event_type===type));
check(ledger.items.filter(e=>e.event_type==='REPAYMENT_REPORTED').every(e=>e.details.status==='PENDING_VERIFICATION'));
check(ledger.items.some(e=>e.event_type==='REPAYMENT_VERIFIED'&&e.details.resulting_verified_outstanding_minor===7500),'historical result retained after fully repaid');
check(ledger.items.filter(e=>e.event_type==='REPAYMENT_VERIFIED'||e.event_type==='REPAYMENT_DISPUTED').every(e=>e.actor.id===b.id));check(ledger.items.filter(e=>e.event_type==='REPAYMENT_REPORTED').every(e=>e.actor.id===a.id));
check(!/phone|private|event_payload|request_id|idempotency|audit|decision_note/.test(JSON.stringify(ledger)),'closed privacy boundary');
assert.deepEqual(await b.ledger.getCommitmentLedger(inr.id),ledger);checks++;
const cursorRows=[];let cursor;do{const result=await a.ledger.getCommitmentLedger(inr.id,{limit:2,...(cursor?{cursor}:{})});cursorRows.push(...result.items);cursor=result.next_cursor;}while(cursor);assert.deepEqual(cursorRows,ledger.items);checks++;
const third=await c.connections.createConnection(a.phone);await a.connections.acceptConnection(third.id);
await assert.rejects(()=>c.ledger.getCommitmentLedger(inr.id),e=>e.code==='NOT_FOUND'&&e.status===404);checks++;
await a.connections.removeConnection(link.id);assert.deepEqual(await a.ledger.getCommitmentLedger(inr.id),ledger);checks++;
link=await a.connections.createConnection(b.phone);await b.connections.acceptConnection(link.id);await a.connections.blockConnection(link.id);assert.deepEqual(await b.ledger.getCommitmentLedger(inr.id),ledger);checks++;
const index=await a.api.listCommitments();check(index.some(row=>row.id===inr.id)&&index.some(row=>row.id===usd.id)&&index.some(row=>row.id===gbp.id));
console.log('Live F5: '+checks+' checks passed; authoritative summary, selected history, privacy, pagination, and removed/blocked independence.');
}finally{for(const user of users)await user.session.logout();}})().catch(e=>{console.error('Live F5 blocked:',e.code||e.name,e.message);process.exitCode=1;});
