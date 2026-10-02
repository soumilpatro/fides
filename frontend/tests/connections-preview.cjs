// Local ephemeral auth/Connections visual fixture; never imported by application code.
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
http.createServer(async(req,res)=>{
 const origin=req.headers.origin;
 if(["http://localhost:8082","http://127.0.0.1:8082","http://localhost:3002","http://127.0.0.1:3002"].includes(origin)){
  res.setHeader("Access-Control-Allow-Origin",origin);res.setHeader("Vary","Origin");
  res.setHeader("Access-Control-Allow-Headers","Authorization,Content-Type");
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
 if(path==="/__fixture/reset"&&req.method==="POST"){reset(body.mode||"mixed");return send(200,{mode});}
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
 const entry=sessions.get(req.headers.authorization?.replace(/^Bearer /,""));
 if(!entry)return error(401,"INVALID_AUTH_TOKEN","Invalid authentication credentials.");
 if(path==="/api/v1/me"&&req.method==="GET")return send(200,entry.user);
 if(path==="/api/v1/auth/logout"&&req.method==="POST"){sessions.delete(entry.access_token);return send(200,{logged_out:true});}
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
}).listen(8766,"127.0.0.1",()=>console.log("Connections-only visual fixture: localhost:8766; login +12025550101 / 654321. No production/backend validation."));
