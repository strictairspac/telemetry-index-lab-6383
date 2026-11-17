"""Sample batch lifecycle: idempotent import, atomic activation, lazy cleanup.

Each batch lives in its own table (telemetry_batch_<id>; the seeded 5,000-row
dataset stays in `telemetry`). A new batch is fully validated and loaded into
its staging table before a single metadata transaction retires the old active
batch and activates the new one, so a failed or interrupted import never
touches the batch experiments are using. Retired tables are dropped only once
no queued/running experiment references them.
"""
import logging
from datetime import datetime
from sqlalchemy import text
from fastapi import HTTPException
from src.config.database import Session,engine
from src.models.sample_batch import SampleBatch
from src.models.experiment import Experiment
from src.services import sample_io
from src.utils.serialization import record
IMPORT_LOCK='sample_batch_import'
DDL='(`id` INT PRIMARY KEY AUTO_INCREMENT,`sensor_id` INT NOT NULL,`recorded_at` VARCHAR(30) NOT NULL,`device_type` VARCHAR(40) NOT NULL,`value` FLOAT NOT NULL)'
def list_items():
 with Session() as s:return [record(r) for r in s.query(SampleBatch).order_by(SampleBatch.id.desc()).all()]
def current():
 with Session() as s:
  row=s.query(SampleBatch).filter_by(status='active').first()
  if not row:raise HTTPException(404,'当前没有生效的样本批次')
  return record(row)
def _mark_failed(batch_id,message):
 with Session() as s:
  b=s.get(SampleBatch,batch_id)
  if b and b.status=='importing':b.status='failed';b.error=message[:1000];s.commit()
def _load(table,rows):
 with engine.begin() as c:
  c.execute(text(f'DROP TABLE IF EXISTS `{table}`'))
  c.execute(text(f'CREATE TABLE `{table}` {DDL}'))
  c.execute(text(f'INSERT INTO `{table}` (sensor_id,recorded_at,device_type,value) VALUES (:sensor_id,:recorded_at,:device_type,:value)'),rows)
def _activate(batch_id,row_count):
 """Atomically replace the active batch. Runs in one metadata transaction."""
 with Session() as s:
  for old in s.query(SampleBatch).filter_by(status='active'):old.status='retired'
  b=s.get(SampleBatch,batch_id);b.status='active';b.row_count=row_count;b.error=None;b.activated_at=datetime.now()
  s.commit();s.refresh(b);return record(b)
def cleanup_retired():
 """Drop retired batch tables whose experiment references have been released."""
 with Session() as s:
  referenced={r[0] for r in s.query(Experiment.batch_id).filter(Experiment.batch_id.isnot(None),Experiment.status.in_(('queued','running')))}
  droppable=[b for b in s.query(SampleBatch).filter_by(status='retired') if b.id not in referenced and b.table_name.startswith('telemetry_batch_')]
 for b in droppable:
  try:
   with engine.begin() as c:c.execute(text(f'DROP TABLE IF EXISTS `{b.table_name}`'))
   with Session() as s:row=s.get(SampleBatch,b.id);row.status='cleaned';s.commit()
  except Exception:logging.exception('cleanup of batch table %s failed',b.table_name)
 return len(droppable)
def import_batch(data):
 digest=sample_io.content_hash(data.content)
 with engine.connect() as lock:
  if lock.execute(text('SELECT GET_LOCK(:name,30)'),{'name':IMPORT_LOCK}).scalar()!=1:raise HTTPException(409,'另一个样本导入正在进行，请稍后重试')
  try:
   with Session() as s:
    batch=s.query(SampleBatch).filter_by(batch_no=data.batch_no).first()
    if batch and batch.content_hash!=digest:raise HTTPException(409,'批次号已存在但文件内容不同，已拒绝；重试请使用原批次文件，换内容请用新批次号')
    if batch and batch.status in ('active','retired','cleaned'):return dict(record(batch),replayed=True)
    if not batch:
     batch=SampleBatch(batch_no=data.batch_no,content_hash=digest,status='importing')
     s.add(batch);s.flush();batch.table_name=f'telemetry_batch_{batch.id}'
    else:batch.status='importing';batch.error=None
    s.commit();batch_id,table=batch.id,batch.table_name
   try:rows=sample_io.parse(data.content)
   except ValueError as exc:
    _mark_failed(batch_id,str(exc))
    raise HTTPException(422,f'样本校验失败，整批未导入，当前批次保持不变：{exc}')
   try:_load(table,rows)
   except Exception as exc:
    _mark_failed(batch_id,'数据装载失败：'+str(exc)[:800])
    raise
   result=_activate(batch_id,len(rows))
  finally:
   try:lock.execute(text("SELECT RELEASE_LOCK(:name)"),{'name':IMPORT_LOCK})
   except Exception:logging.exception('release of %s failed',IMPORT_LOCK)
 try:cleanup_retired()
 except Exception:logging.exception('batch cleanup failed')
 return dict(result,replayed=False)
