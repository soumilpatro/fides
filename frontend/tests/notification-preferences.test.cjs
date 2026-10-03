const fs=require('node:fs'),ts=require('typescript');
require.extensions['.ts']=(m,f)=>m._compile(ts.transpileModule(fs.readFileSync(f,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,f);
const test=require('node:test'),assert=require('node:assert/strict');
const {createNotificationPreferencesApi,notificationPreferencesResponse}=require('../shared/api/notification-preferences.ts');
const {isAllowedApiRoute,isAllowedApiQuery}=require('../shared/api/relay.ts');

test('notification preference decoder requires exact booleans',()=>{
 assert.deepEqual(notificationPreferencesResponse({due_reminders_enabled:true,overdue_reminders_enabled:false}),{due_reminders_enabled:true,overdue_reminders_enabled:false});
 for(const value of [
  {due_reminders_enabled:1,overdue_reminders_enabled:false},
  {due_reminders_enabled:true,overdue_reminders_enabled:'false'},
  {due_reminders_enabled:true},
 ])assert.throws(()=>notificationPreferencesResponse(value));
});

test('notification preferences GET and replacement POST use authoritative response',async()=>{
 const calls=[];
 const api=createNotificationPreferencesApi({baseUrl:'https://fides.example/api/v1',fetcher:async(url,init)=>{
  calls.push({url,method:init.method,body:init.body,key:init.headers.get('Idempotency-Key')});
  if(init.method==='GET')return Response.json({due_reminders_enabled:true,overdue_reminders_enabled:false});
  assert.equal(init.body,JSON.stringify({due_reminders_enabled:false,overdue_reminders_enabled:true}));
  return Response.json({due_reminders_enabled:false,overdue_reminders_enabled:true});
 }});
 assert.deepEqual(await api.getPreferences(),{due_reminders_enabled:true,overdue_reminders_enabled:false});
 assert.deepEqual(await api.updatePreferences({due_reminders_enabled:false,overdue_reminders_enabled:true}),{due_reminders_enabled:false,overdue_reminders_enabled:true});
 assert.equal(calls[0].key,null);assert.equal(calls[1].key,null);
});

test('relay allows only GET/POST preferences with no query',()=>{
 assert.equal(isAllowedApiRoute('GET',['notification-preferences']),true);
 assert.equal(isAllowedApiRoute('POST',['notification-preferences']),true);
 assert.equal(isAllowedApiRoute('PATCH',['notification-preferences']),false);
 assert.equal(isAllowedApiQuery(['notification-preferences'],new URLSearchParams()),true);
 assert.equal(isAllowedApiQuery(['notification-preferences'],new URLSearchParams('x=1')),false);
});
