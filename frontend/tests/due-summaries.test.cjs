const test=require('node:test'),assert=require('node:assert/strict');
const {dueSummaryItemResponse,dueSummaryPageResponse}=require('../shared/api/due-summaries.ts');
const {dueRoleLabel,dueDateLabel,dueInstallmentLabel}=require('../shared/dashboard/due-presentation.ts');
const ID='00000000-0000-4000-8000-000000000003',A='00000000-0000-4000-8000-000000000001',E='00000000-0000-4000-8000-000000000004';
const item=(patch={})=>({commitment_id:ID,counterparty:{id:A,display_name:'Riya'},role:'BORROWER',currency:'INR',verified_outstanding_minor:12500,due_date:'2026-10-09',due_timezone:'Asia/Kolkata',schedule_mode:'single',installment_id:null,...patch});

test('due summary decoder accepts approved fields without deriving due state',()=>{
 const row=dueSummaryItemResponse(item());assert.equal(row.verified_outstanding_minor,12500);assert.equal(dueRoleLabel(row),'Borrowed');assert.equal(dueInstallmentLabel(row),'Commitment due');assert.equal(dueDateLabel(row.due_date),'9 Oct 2026');
 const installment=dueSummaryItemResponse(item({installment_id:E,schedule_mode:'installments'}));assert.equal(dueInstallmentLabel(installment),'Installment due');
});
test('due summary rejects invalid authoritative values',()=>{
 for(const patch of [{role:'OTHER'},{currency:'EUR'},{verified_outstanding_minor:-1},{due_date:'09/10/2026'},{due_timezone:''},{installment_id:'bad'}])assert.throws(()=>dueSummaryItemResponse(item(patch)));
});
test('due page preserves cursor and items only',()=>{
 assert.deepEqual(dueSummaryPageResponse({items:[item()],next_cursor:'opaque'}).next_cursor,'opaque');
 assert.throws(()=>dueSummaryPageResponse({items:[item()],next_cursor:''}));
});
