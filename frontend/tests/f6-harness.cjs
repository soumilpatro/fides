const fs=require('node:fs'),path=require('node:path'),ts=require('typescript'),Module=require('node:module');
require.extensions['.ts']=(m,f)=>m._compile(ts.transpileModule(fs.readFileSync(f,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,f);
const A='00000000-0000-4000-8000-000000000001',B='00000000-0000-4000-8000-000000000002',ID='00000000-0000-4000-8000-000000000003',E='00000000-0000-4000-8000-000000000004';
const me=()=>({id:A,phone_e164:'+12025550101',display_name:'Riya',timezone:'Etc/UTC',status:'ACTIVE',created_at:'2026-01-01T00:00:00Z',updated_at:'2026-01-01T00:00:00Z'});
const parent=()=>({id:ID,borrower:{id:A,display_name:'Riya'},lender:{id:B,display_name:'Morgan'},status:'ACTIVE'});
const terms=()=>({current_terms_version_id:E,versions:[{id:E,schedule_mode:'single',due_date:'2026-12-01'}]});
const extension=(status='REQUESTED')=>({id:E,commitment_id:ID,requested_by:{id:A,display_name:'Riya'},status,base_terms_version_id:E,previous_due_date:'2026-12-01',requested_due_date:'2027-01-01',reason:null,decided_by:['ACCEPTED','REJECTED'].includes(status)?{id:B,display_name:'Morgan'}:null,decided_at:['ACCEPTED','REJECTED'].includes(status)?'2026-10-01T00:00:00Z':null,created_at:'2026-09-01T00:00:00Z'});
const notification=(type='COMMITMENT_PROPOSED',id=E)=>({id,type,actor:{id:B,display_name:'Morgan'},commitment_id:ID,repayment_id:type.startsWith('REPAYMENT_')?A:null,extension_request_id:type.startsWith('EXTENSION_')?E:null,created_at:'2026-10-01T00:00:00Z',read_at:null});
function harness(platform,feature,name,env){
 let index=0,slots=[],effects=[],cleanups=[];const deps=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
 const react={useState(initial){const i=index++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return[slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},useRef(initial){const i=index++;return slots[i]??(slots[i]={current:initial});},useCallback(fn,d){const i=index++;if(!slots[i]||!deps(slots[i].d,d))slots[i]={fn,d};return slots[i].fn;},useEffect(fn,d){const i=index++;if(!slots[i]||!deps(slots[i].d,d)){slots[i]={d};effects.push(()=>{cleanups[i]?.();cleanups[i]=fn();});}}};
 const old=Module._load;Module._load=function(r,p,m){if(r==='react')return react;if(r==='../auth/useAuth')return{useAuth:()=>env};return old.call(this,r.startsWith('@fides/shared/')?path.join(__dirname,'../shared',r.slice(14)+'.ts'):r,p,m);};
 const file=require.resolve('../'+platform+'/features/'+feature+'/'+name+'.ts');let hook;try{delete require.cache[file];hook=require(file)[name];}finally{Module._load=old;delete require.cache[file];}
 return{render(...args){index=0;const result=hook(...args);while(effects.length)effects.shift()();return result;},unmount:()=>cleanups.forEach(fn=>fn?.())};
}
module.exports={A,B,ID,E,me,parent,terms,extension,notification,harness,settle:()=>new Promise(setImmediate)};
