// Local current-main backend only. Disposable development users, approved F4 endpoints.
const fs=require("node:fs"),ts=require("typescript"),{randomUUID}=require("node:crypto"),assert=require("node:assert/strict");
require.extensions[".ts"]=(m,f)=>m._compile(ts.transpileModule(fs.readFileSync(f,"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,f);
const {createAuthApi}=require("../shared/api/auth.ts"),{AuthSession}=require("../shared/auth/session.ts");
const {createConnectionsApi}=require("../shared/api/connections.ts"),{createCommitmentsApi}=require("../shared/api/commitments.ts");
const {createRepaymentsApi}=require("../shared/api/repayments.ts");
const {canReport,canDecide}=require("../shared/repayments/model.ts");
const {proposalActions}=require("../shared/commitments/model.ts"),{MutationIntents}=require("../shared/commitments/intents.ts");
const baseUrl=process.env.FIDES_LIVE_API_URL||"http://127.0.0.1:8000/api/v1";
if(!["127.0.0.1","localhost","[::1]"].includes(new URL(baseUrl).hostname))throw new Error("Disposable users require a local development backend");
const users=[];let checks=0;const check=()=>{checks++;};
async function expectError(run,code,status){await assert.rejects(run,e=>e.code===code&&e.status===status);}

(async()=>{try{
for(let attempt=0;users.length<3&&attempt<16;attempt++){
 const phone='+1202'+String(5500000+Math.floor(Math.random()*4000000));let session;const auth=createAuthApi({baseUrl,accessToken:()=>session?.accessToken()});let challenge;
 try{challenge=await auth.requestOtp('signup',phone);}catch(e){if(e.status===503)continue;throw e;}
 const response=await auth.verifyOtp({challenge_id:challenge.challenge_id,code:'123456',display_name:'F4 disposable '+users.length,timezone:'Etc/UTC'});let stored=null;
 session=new AuthSession({read:async()=>stored,write:async v=>{stored=v;},clear:async()=>{stored=null;}},auth);await session.establish(response);
 users.push({phone,session,id:session.snapshot().user.id,connections:createConnectionsApi({baseUrl,accessToken:session.accessToken}),api:createCommitmentsApi({baseUrl,accessToken:session.accessToken}),repayments:createRepaymentsApi({baseUrl,accessToken:session.accessToken})});}
assert.equal(users.length,3);const[a,b,c]=users;let link=await a.connections.createConnection(b.phone);link=await b.connections.acceptConnection(link.id);check();
const terms={due_date:null,interest_type:'NONE',interest_rate_bps:null,grace_period_days:0,installment_dates:null};
const create=async(interest=false)=>{let p=await a.api.createCommitment({connection_id:link.id,actor_role:'BORROWER',type:'IOU',principal_amount_minor:10000,currency:'INR',description:'F4 local validation',terms:interest?{...terms,interest_type:'SIMPLE_FIXED',interest_rate_bps:500}:terms},randomUUID());return b.api.confirmCommitment(p.id,randomUUID());};
const payload=amount=>({amount_minor:amount,currency:'INR',payment_date:'2026-01-01',note:null});
let p=await create();assert.equal(p.status,'ACTIVE');check();
for(const amount of [2500,2500,5000]){
 const key=randomUUID(),original=await a.repayments.reportRepayment(p.id,payload(amount),key);assert.equal(original.status,'PENDING_VERIFICATION');check();
 assert.deepEqual(await a.repayments.reportRepayment(p.id,payload(amount),key),original);check();await expectError(()=>a.repayments.reportRepayment(p.id,{...payload(amount),note:'changed'},key),'IDEMPOTENCY_CONFLICT',409);check();
 for(const user of[a,b]){assert.equal((await user.repayments.getRepayment(original.id)).id,original.id);check();}
 const current=await b.api.getCommitment(p.id);assert.equal(current.status,amount===2500&& (await b.repayments.listRepayments(p.id)).length===1?'ACTIVE':'PARTIALLY_REPAID');check();
 assert.equal(canDecide(original,current,a.id),false);assert.equal(canDecide(original,current,b.id),true);check();
 await expectError(()=>a.repayments.verifyRepayment(original.id,{decision_note:null},randomUUID()),'FORBIDDEN',403);check();
 const decisionKey=randomUUID(),verified=await b.repayments.verifyRepayment(original.id,{decision_note:'  agreed  '},decisionKey);assert.equal(verified.status,'VERIFIED');check();
 assert.deepEqual(await b.repayments.verifyRepayment(original.id,{decision_note:'agreed'},decisionKey),verified);check();await expectError(()=>b.repayments.verifyRepayment(original.id,{decision_note:'changed'},decisionKey),'IDEMPOTENCY_CONFLICT',409);check();
 const history=await a.repayments.getVerificationHistory(original.id);assert.equal(history.length,1);assert.equal(history[0].decision,'VERIFIED');assert.equal(history[0].decided_by.id,b.id);check();
 p=await a.api.getCommitment(p.id);assert.equal(p.status,amount===5000?'FULLY_REPAID':'PARTIALLY_REPAID');check();
 await expectError(()=>b.repayments.disputeRepayment(original.id,{decision_note:null},randomUUID()),'ALREADY_VERIFIED',409);check();await expectError(()=>b.repayments.verifyRepayment(original.id,{decision_note:null},randomUUID()),'ALREADY_VERIFIED',409);check();
}
assert.equal(p.status,'FULLY_REPAID');assert.equal(canReport(p,a.id),false);assert.equal((await a.repayments.listRepayments(p.id)).length,3);check();
const separate=await create(true);let r=await b.repayments.reportRepayment(separate.id,payload(1000),randomUUID());assert.equal(canDecide(r,separate,a.id),true);assert.equal(canDecide(r,separate,b.id),false);check();
await expectError(()=>b.repayments.disputeRepayment(r.id,{decision_note:null},randomUUID()),'FORBIDDEN',403);check();
const dk=randomUUID();r=await a.repayments.disputeRepayment(r.id,{decision_note:null},dk);assert.equal(r.status,'DISPUTED');check();assert.deepEqual(await a.repayments.disputeRepayment(r.id,{decision_note:null},dk),r);check();
assert.equal((await b.repayments.getVerificationHistory(r.id))[0].decision,'DISPUTED');assert.equal((await b.api.getCommitment(separate.id)).status,'ACTIVE');check();
await expectError(()=>a.repayments.verifyRepayment(r.id,{decision_note:null},randomUUID()),'INVALID_STATE',409);check();
await expectError(()=>a.repayments.reportRepayment(separate.id,payload(10501),randomUUID()),'OVER_REPAYMENT',409);check();
let interestRow=await a.repayments.reportRepayment(separate.id,payload(10500),randomUUID());interestRow=await b.repayments.verifyRepayment(interestRow.id,{decision_note:null},randomUUID());assert.equal((await a.api.getCommitment(separate.id)).status,'FULLY_REPAID');check();
let independent=await create();const unrelatedLink=await c.connections.createConnection(a.phone);await a.connections.acceptConnection(unrelatedLink.id);check();await a.connections.blockConnection(link.id);check();
const stable=randomUUID();r=await a.repayments.reportRepayment(independent.id,payload(1000),stable);check();
for(const user of[a,b]){await user.repayments.getRepayment(r.id);await user.repayments.listRepayments(independent.id);check();}
await b.repayments.verifyRepayment(r.id,{decision_note:null},randomUUID());check();
for(const op of[()=>c.repayments.getRepayment(r.id),()=>c.repayments.listRepayments(independent.id),()=>c.repayments.getVerificationHistory(r.id),()=>c.repayments.verifyRepayment(r.id,{decision_note:null},randomUUID()),()=>c.repayments.disputeRepayment(r.id,{decision_note:null},randomUUID())]){await expectError(op,'NOT_FOUND',404);check();}
const reportKey=randomUUID();let dropped=false;const lossy=createRepaymentsApi({baseUrl,accessToken:a.session.accessToken,fetcher:async(url,init)=>{const result=await fetch(url,init);if(!dropped&&init.method==='POST'){dropped=true;await result.json();throw new Error('lost acknowledgement');}return result;}});
await assert.rejects(()=>lossy.reportRepayment(independent.id,payload(1000),reportKey));const before=await a.repayments.listRepayments(independent.id);const replay=await a.repayments.reportRepayment(independent.id,payload(1000),reportKey);const after=await a.repayments.listRepayments(independent.id);assert.equal(before.length,after.length);assert.ok(before.some(x=>x.id===replay.id));check();
console.log('Live F4: '+checks+' checks passed on current-main local backend; three disposable users.');
}finally{for(const user of users)await user.session.logout();}})().catch(error=>{console.error('Live F4 blocked:',error.code||error.name);process.exitCode=1;});
