"""Sample batch CSV parsing. Pure stdlib so it can be verified without the app stack.

Every row is validated before anything is loaded: any bad row or duplicate
record fails the whole batch and the caller keeps the previous version.
"""
import csv,hashlib,io,math
from datetime import datetime
HEADER=('sensor_id','recorded_at','device_type','value')
DEVICES=('pump','motor','valve')
MAX_ROWS=100000
def content_hash(content):
 return hashlib.sha256(content.encode()).hexdigest()
def parse(content):
 """Return validated rows as dicts. Raise ValueError on the first bad row or duplicate."""
 if not content or not content.strip():raise ValueError('文件内容为空')
 reader=csv.reader(io.StringIO(content.lstrip('\ufeff')))
 try:header=next(reader)
 except StopIteration:raise ValueError('文件内容为空')
 if [c.strip() for c in header]!=list(HEADER):raise ValueError('表头必须为 '+','.join(HEADER))
 rows=[];seen=set()
 for lineno,raw in enumerate(reader,start=2):
  if not raw or all(not c.strip() for c in raw):continue
  if len(raw)!=len(HEADER):raise ValueError(f'第{lineno}行列数应为{len(HEADER)}，实际{len(raw)}')
  sensor,recorded,device,value=(c.strip() for c in raw)
  try:sensor=int(sensor)
  except ValueError:raise ValueError(f'第{lineno}行 sensor_id 不是整数：{sensor}')
  if not 1<=sensor<=1000:raise ValueError(f'第{lineno}行 sensor_id 超出 1..1000：{sensor}')
  try:recorded=datetime.fromisoformat(recorded)
  except ValueError:raise ValueError(f'第{lineno}行 recorded_at 不是 ISO 时间：{recorded}')
  if recorded.tzinfo is not None:raise ValueError(f'第{lineno}行 recorded_at 不应带时区（样本为本地时间）')
  recorded=recorded.isoformat(timespec='seconds')
  if device not in DEVICES:raise ValueError(f'第{lineno}行 device_type 无效：{device}')
  try:value=float(value)
  except ValueError:raise ValueError(f'第{lineno}行 value 不是数值：{value}')
  if not math.isfinite(value):raise ValueError(f'第{lineno}行 value 不是有限数值')
  key=(sensor,recorded)
  if key in seen:raise ValueError(f'第{lineno}行与前面记录重复：sensor_id={key[0]} recorded_at={key[1]}')
  seen.add(key)
  rows.append({'sensor_id':sensor,'recorded_at':recorded,'device_type':device,'value':value})
  if len(rows)>MAX_ROWS:raise ValueError(f'行数超过上限 {MAX_ROWS}')
 if not rows:raise ValueError('文件没有任何数据行')
 return rows
