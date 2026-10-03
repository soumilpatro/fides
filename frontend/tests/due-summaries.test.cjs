const test=require('node:test'),assert=require('node:assert/strict');
const {createDueSummariesApi,dueSummaryItemResponse,dueSummaryPageResponse,appendDueSummary}=require('../shared/api/due-summaries.ts');
const {dueRoleLabel,dueDateLabel,dueInstallmentLabel}=require('../shared/dashboard/due-presentation.ts');
const {isAllowedApiRoute,isAllowedApiQuery}=require('../shared/api/relay.ts');
const ID='00000000-0000-4000-8000-000000000003',A='00000000-0000-4000-8000-000000000001',E='00000000-0000-4000-8000-000000000004';
const item=(patch={})=>({commitment_id:ID,counterparty:{id:A,display_name:'Riya'},role:'BORROWER',currency:'INR',verified_outstanding_minor:12500,due_date:'2026-10-09',due_timezone:'Asia/Kolkata',schedule_mode:'single',installment_id:null,...patch});

test('due summary decoder accepts exact merged backend contract',()=>{
 const row=dueSummaryItemResponse(item());assert.equal(row.verified_outstanding_minor,12500);assert.equal(dueRoleLabel(row),'Borrowed');assert.equal(dueInstallmentLabel(row),'Commitment due');assert.equal(dueDateLabel(row.due_date),'9 Oct 2026');
 const installment=dueSummaryItemResponse(item({installment_id:E,schedule_mode:'installments'}));assert.equal(dueInstallmentLabel(installment),'Installment due');
});
test('due summary rejects invalid authoritative values',()=>{
 for(const patch of [{role:'OTHER'},{currency:'EUR'},{verified_outstanding_minor:0},{verified_outstanding_minor:-1},{due_date:'09/10/2026'},{due_timezone:''},{schedule_mode:'other'},{installment_id:'bad'},{schedule_mode:'single',installment_id:E},{schedule_mode:'installments',installment_id:null}])assert.throws(()=>dueSummaryItemResponse(item(patch)));
});
test('due page preserves opaque cursor and rejects invalid cursor',()=>{
 assert.equal(dueSummaryPageResponse({items:[item()],next_cursor:'opaque/+/='}).next_cursor,'opaque/+/=');
 for(const cursor of ['', 'a'.repeat(513), 'bad\n'])assert.throws(()=>dueSummaryPageResponse({items:[item()],next_cursor:cursor}));
});
test('append preserves server ordering and dedupes occurrence identity',()=>{
 const first=item(),same=item(),second=item({due_date:'2026-10-10'});
 assert.deepEqual(appendDueSummary([first],[same,second]),[first,second]);
});
test('due API uses only approved upcoming/overdue routes and bounded query',async()=>{
 const calls=[];
 const api=createDueSummariesApi({baseUrl:'https://fides.example/api/v1',fetcher:async(url,init)=>{
  calls.push({url,method:init.method,key:init.headers.get('Idempotency-Key')});
  return Response.json({items:[item()],next_cursor:null});
 }});
 await api.list('upcoming',{limit:50});
 await api.list('overdue',{limit:100,cursor:'opaque/+/='});
 assert.equal(calls[0].url,'https://fides.example/api/v1/summary/upcoming?limit=50');
 assert.equal(calls[1].url,'https://fides.example/api/v1/summary/overdue?limit=100&cursor=opaque%2F%2B%2F%3D');
 assert.deepEqual(calls.map(call=>call.method),['GET','GET']);
 assert.deepEqual(calls.map(call=>call.key),[null,null]);
});
for(const options of [{limit:0},{limit:101},{limit:1.5},{cursor:''},{cursor:'a'.repeat(513)},{cursor:'bad\n'}])test('due API rejects invalid options '+JSON.stringify(options),async()=>{
 let calls=0;const api=createDueSummariesApi({baseUrl:'https://fides.example/api/v1',fetcher:async()=>{calls++;return Response.json({});}});
 await assert.rejects(()=>api.list('upcoming',options));assert.equal(calls,0);
});
test('relay allows exact due routes and exact query surface',()=>{
 for(const kind of ['upcoming','overdue']){
  const path=['summary',kind];
  assert.equal(isAllowedApiRoute('GET',path),true);
  assert.equal(isAllowedApiRoute('POST',path),false);
  for(const query of ['', 'limit=50', 'limit=100&cursor=opaque'])assert.equal(isAllowedApiQuery(path,new URLSearchParams(query)),true);
  for(const query of ['offset=1','limit=0','limit=101','limit=1&limit=2','cursor=','cursor=bad%0A'])assert.equal(isAllowedApiQuery(path,new URLSearchParams(query)),false);
 }
});
