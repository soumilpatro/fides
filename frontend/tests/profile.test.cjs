const {A,B,ID,E,me,harness}=require('./f6-harness.cjs'),test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {createProfileApi,profileBody,meResponse}=require('../shared/api/profile.ts'),{AuthSession}=require('../shared/auth/session.ts'),{ApiError}=require('../shared/api/errors.ts'),{isAllowedApiRoute,isAllowedApiQuery}=require('../shared/api/relay.ts');
for(const body of [{display_name:'New'},{timezone:'Europe/London'},{display_name:'New',timezone:'Europe/London'}])test('exact PATCH '+JSON.stringify(body),async()=>{const api=createProfileApi({baseUrl:'https://fides.example/api/v1',fetcher:async(url,init)=>{assert.equal(url,'https://fides.example/api/v1/me');assert.equal(init.method,'PATCH');assert.equal(init.body,JSON.stringify(body));assert.equal(init.headers.get('Idempotency-Key'),null);return Response.json({...me(),...body});}});assert.deepEqual(await api.updateProfile({...body,phone:'excluded'}),{...me(),...body});});
for(const body of [{},{display_name:null},{timezone:null},{display_name:''},{timezone:''},{phone:'unsupported'}])test('invalid profile '+JSON.stringify(body),()=>assert.throws(()=>profileBody(body)));
test('closed MeResponse',()=>assert.deepEqual(meResponse({...me(),session:'private'}),me()));
test('exact deactivate empty body local confirmation not sent',async()=>{const api=createProfileApi({baseUrl:'https://fides.example/api/v1',fetcher:async(url,init)=>{assert.equal(url,'https://fides.example/api/v1/me/deactivate');assert.equal(init.method,'POST');assert.equal(init.body,'{}');assert.equal(init.headers.get('Idempotency-Key'),null);return Response.json({status:'DEACTIVATED',deactivated_at:'2026-10-02T00:00:00Z'});}});assert.equal((await api.deactivate('DEACTIVATE')).status,'DEACTIVATED');});
for(const endpoint of ['me','me/deactivate'])test('profile query denied '+endpoint,()=>assert.equal(isAllowedApiQuery(endpoint.split('/'),new URLSearchParams('actor_id='+B)),false));
for(const platform of ['web','mobile']){
 test(platform+' authoritative save and typed deactivation refusal/success',async()=>{
 let updated=0,cleared=0,calls=0,blocked=true;const env={state:{status:'authenticated',user:me()},session:{reconcileUser:u=>{env.state={status:'authenticated',user:u};updated++;},clearDeactivated:async()=>cleared++,bootstrap:async()=>{},logout:async()=>{}},profile:{updateProfile:async body=>({...me(),...body}),deactivate:async()=>{calls++;if(blocked)throw new ApiError('ACCOUNT_HAS_UNRESOLVED_COMMITMENTS','safe',409);return {status:'DEACTIVATED',deactivated_at:'2026-10-02T00:00:00Z'};}}};
 const h=harness(platform,'profile','useProfile',env);assert.equal(await h.render().save({display_name:'Server name'}),true);assert.equal(updated,1);assert.equal(h.render().user.display_name,'Server name');
 for(const typed of ['deactivate','DEACTIVATE ','','DeActivate'])assert.equal(await h.render().deactivate(typed),false);assert.equal(calls,0);
 assert.equal(await h.render().deactivate('DEACTIVATE'),false);assert.equal(h.render().error,"Your account can't be deactivated while unresolved commitments remain.");assert.equal(cleared,0);blocked=false;await h.render().deactivate('DEACTIVATE');assert.equal(cleared,1);
 });
 test(platform+' no preference phone-edit or persistent credentials introduced',()=>{const source=fs.readFileSync(platform+'/features/profile/Profile.tsx','utf8');assert.ok(source.includes('Phone (read-only)'));assert.ok(source.includes('Type DEACTIVATE to continue.'));assert.ok(!/AsyncStorage|localStorage|password|push token|avatar|phone.*onChange/.test(source));});
}
test('real AuthSession authoritative same-account reconciliation and deactivation local clear',async()=>{
 let stored=null,get=0,clear=0;const api={getMe:async()=>{get++;return me();},logout:async()=>{}};
 const session=new AuthSession({read:async()=>stored,write:async v=>stored=v,clear:async()=>{clear++;stored=null;}},api);
 await session.establish({access_token:'memory',refresh_token:'memory-refresh',token_type:'Bearer',access_expires_at:'2099-01-01T00:00:00Z',refresh_expires_at:'2099-02-01T00:00:00Z',user:me()});assert.equal(get,1);session.reconcileUser({...me(),display_name:'Server'});assert.equal(session.snapshot().user.display_name,'Server');assert.equal(session.accessToken(),'memory');assert.throws(()=>session.reconcileUser({...me(),id:B}));await session.clearDeactivated();assert.equal(clear,1);assert.equal(session.accessToken(),null);assert.equal(session.snapshot().status,'anonymous');
});

test('F6 web confirmation traps forward/backward Tab without exposing background controls',()=>{
 const {trapConfirmationFocus}=require('../web/features/f6-dialog.ts');
 const first={focus(){first.called=true;}},last={focus(){last.called=true;}},dialog={ownerDocument:{activeElement:last},querySelectorAll:()=>[first,last]};
 let prevented=0;trapConfirmationFocus({key:'Tab',shiftKey:false,currentTarget:dialog,preventDefault:()=>prevented++});assert.equal(prevented,1);assert.equal(first.called,true);
 dialog.ownerDocument.activeElement=first;trapConfirmationFocus({key:'Tab',shiftKey:true,currentTarget:dialog,preventDefault:()=>prevented++});assert.equal(last.called,true);assert.equal(prevented,2);
});
