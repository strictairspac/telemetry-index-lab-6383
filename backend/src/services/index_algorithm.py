"""Controlled MySQL index trial. All dynamic identifiers are server-whitelisted."""
import hashlib,json,re,time,statistics
from sqlalchemy import text
from src.config.database import engine
from src.constants.enums import COLUMNS
TABLE_RE=re.compile(r'^telemetry(_batch_\d+)?$')
def prefix_score(columns,w):
 equality={'sensor_id'}|({'device_type'} if w.get('device_type') else set())
 score=0;matched=[];reason=[]
 for col in columns:
  if col in equality:score+=40;matched.append(col);reason.append(f'{col}: equality prefix +40')
  elif col=='recorded_at':score+=20;matched.append(col);reason.append('recorded_at: range +20; following columns cannot extend lookup');break
  else:reason.append(f'{col}: unmatched prefix stops lookup');break
 return {'score':min(100,score),'matched_prefix':matched,'reason':reason,'formula':'equality prefix +40/column, first range +20, max 100; heuristic only'}
def _timed(conn,query,params):
 samples=[];rows=[]
 for _ in range(5):
  start=time.perf_counter();rows=[dict(r) for r in conn.execute(text(query),params).mappings()];samples.append((time.perf_counter()-start)*1000)
 return rows,round(statistics.median(samples),4),[round(x,4) for x in samples]
def _write_probe(conn,table):
 t=time.perf_counter()
 conn.execute(text(f"INSERT INTO `{table}`(sensor_id,recorded_at,device_type,value) VALUES (999,'2026-11-17T12:00:00','pump',42.5)"),[{} for _ in range(20)])
 elapsed=(time.perf_counter()-t)*1000;conn.rollback();return round(elapsed,4)
def run(snapshot):
 w=snapshot['workload'];columns=snapshot['candidate']['columns']
 if not columns or any(c not in COLUMNS for c in columns) or len(set(columns))!=len(columns):raise ValueError('invalid index columns')
 batch=snapshot.get('batch') or {}
 table=batch.get('table_name') or 'telemetry'
 if not TABLE_RE.fullmatch(table):raise ValueError('invalid sample table')
 params={'sensor':w['sensor_id'],'start':w['start_at'],'end':w['end_at']}
 query=f'SELECT id,sensor_id,recorded_at,device_type,value FROM `{table}` WHERE sensor_id=:sensor AND recorded_at>=:start AND recorded_at<=:end'
 if w.get('device_type'):query+=' AND device_type=:device';params['device']=w['device_type']
 query+=' ORDER BY id'
 with engine.connect() as conn:
  if conn.execute(text("SELECT GET_LOCK('index_trial_serial',30)")).scalar()!=1:raise RuntimeError('another trial holds lock')
  try:
   existing=conn.execute(text("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=:t AND index_name='trial_candidate'"),{'t':table}).scalar()
   if existing:conn.execute(text(f'DROP INDEX trial_candidate ON `{table}`'));conn.commit()
   before=[dict(r) for r in conn.execute(text('EXPLAIN '+query),params).mappings()]
   rows,before_ms,before_samples=_timed(conn,query,params)
   write_before=_write_probe(conn,table)
   conn.execute(text(f'CREATE INDEX trial_candidate ON `{table}` ('+','.join('`'+c+'`' for c in columns)+')'));conn.commit()
   conn.execute(text(f'ANALYZE TABLE `{table}`')).all()
   after=[dict(r) for r in conn.execute(text('EXPLAIN '+query),params).mappings()]
   result,after_ms,after_samples=_timed(conn,query,params)
   write_after=_write_probe(conn,table)
   canonical=lambda records:hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()
   return {'batch':{'id':batch.get('id'),'batch_no':batch.get('batch_no'),'content_hash':batch.get('content_hash'),'row_count':batch.get('row_count')},'prefix':prefix_score(columns,w),'query':query,'parameters':params,'rows':len(result),'before_plan':before,'after_plan':after,'before_median_ms':before_ms,'after_median_ms':after_ms,'before_samples_ms':before_samples,'after_samples_ms':after_samples,'insert20_before_ms':write_before,'insert20_after_ms':write_after,'equal_results':canonical(rows)==canonical(result),'checksum':canonical(result),'preview':result[:10],'limitations':[f"{batch.get('row_count') or '5000'}-row sample batch {batch.get('batch_no') or 'seed'}; timings include Python driver and cache effects",'20-row write probe is rolled back; sequence gaps are normal','heuristic prefix score is not MySQL optimizer cost; no guaranteed speedup']}
  finally:
   conn.rollback()
   try:
    exists=conn.execute(text("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=:t AND index_name='trial_candidate'"),{'t':table}).scalar()
    if exists:conn.execute(text(f'DROP INDEX trial_candidate ON `{table}`'));conn.commit()
   finally:conn.execute(text("SELECT RELEASE_LOCK('index_trial_serial')"));conn.commit()
