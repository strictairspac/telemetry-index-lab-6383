#!/usr/bin/env python3
"""End-to-end verification for batch-managed telemetry samples.

Covers: idempotent import, same-batch/different-content rejection, bad-row and
duplicate-record whole-batch failure, import interruption recovery (real
SIGKILL), concurrent batch switch during a long trial, queued experiments
executing across batches, per-batch isolation of queries and write probes,
and reference-guarded cleanup of retired batches.

Runs against the locally started MySQL 8.0 / Redis / uvicorn / worker stack.
"""
import json,os,signal,subprocess,sys,time,urllib.request,urllib.error
from datetime import datetime,timedelta
import pymysql

API='http://127.0.0.1:19241'
DB=dict(host='127.0.0.1',port=17741,user='trial',password='trialpass',database='indextrial')
ENV=dict(os.environ,DATABASE_URL='mysql+pymysql://trial:trialpass@127.0.0.1:17741/indextrial',
         REDIS_URL='redis://127.0.0.1:16379/0',JWT_SECRET='test-secret',SEED_DEMO='false',
         PYTHONPATH='/workspace/backend')
LOG=open('/tmp/infra/uvicorn-verify.log','a')
PASSED=[]
def check(name,cond,detail=''):
    if cond:PASSED.append(name);print(f'  PASS {name}{(" — "+detail) if detail else ""}')
    else:print(f'  FAIL {name} {detail}');sys.exit(1)
def req(method,path,token=None,body=None):
    r=urllib.request.Request(API+path,method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
    try:
        with urllib.request.urlopen(r,timeout=120) as resp:return resp.status,json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:return e.code,json.loads(e.read())
        except Exception:return e.code,{}
def db(sql,args=None):
    with pymysql.connect(**DB) as c:
        with c.cursor() as cur:cur.execute(sql,args);rows=cur.fetchall()
        c.commit();return rows
def wait_health(timeout=30):
    t0=time.time()
    while time.time()-t0<timeout:
        try:
            with urllib.request.urlopen(API+'/health',timeout=2) as r:
                if r.status==200:return True
        except Exception:time.sleep(0.5)
    return False
def start_uvicorn():
    p=subprocess.Popen([sys.executable,'-m','uvicorn','src.main:app','--host','127.0.0.1','--port','19241'],
        cwd='/workspace/backend',env=ENV,stdout=LOG,stderr=LOG,start_new_session=True)
    if not wait_health():print('uvicorn failed to start');sys.exit(1)
    return p
def kill_uvicorn():
    subprocess.run(['pkill','-9','-f','uvicorn src.main'],check=False)
    t0=time.time()
    while time.time()-t0<15:
        try:urllib.request.urlopen(API+'/health',timeout=1);time.sleep(0.3)
        except Exception:return
    print('uvicorn did not stop');sys.exit(1)
def make_csv(sensor17_rows,total_rows):
    lines=['sensor_id,recorded_at,device_type,value'];base=datetime(2026,11,1)
    for k in range(sensor17_rows):lines.append(f"17,{(base+timedelta(hours=k)).isoformat()},pump,{40+k%10}.5")
    for k in range(total_rows-sensor17_rows):
        lines.append(f"{200+k%800},{(base+timedelta(minutes=k)).isoformat()},{['pump','motor','valve'][k%3]},{30+k%50}")
    return '\n'.join(lines)+'\n'
def wait_experiment(token,eid,timeout=60):
    t0=time.time()
    while time.time()-t0<timeout:
        s,e=req('GET',f'/experiments/{eid}',token)
        if e.get('status') in ('completed','failed'):return e
        time.sleep(1)
    print('experiment did not finish',e);sys.exit(1)

print('== setup: restart uvicorn under script control ==')
kill_uvicorn();UV=start_uvicorn()
print('== reset: clean prior verification state ==')
db("DELETE FROM experiments WHERE name LIKE 'verify-%'")
db("DELETE FROM sample_batches WHERE batch_no LIKE 'verify-%'")
db("UPDATE sample_batches SET status='active' WHERE table_name='telemetry'")
for (t,) in db("SELECT table_name FROM information_schema.tables WHERE table_schema='indextrial' AND table_name LIKE 'telemetry_batch\\_%'"):
    db(f'DROP TABLE IF EXISTS `{t}`')
subprocess.run(['/tmp/infra/redis-7.2.6/src/redis-cli','-p','16379','DEL','index-trials'],check=False,capture_output=True)
_,op=req('POST','/auth/login',body={'email':'operator@index.local','password':'Trial2026!'})
_,vw=req('POST','/auth/login',body={'email':'viewer@index.local','password':'Trial2026!'})
OP,VW=op['token'],vw['token']

print('== T0 authz ==')
s,_=req('GET','/samples');check('未登录读批次返回 401',s==401)
s,_=req('POST','/samples/import',VW,{'batch_no':'verify-b0','content':'sensor_id,recorded_at,device_type,value\n17,2026-11-01T00:00:00,pump,1'});check('viewer 导入返回 403',s==403)

print('== T1 整批导入并原子替换 ==')
B1=make_csv(40,200)
s,b=req('POST','/samples/import',OP,{'batch_no':'verify-b1','content':B1})
check('导入返回 200',s==200,str(b)[:200])
check('新批次生效',b.get('status')=='active' and b.get('row_count')==200,str(b))
check('非幂等标记',b.get('replayed')==False)
B1ID,B1TABLE=b['id'],b['table_name']
s,cur=req('GET','/samples/current',OP)
check('current 指向新批次',cur.get('batch_no')=='verify-b1')
rows=db('SELECT status FROM sample_batches WHERE batch_no=%s','seed-20261101')
check('种子批次已退役且表受保护',rows[0][0]=='retired',str(rows))
check('批次表行数精确',db(f'SELECT COUNT(*) FROM `{B1TABLE}`')[0][0]==200)

print('== T2 同批同内容幂等重试 ==')
s,b2=req('POST','/samples/import',OP,{'batch_no':'verify-b1','content':B1})
check('重试返回 200 且标记幂等',s==200 and b2.get('replayed')==True,str(b2)[:200])
check('重试不重复生效(仍 200 行)',db(f'SELECT COUNT(*) FROM `{B1TABLE}`')[0][0]==200)
check('批次记录只有一条',db('SELECT COUNT(*) FROM sample_batches WHERE batch_no=%s','verify-b1')[0][0]==1)

print('== T3 同批异内容拒绝 ==')
s,b3=req('POST','/samples/import',OP,{'batch_no':'verify-b1','content':make_csv(5,50)})
check('同批异内容返回 409',s==409,str(b3)[:120])
s,cur=req('GET','/samples/current',OP)
check('生效批次未被污染',cur.get('batch_no')=='verify-b1')

print('== T4 坏行使整批失败并保留旧版 ==')
bad=B1+f"17,not-a-time,pump,1\n"
s,b4=req('POST','/samples/import',OP,{'batch_no':'verify-bad','content':bad})
check('坏行返回 422',s==422,str(b4)[:120])
rows=db('SELECT status,error FROM sample_batches WHERE batch_no=%s','verify-bad')
check('失败批次留痕 failed',rows and rows[0][0]=='failed' and 'ISO' in (rows[0][1] or ''),str(rows))
s,cur=req('GET','/samples/current',OP)
check('旧版批次保留',cur.get('batch_no')=='verify-b1')
check('失败批次未建数据表',db("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='indextrial' AND table_name=(SELECT table_name FROM sample_batches WHERE batch_no='verify-bad')")[0][0]==0)

print('== T5 重复记录使整批失败 ==')
dup='sensor_id,recorded_at,device_type,value\n17,2026-11-01T00:00:00,pump,1\n17,2026-11-01T00:00:00,motor,2\n'
s,b5=req('POST','/samples/import',OP,{'batch_no':'verify-dup','content':dup})
check('重复记录返回 422',s==422 and '重复' in str(b5),str(b5)[:150])
s,cur=req('GET','/samples/current',OP)
check('旧版批次仍保留',cur.get('batch_no')=='verify-b1')

print('== T6 排队试验跨批执行 + 换批不等待长试验 + 引用释放前不清理 ==')
side=pymysql.connect(**DB)
with side.cursor() as cur_:cur_.execute("SELECT GET_LOCK('index_trial_serial',120)");assert cur_.fetchone()[0]==1
s,e1=req('POST','/experiments',OP,{'name':'verify-cross-batch','candidate_id':1})
check('试验创建成功',s==200,str(e1)[:200])
check('创建时绑定当前批次 verify-b1',e1.get('batch_no')=='verify-b1',str(e1)[:300])
time.sleep(2)  # worker 已领取并阻塞在试验锁上，模拟长试验
t0=time.time()
s,b6=req('POST','/samples/import',OP,{'batch_no':'verify-b2','content':make_csv(75,300)})
dt=time.time()-t0
check('长试验期间换批成功且未等待',s==200 and dt<25,f'{dt:.1f}s')
B2TABLE=b6['table_name']
check('换批后 current 为 verify-b2',req('GET','/samples/current',OP)[1].get('batch_no')=='verify-b2')
check('引用未释放，旧批次表未清理',db("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='indextrial' AND table_name=%s",B1TABLE)[0][0]==1)
rows=db('SELECT status FROM sample_batches WHERE id=%s',B1ID)
check('旧批次状态 retired(未清理)',rows[0][0]=='retired',str(rows))
with side.cursor() as cur_:cur_.execute("SELECT RELEASE_LOCK('index_trial_serial')")
side.close()
e1=wait_experiment(OP,e1['id'])
check('跨批试验完成',e1['status']=='completed',e1.get('error',''))
r=e1['result']
check('结果注明批次 verify-b1',r['batch']['batch_no']=='verify-b1',str(r['batch']))
check('查询落在原批次表',B1TABLE in r['query'] and r['before_plan'][0]['table']==B1TABLE,r['query'])
check('结果行数来自原批次(40)',r['rows']==40,str(r['rows']))
t0=time.time()
while time.time()-t0<20:
    if db('SELECT status FROM sample_batches WHERE id=%s',B1ID)[0][0]=='cleaned':break
    time.sleep(1)
check('引用释放后旧批次被清理',db('SELECT status FROM sample_batches WHERE id=%s',B1ID)[0][0]=='cleaned')
check('旧批次表已删除',db("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='indextrial' AND table_name=%s",B1TABLE)[0][0]==0)

print('== T7 前后查询与写探针均隔离 + 结果注明批次 ==')
s,e2=req('POST','/experiments',OP,{'name':'verify-isolation','candidate_id':1})
check('第二个试验绑定 verify-b2',e2.get('batch_no')=='verify-b2',str(e2)[:200])
e2=wait_experiment(OP,e2['id'])
r=e2['result']
check('结果注明批次 verify-b2',r['batch']['batch_no']=='verify-b2')
check('EXPLAIN 落在 verify-b2 表',r['before_plan'][0]['table']==B2TABLE and r['after_plan'][0]['table']==B2TABLE)
check('结果行数来自 verify-b2(75)',r['rows']==75,str(r['rows']))
ai_b2=db("SELECT auto_increment FROM information_schema.tables WHERE table_schema='indextrial' AND table_name=%s",B2TABLE)[0][0]
ai_seed=db("SELECT auto_increment FROM information_schema.tables WHERE table_schema='indextrial' AND table_name='telemetry'")[0][0]
check('写探针消耗了 verify-b2 的序列号',ai_b2 and ai_b2>301,f'auto_increment={ai_b2}')
check('写探针未触及其他批次表',ai_seed==5001,f'telemetry auto_increment={ai_seed}')
raw=urllib.request.Request(API+f"/experiments/{e2['id']}/export",headers={'Authorization':'Bearer '+OP})
with urllib.request.urlopen(raw) as resp:exported=resp.read().decode()
check('导出 JSON 注明批次','verify-b2' in exported and 'content_hash' in exported)

print('== T8 导入中断(SIGKILL)后可恢复，重试不重复生效 ==')
BIG=make_csv(0,100000)
import threading
def do_import():
    try:req('POST','/samples/import',OP,{'batch_no':'verify-big','content':BIG})
    except Exception:pass
th=threading.Thread(target=do_import);th.start()
t0=time.time();landed='before-load'
while time.time()-t0<30:
    rows=db("SELECT status,table_name FROM sample_batches WHERE batch_no='verify-big'")
    if rows:
        if db("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='indextrial' AND table_name=%s",rows[0][1])[0][0]:landed='during-load';break
        if time.time()-t0>8:break
    time.sleep(0.1)
kill_uvicorn()
rows=db("SELECT status,table_name FROM sample_batches WHERE batch_no='verify-big'")
check('中断后批次停留在 importing',rows and rows[0][0]=='importing',f'kill 落点:{landed} {rows}')
th.join(timeout=5)
UV=start_uvicorn()
t0=time.time()
s,b8=req('POST','/samples/import',OP,{'batch_no':'verify-big','content':BIG})
check('恢复重试成功并生效',s==200 and b8.get('status')=='active' and b8.get('row_count')==100000,f'{time.time()-t0:.1f}s {str(b8)[:160]}')
check('恢复后表行数精确(不重复)',db(f"SELECT COUNT(*) FROM `{b8['table_name']}`")[0][0]==100000)
check('批次记录仍只有一条',db("SELECT COUNT(*) FROM sample_batches WHERE batch_no='verify-big'")[0][0]==1)
s,b8r=req('POST','/samples/import',OP,{'batch_no':'verify-big','content':BIG})
check('恢复后再重试为幂等',s==200 and b8r.get('replayed')==True)
s,b8c=req('POST','/samples/import',OP,{'batch_no':'verify-big','content':make_csv(1,10)})
check('恢复后同批异内容仍拒绝',s==409)

print('== T9 并发同内容重试只生效一次 ==')
import concurrent.futures as cf
with cf.ThreadPoolExecutor(2) as ex:
    r1,r2=ex.map(lambda _:req('POST','/samples/import',OP,{'batch_no':'verify-conc','content':make_csv(3,50)}),range(2))
check('并发重试均 200',r1[0]==200 and r2[0]==200,f'{r1[0]},{r2[0]}')
flags=sorted([r1[1].get('replayed'),r2[1].get('replayed')])
check('恰好一次生效一次幂等',flags==[False,True],str(flags))
check('并发后只有一条批次记录',db("SELECT COUNT(*) FROM sample_batches WHERE batch_no='verify-conc'")[0][0]==1)

print(f'\nALL {len(PASSED)} CHECKS PASSED')
for p in PASSED:print('  -',p)
