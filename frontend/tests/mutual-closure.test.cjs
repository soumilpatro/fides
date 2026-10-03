const test=require('node:test'),assert=require('node:assert/strict');
const {createMutualClosureApi,mutualClosureResponse,closureBody}=require('../shared/api/mutual-closure.ts');
const {canRequestMutualClosure,mutualClosureActions,hasPendingRepayment,verifiedRepayments,closureStatusLabel}=require('../shared/mutual-closure/model.ts');
const {isAllowedApiRoute,isAllowedApiQuery}=require('../shared/api/relay.ts');
const {ledgerResponse}=require('../shared/api/ledger.ts');
const {historyText}=require('../shared/dashboard/presentation.ts');
const A='00000000-0000-4000-8000-000000000001',B='00000000-0000-4000-8000-000000000002',ID='00000000-0000-4000-8000-000000000003',E='00000000-0000-4000-8000-000000000004';
const person=id=>({id,display_name:id===A?'Riya':'Morgan'});
const row=(status='REQUESTED')=>({id:E,commitment_id:ID,requested_by:person(A),counterparty:person(B),status,currency:'INR',outstanding_snapshot_minor:12500,waived_amount_minor:12500,note:'Close together',decided_by:status==='REQUESTED'?null:person(B),decided_at:status==='REQUESTED'?null:'2026-10-03T10:00:00Z',created_at:'2026-10-03T09:00:00Z',updated_at:'2026-10-03T10:00:00Z'});
const parent=status=>({id:ID,status,borrower:person(A),lender:person(B)});
const repayment=status=>({id:E,commitment_id:ID,status,reported_by:person(A),amount_minor:5000,currency:'INR',payment_date:'2026-10-01',reported_at:'2026-10-01T00:00:00Z',created_at:'2026-10-01T00:00:00Z',note:null});

test('closure decoder preserves authoritative snapshot and waiver',()=>{
 assert.deepEqual(mutualClosureResponse(row(),ID),row());
 assert.equal(mutualClosureResponse(row('ACCEPTED'),ID).waived_amount_minor,12500);
 assert.throws(()=>mutualClosureResponse({...row(),outstanding_snapshot_minor:0},ID));
 assert.throws(()=>mutualClosureResponse({...row(),commitment_id:A},ID));
 assert.throws(()=>mutualClosureResponse({...row(),counterparty:person(A)},ID));
 assert.throws(()=>mutualClosureResponse({...row(),decided_by:person(B),decided_at:'2026-10-03T10:00:00Z'},ID));
});

test('closure body trims, blank becomes null, max 500',()=>{
 assert.deepEqual(closureBody('  context  '),{note:'context'});
 assert.deepEqual(closureBody('   '),{note:null});
 assert.throws(()=>closureBody('x'.repeat(501)));
});

test('closure eligibility and actions do not derive financial balance',()=>{
 assert.equal(canRequestMutualClosure(parent('ACTIVE'),[]),true);
 assert.equal(canRequestMutualClosure(parent('PARTIALLY_REPAID'),[]),true);
 assert.equal(canRequestMutualClosure(parent('FULLY_REPAID'),[]),false);
 assert.equal(canRequestMutualClosure(parent('ACTIVE'),[row()]),false);
 assert.deepEqual(mutualClosureActions(row(),A),['cancel']);
 assert.deepEqual(mutualClosureActions(row(),B),['accept','reject']);
 assert.deepEqual(mutualClosureActions(row('ACCEPTED'),B),[]);
 assert.equal(hasPendingRepayment([repayment('PENDING_VERIFICATION')]),true);
 assert.deepEqual(verifiedRepayments([repayment('VERIFIED'),repayment('DISPUTED')]).map(x=>x.status),['VERIFIED']);
 assert.equal(closureStatusLabel(row('ACCEPTED'),A),'Closed by mutual agreement');
});

test('closure API uses exact routes and idempotency on all writes',async()=>{
 const calls=[];
 const api=createMutualClosureApi({baseUrl:'https://fides.example/api/v1',fetcher:async(url,init)=>{
  calls.push({url,method:init.method,body:init.body,key:init.headers.get('Idempotency-Key')});
  const status=url.endsWith('/accept')?'ACCEPTED':url.endsWith('/reject')?'REJECTED':url.endsWith('/cancel')?'CANCELLED':'REQUESTED';
  return Response.json(url.includes('/closure-requests/')&&!url.includes('/commitments/')&&init.method==='GET'?row():url.endsWith('/closure-requests')&&init.method==='GET'?[row()]:row(status),{status:init.method==='POST'&&url.endsWith('/closure-requests')?201:200});
 }});
 await api.listClosureRequests(ID);await api.getClosureRequest(E,ID);
 await api.requestClosure(ID,{note:null},'key-create');await api.acceptClosure(E,ID,'key-accept');await api.rejectClosure(E,ID,'key-reject');await api.cancelClosure(E,ID,'key-cancel');
 assert.equal(calls[0].url,'https://fides.example/api/v1/commitments/'+ID+'/closure-requests');
 assert.equal(calls[1].url,'https://fides.example/api/v1/closure-requests/'+E);
 assert.deepEqual(calls.slice(2).map(c=>c.key),['key-create','key-accept','key-reject','key-cancel']);
});

test('relay exposes only approved closure routes with no query',()=>{
 const approved=[['GET',['commitments',ID,'closure-requests']],['POST',['commitments',ID,'closure-requests']],['GET',['closure-requests',E]],['POST',['closure-requests',E,'accept']],['POST',['closure-requests',E,'reject']],['POST',['closure-requests',E,'cancel']]];
 for(const [method,path] of approved){assert.equal(isAllowedApiRoute(method,path),true);assert.equal(isAllowedApiQuery(path,new URLSearchParams()),true);assert.equal(isAllowedApiQuery(path,new URLSearchParams('x=1')),false);}
 assert.equal(isAllowedApiRoute('DELETE',['closure-requests',E]),false);
});

test('closure ledger events stay distinct from repayments',()=>{
 const base={id:E,commitment_id:ID,actor:person(A),occurred_at:'2026-10-03T10:00:00Z'};
 const cases=[
  ['MUTUAL_CLOSURE_REQUESTED','REQUESTED','Requested mutual closure.'],
  ['MUTUAL_CLOSURE_ACCEPTED','ACCEPTED','Closed by mutual agreement.'],
  ['MUTUAL_CLOSURE_REJECTED','REJECTED','Rejected the mutual-closure request.'],
  ['MUTUAL_CLOSURE_CANCELLED','CANCELLED','Cancelled the mutual-closure request.'],
 ];
 for(const [event_type,status,prefix] of cases){
  const details={closure_request_id:E,currency:'INR',outstanding_snapshot_minor:12500,waived_amount_minor:12500,status,...(status==='ACCEPTED'?{resulting_commitment_status:'CLOSED'}:{})};
  const event=ledgerResponse({items:[{...base,event_type,details}],next_cursor:null},ID).items[0];
  assert.ok(historyText(event).startsWith(prefix));
  assert.equal('repayment_id' in event.details,false);
 }
});
