const fs=require("node:fs"),path=require("node:path"),ts=require("typescript"),Module=require("node:module");
require.extensions[".ts"]=(module,file)=>module._compile(ts.transpileModule(fs.readFileSync(file,"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,file);
const test=require("node:test"),assert=require("node:assert/strict");
const apiModule=require("../shared/api/commitments.ts"),model=require("../shared/commitments/model.ts");
const {parseMinor,parseBps}=require("../shared/commitments/money.ts");
const {initialForm,proposalBody,validDate}=require("../shared/commitments/form.ts");
const {MutationIntents,canonical,ambiguous}=require("../shared/commitments/intents.ts");
const {ApiError}=require("../shared/api/errors.ts"),{isAllowedApiRoute}=require("../shared/api/relay.ts");
const A="00000000-0000-4000-8000-000000000001",B="00000000-0000-4000-8000-000000000002",C="00000000-0000-4000-8000-000000000003",ID="00000000-0000-4000-8000-000000000004",CID="00000000-0000-4000-8000-000000000005",VID="00000000-0000-4000-8000-000000000006";
const person=(id)=>({id,display_name:id===A?"Alex":"Sam"}),time="2026-10-02T10:00:00Z";
const row=(status="PENDING_CONFIRMATION")=>({id:ID,connection_id:CID,type:"IOU",status,principal_amount_minor:12345,currency:"INR",description:null,borrower:person(A),lender:person(B),creator:person(A),created_at:time,updated_at:time,confirmed_at:null,activated_at:null});
const terms=(schedule_mode="none")=>({commitment_id:ID,currency:"INR",current_terms_version_id:VID,versions:[{id:VID,version_no:1,effective_at:time,created_at:time,due_date:null,interest_type:"NONE",interest_rate_bps:null,grace_period_days:0,schedule_mode,due_timezone:null,installment_dates:schedule_mode==="installments"?["2026-11-01","2026-12-01"]:null,created_by:person(A)}]});
const installment=()=>({id:C,terms_version_id:VID,sequence_no:1,due_date:"2026-11-01",principal_amount_minor:123,interest_amount_minor:4,total_due_minor:127,currency:"INR",status:"PENDING",created_at:time,updated_at:time});
const body=()=>proposalBody({...initialForm(CID),role:"BORROWER",amount:"123.45"},[CID]);
for(const [name,method,suffix,args,response] of [
 ["createCommitment","POST","",[body(),"stable-key"],row()],["listCommitments","GET","",[],[row()]],["getCommitment","GET","/"+ID,[ID],row()],
 ...["confirm","reject","cancel"].map(action=>[action+"Commitment","POST","/"+ID+"/"+action,[ID,"stable-key"],row(action==="confirm"?"ACTIVE":action==="reject"?"REJECTED":"CANCELLED")]),
 ["getCommitmentTerms","GET","/"+ID+"/terms",[ID],terms()],["getCommitmentInstallments","GET","/"+ID+"/installments",[ID],[installment()]]
])test("wire "+name,async()=>{
 let calls=0;const api=apiModule.createCommitmentsApi({baseUrl:"https://fides.example/api/v1",accessToken:()=>"memory",fetcher:async(url,init)=>{
   calls++;assert.equal(url,"https://fides.example/api/v1/commitments"+suffix);assert.equal(init.method,method);
   assert.equal(init.headers.get("Authorization"),"Bearer memory");assert.equal(init.headers.get("Idempotency-Key"),method==="POST"?"stable-key":null);
   assert.equal(init.body,name==="createCommitment"?JSON.stringify(body()):undefined);assert.equal(init.credentials,"omit");assert.equal(init.cache,"no-store");assert.equal(init.redirect,"error");return Response.json(response);}});
 assert.deepEqual(await api[name](...args),response);assert.equal(calls,1);
});
for(const key of ["","a b","a,b","x".repeat(129),"bad/","key\n"])test("invalid key "+JSON.stringify(key),async()=>{
 let calls=0;const api=apiModule.createCommitmentsApi({baseUrl:"https://fides.example/api/v1",fetcher:async()=>{calls++;return Response.json(row());}});
 await assert.rejects(async()=>api.createCommitment(body(),key));assert.equal(calls,0);
});
for(const [input,expected] of [["0.01",1],["1",100],["1.1",110],["1.23",123],["0.29",29],["9999999999.99",999999999999],["10000000000",1000000000000]])
 test("money "+input,()=>assert.equal(parseMinor(input),expected));
for(const input of ["0","-1","+1","1.001","1.",".1","1e2","1,000"," 1","NaN","Infinity","10000000000.01"])
 test("invalid money "+input,()=>assert.throws(()=>parseMinor(input)));
for(const [input,expected] of [["0.01",1],["1",100],["5.25",525],["100",10000]])test("bps "+input,()=>assert.equal(parseBps(input),expected));
for(const input of ["0","100.01","1.001","5%","-1"])test("invalid bps "+input,()=>assert.throws(()=>parseBps(input)));
test("explicit modern no-deadline terms, closed body",()=>{assert.deepEqual(body().terms,{due_date:null,installment_dates:null,interest_type:"NONE",interest_rate_bps:null,grace_period_days:0});
 assert.deepEqual(Object.keys(body()).sort(),["connection_id","actor_role","type","principal_amount_minor","currency","description","terms"].sort());});
test("single, installments, bps and grace exact",()=>{
 const form={...initialForm(CID),role:"LENDER",amount:"1",schedule:"single",due:"2028-02-29",interest:"SIMPLE_FIXED",percent:"5.25",grace:"365"};
 assert.equal(proposalBody(form,[CID]).terms.due_date,"2028-02-29");assert.equal(proposalBody(form,[CID]).terms.interest_rate_bps,525);
 const result=proposalBody({...form,schedule:"installments",dates:["2028-03-01","2028-04-01"]},[CID]);assert.equal(result.terms.due_date,null);
 assert.deepEqual(result.terms.installment_dates,["2028-03-01","2028-04-01"]);
});
for(const patch of [{role:""},{connection:B},{amount:"0"},{currency:"EUR"},{type:"OTHER"},{description:"x".repeat(501)},
 {grace:"366"},{grace:"1.0"},{grace:"-1"},{schedule:"single",due:"2026-02-30"},
 {schedule:"installments",dates:["2026-01-01"]},{schedule:"installments",dates:["2026-02-01","2026-01-01"]},
 {schedule:"installments",dates:["2026-01-01","2026-01-01"]},{interest:"SIMPLE_FIXED",percent:""},{schedule:"other"}])
 test("invalid form "+JSON.stringify(patch),()=>assert.throws(()=>proposalBody({...initialForm(CID),role:"BORROWER",amount:"1",...patch},[CID])));
test("60 installments allowed, 61 denied; no UTC conversion",()=>{
 const dates=Array.from({length:60},(_,i)=>"2026-"+String(1+Math.floor(i/28)).padStart(2,"0")+"-"+String(1+i%28).padStart(2,"0"));
 const form={...initialForm(CID),role:"BORROWER",amount:"1",schedule:"installments",dates};assert.deepEqual(proposalBody(form,[CID]).terms.installment_dates,dates);
 assert.throws(()=>proposalBody({...form,dates:[...dates,"2026-04-01"]},[CID]));assert.equal(validDate("2026-01-01T00:00:00Z"),false);
});
test("description trims blank and counts Unicode code points",()=>{
 assert.equal(proposalBody({...initialForm(CID),role:"BORROWER",amount:"1",description:"  "},[CID]).description,null);
 assert.equal(Array.from(proposalBody({...initialForm(CID),role:"BORROWER",amount:"1",description:"😀".repeat(500)},[CID]).description).length,500);
});
for(const status of apiModule.commitmentStatuses)for(const actor of [A,B,C])test("action matrix "+status+" "+actor,()=>{
 const r=row(status);assert.deepEqual(model.proposalActions(r,actor),actor===C||status!=="PENDING_CONFIRMATION"?[]:actor===A?["cancel"]:["confirm","reject"]);
 assert.equal(model.commitmentRole(r,actor),actor===A?"Borrower":actor===B?"Lender":null);
});
test("creator does not mean borrower; invalid participant shape fails closed",()=>{
 const r={...row(),creator:person(B)};assert.deepEqual(model.proposalActions(r,B),["cancel"]);assert.deepEqual(model.proposalActions(r,A),["confirm","reject"]);
 assert.equal(model.commitmentRole({...row(),lender:person(A)},A),null);assert.equal(model.commitmentRole({...row(),creator:person(C)},A),null);
});
test("multiple commitments remain independent and preserve server order",async()=>{
 const values=[row("ACTIVE"),{...row(),id:B,currency:"USD"},{...row(),id:C,currency:"GBP"}];
 const api=apiModule.createCommitmentsApi({baseUrl:"https://fides.example/api/v1",fetcher:async()=>Response.json(values)});
 assert.deepEqual(await api.listCommitments(),values);
});
test("closed projections do not retain private fields",()=>{
 assert.deepEqual(apiModule.commitmentResponse({...row(),outstanding:8,borrower:{...person(A),phone:"private"}}),row());
 const value=terms();value.versions[0].created_by.phone="private";assert.equal(JSON.stringify(apiModule.termsResponse(value)).includes("private"),false);
 assert.deepEqual(apiModule.installmentResponse({...installment(),repayment:"private"}),installment());
});
test("missing current terms rejected; future version is not selected",()=>{
 const value=terms();value.versions.push({...value.versions[0],id:B,version_no:2,effective_at:"2030-01-01T00:00:00Z"});
 assert.equal(model.currentTerms(apiModule.termsResponse(value)).id,VID);assert.throws(()=>apiModule.termsResponse({...value,current_terms_version_id:C}));
});
for(const suffix of ["","/"+ID,"/"+ID+"/terms","/"+ID+"/installments"])test("GET relay "+suffix,()=>assert.equal(isAllowedApiRoute("GET",("commitments"+suffix).split("/")),true));
for(const suffix of ["","/"+ID+"/confirm","/"+ID+"/reject","/"+ID+"/cancel"])test("POST relay "+suffix,()=>assert.equal(isAllowedApiRoute("POST",("commitments"+suffix).split("/")),true));
for(const [method,suffix] of [["GET","/"+ID+"/repayments"],["POST","/"+ID+"/repayments"],["GET","/"+ID+"/ledger"],["POST","/"+ID+"/extension-requests"],["GET","/../me"],["GET","/%2e%2e"],["DELETE","/"+ID],["POST","/"+ID],["GET","/bad"],["GET","/"+ID+"/terms/extra"]])
 test("relay denied "+method+suffix,()=>assert.equal(isAllowedApiRoute(method,("commitments"+suffix).split("/")),false));
test("actual relay preserves write key and safe headers, rejects duplicates; other routes do not forward key",async t=>{
 const old=Module._load;Module._load=function(request,parent,main){return old.call(this,request.startsWith("@fides/shared/")?path.join(__dirname,"../shared",request.slice(14)+".ts"):request,parent,main);};
 let route;try{route=require("../web/app/api/v1/[...path]/route.ts");}finally{Module._load=old;}
 const previous=process.env.FIDES_BACKEND_API_URL;process.env.FIDES_BACKEND_API_URL="http://127.0.0.1:8000/api/v1";let calls=0;
 t.mock.method(global,"fetch",async(url,init)=>{calls++;assert.equal(init.headers.get("Idempotency-Key"),url.includes("commitments")?"same":null);
   assert.equal(init.headers.get("Cookie"),null);assert.equal(init.headers.get("X-Forwarded-For"),null);assert.equal(init.redirect,"error");
   return Response.json(row(),{headers:{"WWW-Authenticate":"Bearer","Retry-After":"1","X-Request-ID":"safe","Set-Cookie":"private"}});});
 try{
 for(const parts of [["commitments"],["connections"]]){const response=await route.POST(new Request("http://localhost/api/v1/"+parts[0],{method:"POST",headers:{"Idempotency-Key":"same",Authorization:"Bearer memory",Cookie:"private"}}),{params:Promise.resolve({path:parts})});
   assert.equal(response.status,200);assert.equal(response.headers.get("Cache-Control"),"no-store");assert.equal(response.headers.get("Set-Cookie"),null);assert.equal(response.headers.get("X-Request-ID"),"safe");}
 const duplicate=await route.POST(new Request("http://localhost/api/v1/commitments",{method:"POST",headers:[["Idempotency-Key","one"],["Idempotency-Key","two"]]}),{params:Promise.resolve({path:["commitments"]})});assert.equal(duplicate.status,400);assert.equal(calls,2);
 }finally{if(previous===undefined)delete process.env.FIDES_BACKEND_API_URL;else process.env.FIDES_BACKEND_API_URL=previous;}
});
test("ambiguous intent retains exact key/payload, requires reconciliation, success clears",()=>{
 const store=new MutationIntents(),scope="actor:new:create";const first=store.begin(scope,body(),()=>"first");
 store.failed(scope,new ApiError("NETWORK_ERROR","safe",null));assert.throws(()=>store.begin(scope,body()));
 store.reconciled(scope);assert.equal(store.begin(scope,body()).key,first.key);
 assert.throws(()=>store.begin(scope,{...body(),currency:"USD"}));store.succeeded(scope);
 assert.equal(store.begin(scope,{...body(),currency:"USD"},()=>"second").key,"second");
});
test("definite failure discards key, idempotency conflict never silently rekeys",()=>{
 const store=new MutationIntents();store.begin("scope",{},()=>"first");store.failed("scope",new ApiError("VALIDATION_ERROR","safe",422));assert.equal(store.get("scope"),undefined);
 store.begin("scope",{},()=>"second");store.failed("scope",new ApiError("IDEMPOTENCY_CONFLICT","safe",409));store.reconciled("scope");assert.throws(()=>store.begin("scope",{}));assert.equal(store.get("scope").key,"second");
 assert.equal(ambiguous(new ApiError("SERVICE_UNAVAILABLE","safe",503)),true);assert.equal(canonical({b:2,a:1}),canonical({a:1,b:2}));
});
function harness(platform,{creation=false,overrides={}}={}) {
 let current=row();const calls={mutation:0,reads:0,keys:[]};
 const commitments={listCommitments:async()=>{calls.reads++;return[current];},getCommitment:async()=>current,getCommitmentTerms:async()=>terms(),getCommitmentInstallments:async()=>[],
   createCommitment:async(body,key)=>{calls.mutation++;calls.keys.push(key);return current;},confirmCommitment:async(id,key)=>{calls.mutation++;calls.keys.push(key);current=row("ACTIVE");return current;},
   rejectCommitment:async()=>row("REJECTED"),cancelCommitment:async()=>row("CANCELLED"),...overrides};
 const env={state:{status:"authenticated",user:{id:creation?A:B}},commitments,intents:new MutationIntents(),connections:{listConnections:async()=>[]},session:{snapshot:()=>env.state,bootstrap:async()=>{}}};
 let index=0;const slots=[],effects=[];const same=(a,b)=>a&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
 const react={useState(initial){const i=index++;if(!slots[i])slots[i]={value:typeof initial==="function"?initial():initial};return[slots[i].value,v=>{slots[i].value=typeof v==="function"?v(slots[i].value):v;}];},
   useRef(initial){const i=index++;return slots[i]??(slots[i]={current:initial});},
   useCallback(fn,deps){const i=index++;if(!slots[i]||!same(slots[i].deps,deps))slots[i]={fn,deps};return slots[i].fn;},
   useEffect(fn,deps){const i=index++;if(!slots[i]||!same(slots[i].deps,deps)){slots[i]?.cleanup?.();slots[i]={deps};effects.push(()=>{slots[i].cleanup=fn();});}}};
 const old=Module._load;Module._load=function(request,parent,main){
   if(request==="react")return react;if(request==="../auth/useAuth")return{useAuth:()=>env};
   if(request.startsWith("@fides/shared/"))return old.call(this,path.join(__dirname,"../shared",request.slice(14)+".ts"),parent,main);return old.call(this,request,parent,main);};
 const file=require.resolve("../"+platform+"/features/commitments/useCommitments.ts");let hook;try{delete require.cache[file];hook=require(file).useCommitments;}finally{Module._load=old;delete require.cache[file];}
 return{render(){index=0;const result=hook(creation?undefined:ID,creation);while(effects.length)effects.shift()();return result;},env,commitments,calls};
}
const settle=()=>new Promise(setImmediate);
for(const platform of ["web","mobile"]){
 test(platform+" duplicate guard and no optimistic state",async()=>{
  const h=harness(platform);h.render();await settle();let resolve;h.commitments.confirmCommitment=(id,key)=>{h.calls.mutation++;h.calls.keys.push(key);return new Promise(r=>{resolve=r;});};
  const promise=h.render().action("confirm");assert.equal(h.render().data.detail.status,"PENDING_CONFIRMATION");await h.render().action("confirm");assert.equal(h.calls.mutation,1);
  h.commitments.getCommitment=async()=>row("ACTIVE");h.commitments.listCommitments=async()=>[row("ACTIVE")];resolve(row("ACTIVE"));await promise;assert.equal(h.render().data.detail.status,"ACTIVE");assert.equal(h.render().pending("confirm"),undefined);
 });
 test(platform+" ambiguous create retains exact key, explicit retry only",async()=>{
  const h=harness(platform,{creation:true});h.render();await settle();let fail=true;h.commitments.createCommitment=async(_body,key)=>{h.calls.mutation++;h.calls.keys.push(key);if(fail)throw new ApiError("NETWORK_ERROR","safe",null);return row();};
  await h.render().create(body());assert.equal(h.calls.mutation,1);const pending=h.render().pending("create");assert.ok(pending);assert.equal(pending.needsReconcile,false);
  await h.render().create({...body(),currency:"USD"});assert.equal(h.calls.mutation,1);fail=false;await h.render().create(body());assert.equal(h.calls.mutation,2);assert.equal(h.calls.keys[0],h.calls.keys[1]);assert.equal(h.render().pending("create"),undefined);
 });
 test(platform+" failed reconcile freezes retry and preserves data",async()=>{
  const h=harness(platform,{creation:true});h.render();await settle();h.commitments.createCommitment=async()=>{h.calls.mutation++;throw new ApiError("SERVICE_UNAVAILABLE","safe",503);};
  h.commitments.listCommitments=async()=>{throw new ApiError("NETWORK_ERROR","safe",null);};await h.render().create(body());assert.ok(h.render().data);assert.equal(h.render().pending("create").needsReconcile,true);
  await h.render().create(body());assert.equal(h.calls.mutation,1);h.commitments.listCommitments=async()=>[row()];await h.render().refresh();assert.equal(h.render().pending("create").needsReconcile,false);
 });
 test(platform+" unrelated or inconsistent terms fail closed",async()=>{
  const h=harness(platform,{overrides:{getCommitmentTerms:async()=>({...terms(),commitment_id:C})}});h.render();await settle();assert.equal(h.render().data,null);assert.ok(h.render().error);
 });
 test(platform+" connection status never gates existing commitment access",async()=>{
  const h=harness(platform);h.env.connections.listConnections=async()=>{throw new Error("Must not fetch connections for existing commitment");};h.render();await settle();assert.equal(h.render().data.detail.id,ID);
 });
}

for (const platform of ["web","mobile"]) {
 test(platform+" ambiguous confirm blocks opposite action until original outcome resolves",async()=>{
  const h=harness(platform);h.render();await settle();h.commitments.confirmCommitment=async()=>{h.calls.mutation++;throw new ApiError("NETWORK_ERROR","safe",null);};
  h.commitments.rejectCommitment=async()=>{h.calls.mutation++;return row("REJECTED");};await h.render().action("confirm");
  assert.equal(h.render().actionBlocked("reject"),true);assert.equal(h.render().actionBlocked("confirm"),false);
  await h.render().action("reject");assert.equal(h.calls.mutation,1);
  h.commitments.getCommitment=async()=>row("ACTIVE");await h.render().refresh();assert.equal(h.render().pending("confirm"),undefined);
 });
 test(platform+" incoherent installment snapshot withheld",async()=>{
  const h=harness(platform,{overrides:{getCommitmentTerms:async()=>terms("installments"),getCommitmentInstallments:async()=>[installment()]}});h.render();await settle();assert.equal(h.render().data,null);assert.ok(h.render().error);
 });
 test(platform+" successful mutation followed by failed read never displays stale terms",async()=>{
  const h=harness(platform);h.render();await settle();h.commitments.listCommitments=async()=>{throw new ApiError("NETWORK_ERROR","safe",null);};
  await h.render().action("confirm");assert.equal(h.render().data.detail.status,"ACTIVE");assert.equal(h.render().data.terms,null);assert.equal(h.render().data.installments,null);assert.ok(h.render().error);
 });
}
