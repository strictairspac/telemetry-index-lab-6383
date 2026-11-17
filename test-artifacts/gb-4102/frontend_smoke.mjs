// Frontend smoke test: render every page with a populated store under a DOM stub.
const noop=()=>{};
const el=new Proxy(noop,{get:(t,k)=>{
  if(k==='value'||k==='innerHTML'||k==='textContent'||k==='className')return '';
  if(k==='dataset'||k==='style'||k==='elements'||k==='classList')return {};
  return el;
},set:()=>true,apply:()=>el});
global.document={getElementById:()=>el,querySelectorAll:()=>[],querySelector:()=>null,createElement:()=>el,addEventListener:noop,hidden:true,body:el};
global.sessionStorage={getItem:()=>null,setItem:noop,removeItem:noop};
global.fetch=async()=>({ok:true,status:200,json:async()=>({}),blob:async()=>({})});
global.setInterval=()=>0;global.clearInterval=noop;
global.URL={createObjectURL:()=>'',revokeObjectURL:noop};
global.FormData=class{};
const {store}=await import('/workspace/frontend/src/stores/business.js');
store.user={email:'operator@index.local',role:'operator'};
store.workloads=[{id:1,name:'泵站17温升排查',sensor_id:17,start_at:'2026-11-01T00:00:00',end_at:'2026-11-30T23:59:59',device_type:null,description:''}];
store.candidates=[{id:1,name:'传感器优先复合索引',workload_id:1,columns:['sensor_id','recorded_at'],note:''}];
store.samples=[
 {id:2,batch_no:'verify-b2',content_hash:'9545382591412ebbf',row_count:300,status:'active',table_name:'telemetry_batch_2',error:null,activated_at:'2026-11-17T12:00:00',created_at:'2026-11-17T12:00:00'},
 {id:1,batch_no:'seed-20261101',content_hash:'09a9d7e04a5d',row_count:5000,status:'retired',table_name:'telemetry',error:null,activated_at:'2026-11-17T11:00:00',created_at:'2026-11-17T11:00:00'},
 {id:3,batch_no:'verify-bad',content_hash:'ffff',row_count:0,status:'failed',table_name:'telemetry_batch_3',error:'第202行 recorded_at 不是 ISO 时间',activated_at:null,created_at:'2026-11-17T12:30:00'}];
store.experiments=[{id:1,name:'verify-isolation',status:'completed',created_at:'2026-11-17T12:40:00',batch_no:'verify-b2',error:null,snapshot:{batch:{batch_no:'verify-b2'}},
 result:{batch:{id:2,batch_no:'verify-b2',row_count:300,content_hash:'9545382591412ebbf'},prefix:{score:100,matched_prefix:['sensor_id'],reason:['sensor_id: equality prefix +40'],formula:'f'},rows:75,equal_results:true,before_median_ms:1.2,after_median_ms:0.8,before_plan:[{type:'ALL',key:null,rows:300,table:'telemetry_batch_2'}],after_plan:[{type:'ref',key:'trial_candidate',rows:75,table:'telemetry_batch_2'}],insert20_before_ms:3,insert20_after_ms:4,checksum:'deadbeef',query:'SELECT 1',parameters:{sensor:17},preview:[]}}];
for(const p of ['workloads','candidates','experiments','results','samples']){
  const m=await import(`/workspace/frontend/src/pages/${p}.js`);
  const fn=Object.values(m)[0];
  const html=fn(p==='results'?1:undefined);
  if(typeof html!=='string'||html.length<200)throw new Error(p+' render too small: '+String(html).slice(0,80));
  console.log('RENDER OK',p,html.length,'chars');
}
const {samplesPage}=await import('/workspace/frontend/src/pages/samples.js');
const sh=samplesPage();
if(!sh.includes('verify-b2')||!sh.includes('当前生效')||!sh.includes('导入失败')||!sh.includes('第202行'))throw new Error('samples page missing batch states');
const {experimentsPage}=await import('/workspace/frontend/src/pages/experiments.js');
const eh=experimentsPage();
if(!eh.includes('verify-b2')||!eh.includes('样本批次'))throw new Error('experiments page missing batch column/binding');
const {resultsPage}=await import('/workspace/frontend/src/pages/results.js');
const rh=resultsPage(1);
if(!rh.includes('样本批次')||!rh.includes('verify-b2')||!rh.includes('300'))throw new Error('results page missing batch evidence');
console.log('FRONTEND SMOKE OK');
