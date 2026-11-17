import redis
from fastapi import HTTPException
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models.workload import Workload
from src.models.candidate import Candidate
from src.models.experiment import Experiment
from src.models.sample_batch import SampleBatch
from src.utils.serialization import record
queue=redis.Redis.from_url(REDIS_URL)
def _enrich(s,rows):
 ids={r.batch_id for r in rows if r.batch_id}
 names={b.id:b.batch_no for b in s.query(SampleBatch).filter(SampleBatch.id.in_(ids))} if ids else {}
 return [dict(record(r),batch_no=names.get(r.batch_id)) for r in rows]
def list_items():
 with Session() as s:return _enrich(s,s.query(Experiment).order_by(Experiment.id.desc()).limit(100).all())
def detail(item_id):
 with Session() as s:
  row=s.get(Experiment,item_id)
  if not row:raise HTTPException(404,'未找到试验')
  return _enrich(s,[row])[0]
def create(data):
 with Session() as s:
  c=s.get(Candidate,data.candidate_id)
  if not c:raise HTTPException(404,'未找到候选')
  w=s.get(Workload,c.workload_id)
  b=s.query(SampleBatch).filter_by(status='active').first()
  if not b:raise HTTPException(503,'当前没有生效的样本批次，请先导入样本')
  snap={'workload':record(w),'candidate':record(c),'batch':{'id':b.id,'batch_no':b.batch_no,'content_hash':b.content_hash,'row_count':b.row_count,'table_name':b.table_name}}
  row=Experiment(name=data.name,candidate_id=c.id,workload_id=w.id,batch_id=b.id,status='queued',snapshot=snap)
  s.add(row);s.commit();s.refresh(row);result=_enrich(s,[row])[0]
 try:queue.rpush('index-trials',result['id'])
 except redis.RedisError:
  with Session() as s:r=s.get(Experiment,result['id']);r.status='failed';r.error='队列不可用，请创建新试验';s.commit()
  raise HTTPException(503,'队列不可用，请稍后重新执行')
 return result
