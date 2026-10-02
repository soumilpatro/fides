// Local ephemeral auth/Connections/Commitments/Repayments visual fixture; never imported by application code.
const http=require("node:http"),{randomUUID}=require("node:crypto");
if(process.env.NODE_ENV==="production")throw new Error("Development fixture only");
const users=Array.from({length:7},(_,i)=>({id:randomUUID(),display_name:["Riya","Morgan","Alex","Sam","Jules","Taylor","Casey"][i],phone_e164:"+1202555010"+(i+1),timezone:"Etc/UTC",status:"ACTIVE",created_at:new Date().toISOString(),updated_at:new Date().toISOString()}));
const sessions=new Map(),challenges=new Map();let rows=[],mode="mixed";
const person=user=>({id:user.id,display_name:user.display_name});
const stamp=()=>new Date().toISOString();
function reset(next="mixed"){
 mode=next;rows=next==="empty"?[]:["PENDING","PENDING","ACCEPTED","BLOCKED","REMOVED"].map((status,i)=>({
  id:randomUUID(),status,requester:person(i===0?users[i+1]:users[0]),recipient:person(i===0?users[0]:users[i+1]),
  created_at:new Date(Date.now()-86400000).toISOString(),updated_at:new Date(Date.now()-i*1000).toISOString()}));
}
reset();
function credentials(user){const value={access_token:randomUUID(),refresh_token:randomUUID(),token_type:"Bearer",access_expires_at:new Date(Date.now()+900000).toISOString(),refresh_expires_at:new Date(Date.now()+2592000000).toISOString(),user};sessions.set(value.access_token,value);return value;}

let commitmentRows=[],termsById=new Map(),installmentsById=new Map(),mutationResults=new Map();
function createRecord(actor,other,body,status="PENDING_CONFIRMATION"){
 const record={id:randomUUID(),connection_id:body.connection_id,type:body.type,status,principal_amount_minor:body.principal_amount_minor,currency:body.currency,description:body.description||null,
  borrower:person(body.actor_role==="BORROWER"?actor:other),lender:person(body.actor_role==="LENDER"?actor:other),creator:person(actor),
  created_at:stamp(),updated_at:stamp(),confirmed_at:status==="ACTIVE"?stamp():null,activated_at:status==="ACTIVE"?stamp():null};
 const t=body.terms,version={id:randomUUID(),version_no:1,effective_at:stamp(),created_at:stamp(),...t,
  schedule_mode:t.installment_dates?"installments":t.due_date?"single":"none",due_timezone:"Etc/UTC",created_by:person(actor)};
 termsById.set(record.id,{commitment_id:record.id,currency:record.currency,current_terms_version_id:version.id,versions:[version]});
 // Fixture server calculation only. Production clients never compute interest or allocation.
 const dates=t.installment_dates||[],interest=t.interest_rate_bps?Number((BigInt(record.principal_amount_minor)*BigInt(t.interest_rate_bps)+5000n)/10000n):0;
 installmentsById.set(record.id,dates.map((due_date,i)=>{
  const principal=Math.floor(record.principal_amount_minor/dates.length),partInterest=Math.floor(interest/dates.length);
  const p=i===dates.length-1?record.principal_amount_minor-principal*i:principal,j=i===dates.length-1?interest-partInterest*i:partInterest;
  return{id:randomUUID(),terms_version_id:version.id,sequence_no:i+1,due_date,principal_amount_minor:p,interest_amount_minor:j,total_due_minor:p+j,currency:record.currency,status:"PENDING",created_at:stamp(),updated_at:stamp()};}));
 return record;
}
function resetCommitments(){
 commitmentRows=[];termsById.clear();installmentsById.clear();mutationResults.clear();
 if(mode==="empty")return;
 const link=rows.find(r=>r.status==="ACCEPTED");
 const basic={connection_id:link.id,actor_role:"BORROWER",type:"IOU",principal_amount_minor:12345,currency:"INR",description:"Shared record fixture",terms:{due_date:null,interest_type:"NONE",interest_rate_bps:null,grace_period_days:0,installment_dates:null}};
 commitmentRows.push(createRecord(users[0],users[3],basic));
 commitmentRows.push(createRecord(users[3],users[0],{...basic,currency:"USD",type:"PEER_LOAN",terms:{...basic.terms,interest_type:"SIMPLE_FIXED",interest_rate_bps:525,grace_period_days:7,installment_dates:["2027-02-01","2027-03-01","2027-04-01"]}}));
 commitmentRows.push(createRecord(users[0],users[3],{...basic,currency:"GBP",terms:{...basic.terms,due_date:"2027-01-15"}},"ACTIVE"));
 commitmentRows.push(createRecord(users[0],users[3],{...basic,currency:"USD"},"REJECTED"));
 commitmentRows.push(createRecord(users[0],users[3],{...basic,currency:"GBP"},"CANCELLED"));
}
resetCommitments();

let repaymentRows=[],historyById=new Map();
function reportRecord(parent,actor,amount,status='PENDING_VERIFICATION') {const value={id:randomUUID(),commitment_id:parent.id,reported_by:person(actor),amount_minor:amount,currency:parent.currency,payment_date:'2026-01-01',reported_at:stamp(),status,note:null,created_at:stamp()};repaymentRows.unshift(value);historyById.set(value.id,[]);return value;}
function resetRepayments(){repaymentRows=[];historyById.clear();if(mode==='empty')return;const basic={connection_id:rows.find(r=>r.status==='ACCEPTED').id,actor_role:'BORROWER',type:'IOU',principal_amount_minor:10000,currency:'INR',description:'Repayment review fixture',terms:{due_date:null,interest_type:'NONE',interest_rate_bps:null,grace_period_days:0,installment_dates:null}};
const mixed=createRecord(users[0],users[3],basic,'ACTIVE'),empty=createRecord(users[0],users[3],{...basic,description:'No repayments yet'},'ACTIVE');commitmentRows.unshift(mixed,empty);
for(const [status,actor,amount] of [['PENDING_VERIFICATION',users[3],1000],['PENDING_VERIFICATION',users[0],1500],['VERIFIED',users[0],2000],['DISPUTED',users[3],500],['CANCELLED',users[0],300]]){const r=reportRecord(mixed,actor,amount,status);if(['VERIFIED','DISPUTED'].includes(status))historyById.set(r.id,[{id:randomUUID(),repayment_id:r.id,decided_by:person(actor.id===users[0].id?users[3]:users[0]),decision:status,decision_note:'Reviewed together',decided_at:stamp()}]);}mixed.status='PARTIALLY_REPAID';}
resetRepayments();

let ledgerById=new Map(),reads=[];
function resetLedger(){
 ledgerById.clear();
 for(const parent of commitmentRows){
  const version=termsById.get(parent.id).versions[0],items=[];
  const add=(type,actor,details)=>items.push({id:randomUUID(),commitment_id:parent.id,actor:person(actor),event_type:type,occurred_at:new Date(Date.UTC(2026,8,1,0,0,items.length)).toISOString(),details});
  add('COMMITMENT_PROPOSED',users.find(u=>u.id===parent.creator.id),{status:'PENDING_CONFIRMATION',terms_version_id:version.id});
  if(['ACTIVE','PARTIALLY_REPAID'].includes(parent.status))add('COMMITMENT_CONFIRMED',users.find(u=>u.id!==parent.creator.id&&[parent.borrower.id,parent.lender.id].includes(u.id)),{status:'ACTIVE'});
  for(const r of repaymentRows.filter(r=>r.commitment_id===parent.id&&r.status!=='CANCELLED')){
   add('REPAYMENT_REPORTED',users.find(u=>u.id===r.reported_by.id),{status:'PENDING_VERIFICATION',repayment_id:r.id,terms_version_id:version.id,amount_minor:r.amount_minor,currency:r.currency});
   const h=historyById.get(r.id)?.[0];if(h)add('REPAYMENT_'+h.decision,users.find(u=>u.id===h.decided_by.id),{status:h.decision,repayment_id:r.id,verification_id:h.id,amount_minor:r.amount_minor,currency:r.currency,...(h.decision==='VERIFIED'?{terms_version_id:version.id,resulting_verified_outstanding_minor:8000,resulting_commitment_status:'PARTIALLY_REPAID'}:{})});
  }
  if(parent.description==='Repayment review fixture')for(let i=0;i<48;i++){const r=reportRecord(parent,users[0],10);add('REPAYMENT_REPORTED',users[0],{status:'PENDING_VERIFICATION',repayment_id:r.id,terms_version_id:version.id,amount_minor:10,currency:parent.currency});}
  ledgerById.set(parent.id,items);
 }
}
resetLedger();
http.createServer(async(req,res)=>{
 const origin=req.headers.origin;
 if(["http://localhost:8085","http://127.0.0.1:8085","http://localhost:3005","http://127.0.0.1:3005"].includes(origin)){
  res.setHeader("Access-Control-Allow-Origin",origin);res.setHeader("Vary","Origin");
  res.setHeader("Access-Control-Allow-Headers","Authorization,Content-Type,Idempotency-Key");
  res.setHeader("Access-Control-Allow-Methods","GET,POST,DELETE,OPTIONS");
  res.setHeader("Access-Control-Expose-Headers","X-Request-ID");
 }
 res.setHeader("Cache-Control","no-store");res.setHeader("Content-Type","application/json");res.setHeader("X-Request-ID",randomUUID());
 const send=(status,data)=>{res.writeHead(status);res.end(JSON.stringify(data));};
 const error=(status,code,message)=>send(status,{error:{code,message}});
 if(req.method==="OPTIONS")return send(204,{});
 let body={};try{let raw="";for await(const chunk of req){raw+=chunk;if(raw.length>4096)throw new Error();}if(raw)body=JSON.parse(raw);}
 catch{return error(400,"MALFORMED_REQUEST","Malformed request.");}
 const path=new URL(req.url,"http://localhost").pathname;
 if(path==="/__fixture/reset"&&req.method==="POST"){reset(body.mode||"mixed");resetCommitments();resetRepayments();resetLedger();reads=[];return send(200,{mode});}
 if(path==="/api/v1/auth/otp/request"&&req.method==="POST"){
  const id=randomUUID();challenges.set(id,body);return send(202,{challenge_id:id,expires_at:new Date(Date.now()+600000).toISOString(),resend_after_seconds:60,message:"Verification requested."});
 }
 if(path==="/api/v1/auth/otp/verify"&&req.method==="POST"){
  const challenge=challenges.get(body.challenge_id);
  if(!challenge||body.code!==(challenge.intent==="signup"?"123456":"654321"))return error(422,"OTP_INVALID","Verification code is invalid.");
  let user=users.find(u=>u.phone_e164===challenge.phone);
  if(challenge.intent==="signup"&&!user){user={...users[0],id:randomUUID(),phone_e164:challenge.phone,display_name:body.display_name};users.push(user);}
  if(!user)return error(409,"AUTH_FLOW_NOT_ALLOWED","This authentication flow is not allowed.");
  challenges.delete(body.challenge_id);return send(200,credentials(user));
 }
 if(path==="/api/v1/auth/refresh"&&req.method==="POST"){
  const entry=[...sessions.values()].find(s=>s.refresh_token===body.refresh_token);
  if(!entry)return error(401,"INVALID_REFRESH_TOKEN","Invalid refresh credentials.");
  sessions.delete(entry.access_token);return send(200,credentials(entry.user));
 }
 if(path==="/__fixture/mode"&&req.method==="POST"){mode=body.mode||"mixed";return send(200,{mode});}
 if(path==="/__fixture/reads"&&req.method==="GET")return send(200,{reads});
 const entry=sessions.get(req.headers.authorization?.replace(/^Bearer /,""));
 if(!entry)return error(401,"INVALID_AUTH_TOKEN","Invalid authentication credentials.");

 if(req.method==="GET")reads.push(path);
 if(path==="/api/v1/summary"&&req.method==="GET"){
  if(mode==="summary-error")return error(503,"SERVICE_UNAVAILABLE","Service is temporarily unavailable.");
  if(mode==="slow")await new Promise(r=>setTimeout(r,1500));
  // Explicit server fixtures only; production frontend never derives these.
  const values=mode==="empty"?[[0,0,0],[0,0,0],[0,0,0]]:[[18000,0,-18000],[0,20000,20000],[0,0,0]];
  return send(200,{currencies:["INR","USD","GBP"].map((currency,i)=>({currency,borrowed_outstanding_minor:values[i][0],lent_outstanding_minor:values[i][1],net_position_minor:values[i][2]}))});
 }
 const ledger=path.match(/^\/api\/v1\/commitments\/([^/]+)\/ledger$/);
 if(ledger&&req.method==="GET"){
  const parent=commitmentRows.find(row=>row.id===ledger[1]&&[row.borrower.id,row.lender.id].includes(entry.user.id));
  if(!parent)return error(404,"NOT_FOUND","Unavailable resource.");
  const q=new URL(req.url,"http://localhost").searchParams,cursor=q.get("cursor");
  if(mode==="history-error"||mode==="page-error"&&cursor)return error(503,"SERVICE_UNAVAILABLE","Service is temporarily unavailable.");
  if(mode==="slow")await new Promise(r=>setTimeout(r,1500));
  const items=mode==="history-empty"?[]:ledgerById.get(parent.id)||[],start=cursor?Number(cursor.replace("fixture:","")):0,limit=Number(q.get("limit")||50);
  return send(200,{items:items.slice(start,start+limit),next_cursor:start+limit<items.length?"fixture:"+(start+limit):null});
 }
 if(path==="/api/v1/me"&&req.method==="GET")return send(200,entry.user);
 if(path==="/api/v1/auth/logout"&&req.method==="POST"){sessions.delete(entry.access_token);return send(200,{logged_out:true});}



 const collection=path.match(/^\/api\/v1\/commitments\/([^/]+)\/repayments$/),detail=path.match(/^\/api\/v1\/repayments\/([^/]+)(?:\/(verify|dispute|verification-history))?$/);
 if(collection||detail){
  if(mode==='network'){req.destroy();return;}if(mode==='error')return error(503,'SERVICE_UNAVAILABLE','Service is temporarily unavailable.');if(mode==='slow')await new Promise(r=>setTimeout(r,2000));
  const actor=entry.user,r=detail&&repaymentRows.find(r=>r.id===detail[1]),parent=commitmentRows.find(p=>p.id===(collection?collection[1]:r?.commitment_id)&&[p.borrower.id,p.lender.id].includes(actor.id));
  if(!parent)return error(404,'NOT_FOUND','Unavailable resource.');
  const key=req.headers['idempotency-key'],scope=actor.id+':'+path+':'+key,digest=JSON.stringify(body,Object.keys(body).sort());
  if(req.method==='POST'){
   if(!key||!/^[A-Za-z0-9._:-]{1,128}$/.test(key))return error(400,'MALFORMED_REQUEST','Invalid request.');
   if(mode==='conflict')return error(409,'IDEMPOTENCY_CONFLICT','Conflicting request.');const cache=mutationResults.get(scope);if(cache){if(cache.digest!==digest)return error(409,'IDEMPOTENCY_CONFLICT','Conflicting request.');return send(cache.status,cache.body);}
   if(mode==='invalid')return error(409,'INVALID_STATE','Invalid state.');if(mode==='over')return error(409,'OVER_REPAYMENT','Invalid amount.');
  }
  if(collection&&req.method==='GET')return send(200,repaymentRows.filter(r=>r.commitment_id===parent.id).sort((a,b)=>b.reported_at.localeCompare(a.reported_at)||a.id.localeCompare(b.id)));
  if(collection&&req.method==='POST'){
   if(!['ACTIVE','PARTIALLY_REPAID'].includes(parent.status))return error(409,'INVALID_STATE','Invalid state.');
   if(!Number.isSafeInteger(body.amount_minor)||body.amount_minor<=0)return error(422,'INVALID_AMOUNT','Invalid amount.');if(body.currency!==parent.currency)return error(422,'CURRENCY_MISMATCH','Currency mismatch.');
   const reserved=repaymentRows.filter(r=>r.commitment_id===parent.id&&['VERIFIED','PENDING_VERIFICATION'].includes(r.status)).reduce((sum,r)=>sum+r.amount_minor,0);
   if(body.amount_minor>parent.principal_amount_minor-reserved)return error(409,'OVER_REPAYMENT','Invalid amount.');
   const created=reportRecord(parent,actor,body.amount_minor);created.payment_date=body.payment_date;created.note=body.note?.trim()||null;
   mutationResults.set(scope,{digest,status:201,body:structuredClone(created)});if(mode==='ambiguous'){mode='mixed';req.destroy();return;}return send(201,created);
  }
  if(detail&&req.method==='GET'){if(detail[2]==='verification-history')return send(200,historyById.get(r.id)||[]);if(!detail[2])return send(200,r);}
  if(detail&&req.method==='POST'&&['verify','dispute'].includes(detail[2])){
   if(r.reported_by.id===actor.id)return error(403,'FORBIDDEN','Forbidden.');if(r.status==='VERIFIED')return error(409,'ALREADY_VERIFIED','Already verified.');if(r.status!=='PENDING_VERIFICATION'||!['ACTIVE','PARTIALLY_REPAID'].includes(parent.status))return error(409,'INVALID_STATE','Invalid state.');
   r.status=detail[2]==='verify'?'VERIFIED':'DISPUTED';historyById.set(r.id,[{id:randomUUID(),repayment_id:r.id,decided_by:person(actor),decision:r.status,decision_note:body.decision_note?.trim()||null,decided_at:stamp()}]);
   if(r.status==='VERIFIED'){const verified=repaymentRows.filter(r=>r.commitment_id===parent.id&&r.status==='VERIFIED').reduce((sum,r)=>sum+r.amount_minor,0);parent.status=verified===parent.principal_amount_minor?'FULLY_REPAID':'PARTIALLY_REPAID';}
   mutationResults.set(scope,{digest,status:200,body:structuredClone(r)});if(mode==='ambiguous'){mode='mixed';req.destroy();return;}return send(200,r);
  }
  return error(404,'NOT_FOUND','Unavailable resource.');
 }
 if(path.startsWith("/api/v1/commitments")){
  if(mode==="network"){req.destroy();return;}
  if(mode==="error")return error(503,"SERVICE_UNAVAILABLE","Service is temporarily unavailable.");
  if(mode==="slow")await new Promise(resolve=>setTimeout(resolve,2000));
  const parts=path.split("/").slice(3);const actor=entry.user;
  const visible=row=>[row.borrower.id,row.lender.id].includes(actor.id);
  if(parts.length===1&&req.method==="GET")return send(200,commitmentRows.filter(visible).sort((a,b)=>b.updated_at.localeCompare(a.updated_at)||a.id.localeCompare(b.id)));
  const key=req.headers["idempotency-key"],scope=actor.id+":"+path+":"+key,digest=JSON.stringify(body, (_key,value) => value && typeof value === "object" && !Array.isArray(value) ? Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b))) : value);
  if(req.method==="POST"){
   if(!key||!/^[A-Za-z0-9._:-]{1,128}$/.test(key))return error(400,"MALFORMED_REQUEST","Invalid request.");
   if(mode==="conflict")return error(409,"IDEMPOTENCY_CONFLICT","Conflicting request.");
   const cached=mutationResults.get(scope);
   if(cached){if(cached.digest!==digest)return error(409,"IDEMPOTENCY_CONFLICT","Conflicting request.");return send(cached.status,cached.body);}
   if(mode==="invalid")return error(409,"INVALID_STATE","Invalid state.");
  }
  if(parts.length===1&&req.method==="POST"){
   const link=rows.find(r=>r.id===body.connection_id&&[r.requester.id,r.recipient.id].includes(actor.id));
   if(!link)return error(404,"NOT_FOUND","Unavailable resource.");
   if(link.status!=="ACCEPTED")return error(409,"INVALID_STATE","Invalid state.");
   if(!Number.isSafeInteger(body.principal_amount_minor)||body.principal_amount_minor<=0)return error(422,"INVALID_AMOUNT","Invalid amount.");
   const other=users.find(u=>u.id===(link.requester.id===actor.id?link.recipient.id:link.requester.id));
   const record=createRecord(actor,other,body);
   commitmentRows.unshift(record);mutationResults.set(scope,{digest,status:201,body:structuredClone(record)});
   if(mode==="ambiguous"){mode="mixed";req.destroy();return;}return send(201,record);
  }
  const record=commitmentRows.find(r=>r.id===parts[1]&&visible(r));
  if(!record)return error(404,"NOT_FOUND","Unavailable resource.");
  if(parts.length===2&&req.method==="GET")return send(200,record);
  if(parts.length===3&&parts[2]==="terms"&&req.method==="GET")return send(200,termsById.get(record.id));
  if(parts.length===3&&parts[2]==="installments"&&req.method==="GET")return send(200,installmentsById.get(record.id));
  if(parts.length===3&&req.method==="POST"&&["confirm","reject","cancel"].includes(parts[2])){
   const action=parts[2];
   if((record.creator.id===actor.id)!==(action==="cancel"))return error(403,"FORBIDDEN","Forbidden.");
   if(record.status!=="PENDING_CONFIRMATION")return error(409,"INVALID_STATE","Invalid state.");
   if(action==="confirm"&&rows.find(r=>r.id===record.connection_id)?.status!=="ACCEPTED")return error(409,"INVALID_STATE","Invalid state.");
   record.status={confirm:"ACTIVE",reject:"REJECTED",cancel:"CANCELLED"}[action];record.updated_at=stamp();
   if(action==="confirm")record.confirmed_at=record.activated_at=stamp();
   mutationResults.set(scope,{digest,status:200,body:structuredClone(record)});
   if(mode==="ambiguous"){mode="mixed";req.destroy();return;}return send(200,record);
  }
  return error(404,"NOT_FOUND","Unavailable resource.");
 }

 if(!path.startsWith("/api/v1/connections"))return error(404,"NOT_FOUND","Unavailable resource.");
 if(mode==="network"){req.destroy();return;}
 if(mode==="error")return error(503,"SERVICE_UNAVAILABLE","Service is temporarily unavailable.");
 if(mode==="slow")await new Promise(resolve=>setTimeout(resolve,2000));
 if(path==="/api/v1/connections"&&req.method==="GET")return send(200,rows.filter(r=>[r.requester.id,r.recipient.id].includes(entry.user.id)).sort((a,b)=>b.updated_at.localeCompare(a.updated_at)));
 if(path==="/api/v1/connections"&&req.method==="POST"){
  const target=users.find(u=>u.phone_e164===body.phone);
  if(!target)return error(404,"NOT_FOUND","Unavailable resource.");
  if(target.id===entry.user.id)return error(422,"VALIDATION_ERROR","Request validation failed.");
  let row=rows.find(r=>[r.requester.id,r.recipient.id].includes(entry.user.id)&&[r.requester.id,r.recipient.id].includes(target.id));
  if(row&&row.status!=="REMOVED")return error(409,"CONFLICT","Conflicting request.");
  if(row)Object.assign(row,{requester:person(entry.user),recipient:person(target),status:"PENDING",updated_at:stamp()});
  else{row={id:randomUUID(),requester:person(entry.user),recipient:person(target),status:"PENDING",created_at:stamp(),updated_at:stamp()};rows.unshift(row);}
  return send(201,row);
 }
 const match=path.match(/^\/api\/v1\/connections\/([^/]+)(?:\/(accept|reject|block))?$/);
 const row=match&&rows.find(r=>r.id===match[1]&&[r.requester.id,r.recipient.id].includes(entry.user.id));
 if(!row)return error(404,"NOT_FOUND","Unavailable resource.");
 if(req.method==="GET"&&!match[2])return send(200,row);
 const action=req.method==="DELETE"&&!match[2]?"remove":req.method==="POST"?match[2]:null;
 if(!action)return error(404,"NOT_FOUND","Unavailable resource.");
 if(["accept","reject"].includes(action)&&row.recipient.id!==entry.user.id)return error(403,"FORBIDDEN","Forbidden.");
 if(!["PENDING","ACCEPTED"].includes(row.status)||(["accept","reject"].includes(action)&&row.status!=="PENDING"))return error(409,"INVALID_STATE","Invalid state.");
 if(action==="remove"&&row.status==="PENDING"&&row.requester.id!==entry.user.id)return error(403,"FORBIDDEN","Forbidden.");
 row.status=action==="accept"?"ACCEPTED":action==="block"?"BLOCKED":"REMOVED";row.updated_at=stamp();return send(200,row);
}).listen(8769,"127.0.0.1",()=>console.log("F5-only visual fixture: localhost:8769; login +12025550101 / 654321. No production/backend validation."));
