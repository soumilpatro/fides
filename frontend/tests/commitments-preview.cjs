// Local ephemeral auth/Connections/Commitments visual fixture; never imported by application code.
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

http.createServer(async(req,res)=>{
 const origin=req.headers.origin;
 if(["http://localhost:8083","http://127.0.0.1:8083","http://localhost:3003","http://127.0.0.1:3003"].includes(origin)){
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
 if(path==="/__fixture/reset"&&req.method==="POST"){reset(body.mode||"mixed");resetCommitments();return send(200,{mode});}
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
 const entry=sessions.get(req.headers.authorization?.replace(/^Bearer /,""));
 if(!entry)return error(401,"INVALID_AUTH_TOKEN","Invalid authentication credentials.");
 if(path==="/api/v1/me"&&req.method==="GET")return send(200,entry.user);
 if(path==="/api/v1/auth/logout"&&req.method==="POST"){sessions.delete(entry.access_token);return send(200,{logged_out:true});}


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
}).listen(8767,"127.0.0.1",()=>console.log("F3-only visual fixture: localhost:8767; login +12025550101 / 654321. No production/backend validation."));
