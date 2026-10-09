const {A,B,ID,E,notification,harness,settle}=require('./f6-harness.cjs'),test=require('node:test'),assert=require('node:assert/strict');
const {createNotificationsApi,notificationResponse,notificationTypes,reminderNotificationTypes}=require('../shared/api/notifications.ts'),{notificationText,notificationTarget,appendNotifications}=require('../shared/notifications/presentation.ts'),{isAllowedApiRoute,isAllowedApiQuery}=require('../shared/api/relay.ts');
const {notificationTimestamp,notificationActionLabel}=require('../shared/notifications/presentation.ts');

const instant='2026-10-04T15:16:03.006520Z';
for(const [zone,expected] of [['UTC','4 Oct 2026, 3:16 PM'],['Asia/Kolkata','4 Oct 2026, 8:46 PM'],['America/New_York','4 Oct 2026, 11:16 AM']])
 test('notification instant in saved timezone '+zone,()=>assert.equal(notificationTimestamp(instant,zone),expected));
for(const [value,expected] of [
 ['2026-03-08T06:59:00Z','8 Mar 2026, 1:59 AM'],['2026-03-08T07:01:00Z','8 Mar 2026, 3:01 AM'],
 ['2026-11-01T05:30:00Z','1 Nov 2026, 1:30 AM'],['2026-11-01T06:30:00Z','1 Nov 2026, 1:30 AM'],
])test('notification New York DST transition '+value,()=>assert.equal(notificationTimestamp(value,'America/New_York'),expected));
test('notification timestamp preserves date rollover, offset and original microseconds',()=>{
 const record=notification();record.created_at=instant;const before=JSON.stringify(record);
 assert.equal(notificationTimestamp('2026-10-04T23:30:00Z','Asia/Kolkata'),'5 Oct 2026, 5:00 AM');
 assert.equal(notificationTimestamp('2026-10-04T20:46:03.006520+05:30','UTC'),notificationTimestamp(instant,'UTC'));
 notificationTimestamp(record.created_at,'Asia/Kolkata');assert.equal(JSON.stringify(record),before);
});
test('notification timestamp never substitutes the device timezone or an invalid saved timezone',()=>{
 const old=process.env.TZ;
 try{for(const device of ['Pacific/Honolulu','Europe/London']){process.env.TZ=device;assert.equal(notificationTimestamp(instant,'Asia/Kolkata'),'4 Oct 2026, 8:46 PM');}}
 finally{if(old===undefined)delete process.env.TZ;else process.env.TZ=old;}
 assert.throws(()=>notificationTimestamp(instant,'Invalid/Timezone'),RangeError);
});
for(const read of [false,true])test('notification accessible actions retain '+(read?'read':'unread')+' and record context',()=>{
 for(const type of notificationTypes){const record={...notification(type),read_at:read?instant:null};assert.equal(notificationActionLabel(record),(read?'Read. ':'Unread. ')+notificationText(record)+' Open record.');}
});

// Render actual notification TSX/UI; stub only native hosts, auth/data and routing.
function notificationView(platform,record,timezone){
 const fs=require('node:fs'),path=require('node:path'),ts=require('typescript'),Module=require('node:module'),React=require('react');
 const load=Module._load,tsx=require.extensions['.tsx'],file=path.join(__dirname,'../'+platform+'/features/notifications/Notifications.tsx'),ui=path.join(__dirname,'../'+platform+'/components/ui/index.tsx');
 const calls={read:[],opened:[]},state=timezone?{status:'authenticated',user:{timezone}}:{status:'anonymous'};
 const snapshot={data:{items:[record],next_cursor:null},busy:false,error:null,activate:async row=>calls.read.push(row.id),refresh:async()=>{}};
 require.extensions['.tsx']=(m,f)=>m._compile(ts.transpileModule(fs.readFileSync(f,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,f);
 Module._load=function(request,parent,main){
  if(request==='./useNotifications')return{useNotifications:()=>snapshot};
  if(request==='../auth/useAuth')return{useAuth:()=>({state})};
  if(request==='next/navigation')return{useRouter:()=>({push:value=>calls.opened.push(value)})};
  if(request==='react-native')return{...Object.fromEntries(['View','Text','ScrollView','Pressable','TextInput','ActivityIndicator'].map(name=>[name,name])),StyleSheet:{create:value=>value}};
  return load.call(this,request.startsWith('@fides/shared/')?path.join(__dirname,'../shared',request.slice(14)+'.ts'):request,parent,main);
 };
 const nodes=[],texts=[];
 function render(node,inText=false){
  if(node===null||node===undefined||typeof node==='boolean')return;
  if(Array.isArray(node)){node.forEach(value=>render(value,inText));return;}
  if(typeof node==='string'||typeof node==='number'){if(platform==='mobile'&&node!=='')assert.ok(inText,'Unwrapped native text');texts.push(String(node));return;}
  if(typeof node.type==='function'){render(node.type(node.props),inText);return;}
  if(node.type!==React.Fragment)nodes.push(node);
  render(node.props.children,inText||node.type==='Text');
 }
 try{delete require.cache[file];delete require.cache[ui];render(require(file).Notifications({onOpen:value=>calls.opened.push(value)}));return{nodes,texts,calls};}
 finally{Module._load=load;if(tsx)require.extensions['.tsx']=tsx;else delete require.extensions['.tsx'];delete require.cache[file];delete require.cache[ui];}
}
for(const platform of ['web','mobile'])for(const read of [false,true])test(platform+' notification uses saved timezone, accessible action and unchanged navigation ('+(read?'read':'unread')+')',()=>{
 const record={...notification('REPAYMENT_REPORTED'),actor:{id:B,display_name:'A very long counterparty name '.repeat(15)},created_at:instant,read_at:read?instant:null};
 const before=JSON.stringify(record),view=notificationView(platform,record,'Asia/Kolkata');
 assert.ok(view.texts.includes('4 Oct 2026, 8:46 PM'));assert.ok(view.texts.includes(notificationText(record)));assert.ok(view.texts.includes(read?'Read':'Unread'));
 const action=view.nodes.find(node=>node.props[platform==='web'?'aria-label':'accessibilityLabel']===notificationActionLabel(record));assert.ok(action);
 action.props[platform==='web'?'onClick':'onPress']();assert.deepEqual(view.calls.read,[record.id]);
 assert.deepEqual(view.calls.opened,[platform==='web'?'/app/repayments/'+A:notificationTarget(record)]);
 if(platform==='web'){assert.equal(view.nodes.find(node=>node.type==='time').props.dateTime,instant);assert.ok(view.nodes.some(node=>node.props.className==='f6-wrap'));}
 else{const label=view.nodes.find(node=>node.type==='Text'&&node.props.children===notificationText(record));assert.equal(label.props.style[0].flexShrink,1);assert.equal(label.props.style[0].maxWidth,'100%');}
 assert.equal(JSON.stringify(record),before);
 const utc=notificationView(platform,record,'UTC');assert.ok(utc.texts.includes('4 Oct 2026, 3:16 PM'));
});
for(const platform of ['web','mobile'])test(platform+' unresolved auth cannot render notification times using device timezone',()=>assert.deepEqual(notificationView(platform,notification(),null).texts,[]));

for(const type of notificationTypes)test('closed '+type+' projection/copy/target',()=>{
 const r=notification(type);
 assert.deepEqual(notificationResponse({...r,amount_minor:100,reason:'private',payload:{},actor:r.actor?{...r.actor,phone:'private'}:null}),r);
 if(reminderNotificationTypes.includes(type)){
  assert.match(notificationText(r),/^Payment /);
 }else{
  assert.ok(notificationText(r).startsWith('Morgan '));
 }
 assert.ok(!/100|private/.test(notificationText(r)));
 assert.deepEqual(notificationTarget(r),type.startsWith('REPAYMENT_')?{page:'repayment',id:A,parent:ID}:{page:'commitment',id:ID,extension:type.startsWith('EXTENSION_')});
});

for(const field of Object.keys(notification()))test('required '+field,()=>{const r=notification();delete r[field];assert.throws(()=>notificationResponse(r));});
for(const patch of [{type:'UNKNOWN'},{actor:{id:'bad',display_name:'Name'}},{created_at:'bad'},{repayment_id:A},{read_at:'2025-01-01T00:00:00Z'}])test('invalid notification '+JSON.stringify(patch),()=>assert.throws(()=>notificationResponse({...notification(),...patch})));

for(const type of reminderNotificationTypes){
 test(type+' requires null actor and no child resource ids',()=>{
  assert.throws(()=>notificationResponse({...notification(type),actor:{id:B,display_name:'Morgan'}}));
  assert.throws(()=>notificationResponse({...notification(type),repayment_id:A}));
  assert.throws(()=>notificationResponse({...notification(type),extension_request_id:E}));
 });
}
for(const type of notificationTypes.filter(type=>!reminderNotificationTypes.includes(type)))test(type+' requires human actor',()=>{
 assert.throws(()=>notificationResponse({...notification(type),actor:null}));
});

test('exact list and read wires no key cookies',async()=>{
 let calls=0;const api=createNotificationsApi({baseUrl:'https://fides.example/api/v1',fetcher:async(url,init)=>{calls++;assert.equal(init.headers.get('Idempotency-Key'),null);assert.equal(init.credentials,'omit');if(init.method==='GET'){assert.equal(url,'https://fides.example/api/v1/notifications?limit=50&cursor=opaque%2F..%2F%2B%3D');assert.equal(init.body,undefined);return Response.json({items:[notification()],next_cursor:null});}assert.equal(url,'https://fides.example/api/v1/notifications/'+E+'/read');assert.equal(init.body,'{}');return Response.json({...notification(),read_at:'2026-10-02T00:00:00Z'});}});
 await api.listNotifications({cursor:'opaque/../+='});assert.ok((await api.markRead(E)).read_at);assert.equal(calls,2);
});
for(const options of [{limit:0},{limit:101},{limit:1.1},{cursor:''},{cursor:'a'.repeat(513)},{cursor:String.fromCharCode(10)}])test('invalid options '+JSON.stringify(options),async()=>{let calls=0;const api=createNotificationsApi({baseUrl:'https://fides.example',fetcher:async()=>calls++});await assert.rejects(()=>api.listNotifications(options));assert.equal(calls,0);});
for(const query of ['offset=1','user_id='+A,'read_at=null','limit=0','limit=101','limit=1&limit=2','cursor=','cursor='+ 'a'.repeat(513)])test('relay query rejected '+query,()=>assert.equal(isAllowedApiQuery(['notifications'],new URLSearchParams(query)),false));
for(const query of ['','limit=50','limit=100&cursor=opaque'])test('relay query accepted '+query,()=>assert.equal(isAllowedApiQuery(['notifications'],new URLSearchParams(query)),true));
for(const route of ['notifications/read-all','notifications/preferences','notifications/push','notifications/'+E+'/unread','notifications/'+E])for(const method of ['GET','POST','DELETE','PATCH'])test('excluded '+method+route,()=>assert.equal(isAllowedApiRoute(method,route.split('/')),false));
test('append dedupes id preserves server ordering',()=>{const first=notification('EXTENSION_ACCEPTED',E),second=notification('COMMITMENT_CONFIRMED',A);assert.deepEqual(appendNotifications([first],[first,second]),[first,second]);});

for(const platform of ['web','mobile']){
 test(platform+' read only on activation, failure remains unread then authoritative read',async()=>{
 let reads=0,fail=true;const env={state:{status:'authenticated',user:{id:A}},session:{bootstrap:async()=>{},snapshot:()=>env.state},notifications:{listNotifications:async()=>({items:[notification()],next_cursor:null}),markRead:async()=>{reads++;if(fail)throw new Error('network');return {...notification(),read_at:'2026-10-02T00:00:00Z'};}}};
 const h=harness(platform,'notifications','useNotifications',env);h.render();await settle();assert.equal(reads,0);await h.render().activate(notification());assert.equal(h.render().data.items[0].read_at,null);fail=false;await h.render().activate(notification());assert.equal(h.render().data.items[0].read_at,'2026-10-02T00:00:00Z');assert.equal(reads,2);h.unmount();
 });
 test(platform+' pagination order failure preservation and refresh reset',async()=>{
 const calls=[];let fail=false;const env={state:{status:'authenticated',user:{id:A}},session:{},notifications:{listNotifications:async(options)=>{calls.push(options);if(fail)throw new Error('network');return options.cursor?{items:[notification('COMMITMENT_PROPOSED',A)],next_cursor:null}:{items:[notification('COMMITMENT_CONFIRMED',E)],next_cursor:'opaque'};}}};
 const h=harness(platform,'notifications','useNotifications',env);h.render();await settle();fail=true;await h.render().loadMore();assert.equal(h.render().data.next_cursor,'opaque');fail=false;await h.render().loadMore();assert.deepEqual(h.render().data.items.map(r=>r.id),[E,A]);await h.render().refresh();assert.deepEqual(calls.at(-1),{limit:50});assert.equal(h.render().data.items.length,1);h.unmount();
 });
}

test('actual F6 relay allowed methods, keys, query restrictions, safe headers',async t=>{
 const Module=require('node:module'),path=require('node:path'),old=Module._load;Module._load=function(r,p,m){return old.call(this,r.startsWith('@fides/shared/')?path.join(__dirname,'../shared',r.slice(14)+'.ts'):r,p,m);};let route;try{route=require('../web/app/api/v1/[...path]/route.ts');}finally{Module._load=old;}
 const before=process.env.FIDES_BACKEND_API_URL;process.env.FIDES_BACKEND_API_URL='http://127.0.0.1:8000/api/v1';const received=[];
 t.mock.method(global,'fetch',async(url,init)=>{received.push({url,init});assert.equal(init.headers.get('Cookie'),null);assert.equal(init.headers.get('X-Forwarded-For'),null);return Response.json({ok:true},{headers:{'Set-Cookie':'private'}});});
 try{
 for(const [method,endpoint,financial] of [['GET','notifications?limit=50&cursor=opaque',false],['POST','notifications/'+E+'/read',false],['PATCH','me',false],['POST','me/deactivate',false],['GET','commitments/'+ID+'/extension-requests',false],['POST','commitments/'+ID+'/extension-requests',true],['POST','extension-requests/'+E+'/accept',true],['POST','extension-requests/'+E+'/reject',true]]){
  const response=await route[method](new Request('http://localhost/api/v1/'+endpoint,{method,headers:{Authorization:'Bearer memory',Cookie:'private','X-Forwarded-For':'private','Idempotency-Key':'key-1'},...(method!=='GET'?{body:'{}'}:{})}),{params:Promise.resolve({path:endpoint.split('?')[0].split('/')})});
  assert.equal(response.status,200);assert.equal(response.headers.get('Cache-Control'),'no-store');assert.equal(response.headers.get('Set-Cookie'),null);assert.equal(received.at(-1).init.headers.get('Idempotency-Key'),financial?'key-1':null);
 }
 for(const [method,endpoint] of [['GET','notifications?offset=1'],['GET','commitments/'+ID+'/extension-requests?limit=1'],['PATCH','me?phone=bad'],['POST','me/deactivate?confirm=yes']]){
  const response=await route[method](new Request('http://localhost/api/v1/'+endpoint,{method}),{params:Promise.resolve({path:endpoint.split('?')[0].split('/')})});assert.equal(response.status,422);
 }
 assert.equal(received.length,8);
 }finally{if(before===undefined)delete process.env.FIDES_BACKEND_API_URL;else process.env.FIDES_BACKEND_API_URL=before;}
});
