"""GitHub Pages API. Bind to loopback; publish only through HTTPS tunnel."""
import os,json,secrets,hashlib,hmac,time,threading,queue,re
from pathlib import Path
from flask import Flask,request,jsonify,g
from werkzeug.exceptions import HTTPException
import store
RUNTIME=Path(os.environ.get('PROJECTHELPER_DATA',Path.home()/'.projecthelper')).resolve()
RUNTIME.mkdir(parents=True,exist_ok=True);RUNTIME.chmod(0o700)
store.DB=RUNTIME/'deployment.sqlite3'
store.initialize()
ORIGIN=os.environ.get('PROJECTHELPER_ORIGIN','https://miaelang.github.io')
MODEL=os.environ.get('PROJECTHELPER_MODEL','gemma3:12b')
app=Flask(__name__);app.config['MAX_CONTENT_LENGTH']=100000
Q=queue.Queue(maxsize=30);MUTEX=threading.RLock();LOGIN_LOCK=threading.Lock();ATTEMPTS={};NET_ATTEMPTS={}
with store.connect() as c:
 c.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,owner TEXT NOT NULL,request_id TEXT NOT NULL,status TEXT NOT NULL,message TEXT NOT NULL,answer TEXT,error TEXT,created TEXT NOT NULL,UNIQUE(owner,request_id))')
 c.execute("UPDATE jobs SET status='failed',error='서버가 재시작됐어요. 질문을 다시 보내주세요.' WHERE status IN ('queued','running')")
def fail(message,status=400):
 e=HTTPException(description=message);e.code=status;raise e
@app.errorhandler(HTTPException)
def error(e):return jsonify(error=e.description),e.code
@app.errorhandler(Exception)
def unexpected(e):return jsonify(error='요청 처리 중 오류가 발생했어요. 잠시 후 다시 시도하세요.'),500
@app.before_request
def security():
 if request.path=='/health':return
 if request.headers.get('Origin')!=ORIGIN:fail('허용된 웹앱에서 접속하세요.',403)
 if request.method=='OPTIONS':return '',204
@app.after_request
def headers(resp):
 if request.headers.get('Origin')==ORIGIN:
  resp.headers['Access-Control-Allow-Origin']=ORIGIN;resp.headers['Vary']='Origin'
  resp.headers['Access-Control-Allow-Methods']='GET, POST, OPTIONS'
  resp.headers['Access-Control-Allow-Headers']='Authorization, Content-Type'
  resp.headers['Access-Control-Max-Age']='600'
 resp.headers['Cache-Control']='no-store';resp.headers['X-Content-Type-Options']='nosniff';resp.headers['Referrer-Policy']='no-referrer'
 return resp
@app.get('/health')
def health():return jsonify(ok=True,service='ProjectHelper',version='1.0-pilot')
def bearer():
 value=request.headers.get('Authorization','')
 return value[7:] if value.startswith('Bearer ') else ''
def session(optional=False,change=False):
 token=bearer();digest=hashlib.sha256(token.encode()).hexdigest();stamp=time.time()
 with store.connect() as c:
  c.execute('DELETE FROM sessions WHERE last_seen<? OR created<?',(stamp-1800,stamp-28800))
  u=c.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND u.active=1',(digest,)).fetchone()
  if u:c.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?',(stamp,digest))
 if not u:
  if optional:return None
  fail('로그인이 만료됐어요. 다시 로그인하세요.',401)
 if u['must_change'] and not change:fail('임시 비밀번호를 먼저 변경하세요.',403)
 return u
def issue(uid):
 token=secrets.token_urlsafe(32);stamp=time.time()
 with store.connect() as c:c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,stamp,stamp))
 return jsonify(ok=True,access_token=token)
def teacher(u):
 if u['role']!='teacher':fail('교사 전용 기능입니다.',403)
def student(u,target):
 teacher(u)
 with store.connect() as c:r=c.execute("SELECT * FROM users WHERE id=? AND teacher_id=? AND role='student'",(target,u['id'])).fetchone()
 if not r:fail('담당 학생 계정이 없습니다.',404)
 return r
def owner(u):
 target=request.args.get('owner',u['id'])
 if target==u['id']:return target
 if target=='legacy':fail('이전 로컬 기록은 맥북의 기존 앱에서 확인하세요.',404)
 student(u,target);return target
def payload():
 b=request.get_json(silent=True)
 if not isinstance(b,dict):fail('입력을 확인하세요.')
 return b
def text(b,key,limit=16000):
 v=b.get(key,'')
 if not isinstance(v,str) or len(v)>limit:fail('입력 길이와 형식을 확인하세요.')
 return v
@app.get('/api/privacy')
def privacy():
 with store.connect() as c:return jsonify(dict(c.execute('SELECT key,value FROM settings').fetchall()))
@app.get('/api/me')
def me():
 u=session(optional=True,change=True);return jsonify(user=store.public_user(u) if u else None,setup_required=False)
@app.post('/api/login')
def login():
 b=payload();name=text(b,'username',64).strip();password=text(b,'password',128);stamp=time.time();key=hashlib.sha256(name.encode()).hexdigest()
 # Proxy injects this header. Stored only as a one-way, in-memory throttle key.
 net=hashlib.sha256(request.headers.get('CF-Connecting-IP',request.remote_addr).encode()).hexdigest()
 with LOGIN_LOCK:
  for buckets in (ATTEMPTS,NET_ATTEMPTS):
   for k in list(buckets):
    if buckets[k][1]<stamp:del buckets[k]
  if ATTEMPTS.get(key,(0,0))[0]>=5 or NET_ATTEMPTS.get(net,(0,0))[0]>=100:fail('로그인 시도가 많아요. 5분 뒤 다시 시도하세요.',429)
  if len(ATTEMPTS)>1000:fail('잠시 후 다시 시도하세요.',429)
  NET_ATTEMPTS[net]=(NET_ATTEMPTS.get(net,(0,0))[0]+1,stamp+300)
  with store.connect() as c:u=c.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
  hashed=store.password_hash(password,u['salt'] if u else store.DUMMY_SALT)
  if not u or not hmac.compare_digest(hashed,u['password_hash']) or not u['active']:
   ATTEMPTS[key]=(ATTEMPTS.get(key,(0,0))[0]+1,stamp+300);fail('ID 또는 비밀번호를 확인하세요.',401)
  ATTEMPTS.pop(key,None)
 return issue(u['id'])
@app.post('/api/logout')
def logout():
 with store.connect() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(bearer().encode()).hexdigest(),))
 return jsonify(ok=True)
@app.post('/api/password')
def password():
 u=session(change=True);b=payload();old=text(b,'old',128);new=text(b,'password',128)
 if not hmac.compare_digest(store.password_hash(old,u['salt']),u['password_hash']):fail('현재 비밀번호를 확인하세요.',403)
 if old==new or len(new)<12:fail('이전과 다른 12자 이상의 비밀번호를 입력하세요.')
 with store.connect() as c:store.set_password(c,u['id'],new,False);store.audit(c,u['id'],'password_changed')
 return issue(u['id'])
@app.get('/api/events')
def events():return jsonify(store.records(owner(session())))
@app.get('/api/status')
def status():
 session()
 try:
  installed=[m['name'] for m in store.ollama('/api/tags')['models']]
  return jsonify(models=[MODEL] if MODEL in installed else [],error=None if MODEL in installed else '교사 맥북의 모델 설치를 확인하세요.')
 except Exception:return jsonify(models=[],error='교사 맥북의 Ollama 연결을 확인하세요.')
@app.post('/api/note')
def note():
 u=session();b=payload();note=text(b,'note',12000);store.save(u['id'],'note',{'note':note});return jsonify(ok=True)
@app.get('/api/students')
def students():
 u=session();teacher(u)
 with store.connect() as c:
  rows=[dict(r) for r in c.execute("SELECT u.id,u.username,u.class_name,u.active,u.must_change,u.research_allowed,(SELECT MAX(time) FROM events WHERE owner_id=u.id) AS last_activity,(SELECT COUNT(*) FROM events WHERE owner_id=u.id AND kind='user') AS messages FROM users u WHERE teacher_id=? ORDER BY class_name,username",(u['id'],))]
  settings=dict(c.execute('SELECT key,value FROM settings').fetchall())
 return jsonify(students=rows,settings=settings)
@app.post('/api/students/create')
def create_students():
 u=session();teacher(u);b=payload();count=b.get('count');name=text(b,'class_name',40).strip()
 if type(count)!=int or not 1<=count<=100 or not name:fail('수업명과 1~100명의 인원을 입력하세요.')
 issued=[]
 with store.connect() as c:
  for _ in range(count):
   username='s-'+secrets.token_hex(4);password=secrets.token_urlsafe(12);uid=store.new_user(c,username,'student',password,u['id'],name)
   issued.append(dict(id=uid,username=username,temporary_password=password,class_name=name))
  store.audit(c,u['id'],'accounts_created',str(count))
 return jsonify(issued=issued)
@app.post('/api/students/<action>')
def change_student(action):
 u=session();b=payload();target=text(b,'id',64);s=student(u,target)
 with MUTEX,store.connect() as c:
  if action in ('delete','active') and c.execute("SELECT 1 FROM jobs WHERE owner=? AND status='running'",(target,)).fetchone():fail('이 학생의 AI 답변이 끝난 뒤 변경하세요.',409)
  if action=='reset':
   password=secrets.token_urlsafe(12);store.set_password(c,target,password,True);out={'temporary_password':password}
  elif action=='active':
   if type(b.get('active'))!=bool:fail('상태를 확인하세요.')
   c.execute('UPDATE users SET active=? WHERE id=?',(b['active'],target));c.execute('DELETE FROM sessions WHERE user_id=?',(target,));out={'ok':True}
  elif action=='research':
   if type(b.get('allowed'))!=bool:fail('상태를 확인하세요.')
   c.execute('UPDATE users SET research_allowed=? WHERE id=?',(b['allowed'],target));out={'ok':True}
  elif action=='delete':
   if b.get('confirmation')!=s['username']:fail('삭제할 ID를 정확히 입력하세요.')
   c.execute('DELETE FROM jobs WHERE owner=?',(target,));c.execute('DELETE FROM events WHERE owner_id=?',(target,));c.execute('DELETE FROM users WHERE id=?',(target,));c.execute('UPDATE audit SET target=NULL WHERE target=?',(target,));target=None;out={'ok':True}
  else:fail('없는 기능입니다.',404)
  store.audit(c,u['id'],'student_'+action,target)
 return jsonify(out)
@app.post('/api/settings')
def settings():
 u=session();teacher(u);b=payload();date=text(b,'retention_date',10);contact=text(b,'contact',200)
 if date:
  try:store.datetime.strptime(date,'%Y-%m-%d')
  except ValueError:fail('날짜를 확인하세요.')
 with store.connect() as c:
  for k,v in [('retention_date',date),('contact',contact)]:c.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,v))
  store.audit(c,u['id'],'retention_plan_updated')
 return jsonify(ok=True)
@app.get('/api/research')
def research():
 u=session();teacher(u)
 with store.connect() as c:
  rows=c.execute('SELECT e.id,e.time,e.kind,e.payload,u.research_id FROM events e JOIN users u ON e.owner_id=u.id WHERE u.teacher_id=? AND u.research_allowed=1 ORDER BY e.id',(u['id'],)).fetchall();store.audit(c,u['id'],'research_export')
 return jsonify([dict(r)|{'payload':json.loads(r['payload'])} for r in rows])
@app.post('/api/chat')
def chat():
 u=session();b=payload();message=text(b,'message').strip();rid=text(b,'request_id',64)
 if not message or not re.fullmatch('[a-zA-Z0-9-]{16,64}',rid):fail('질문과 요청 번호를 확인하세요.')
 with MUTEX:
  with store.connect() as c:
   previous=c.execute('SELECT id FROM jobs WHERE owner=? AND request_id=?',(u['id'],rid)).fetchone()
   if previous:return jsonify(job_id=previous['id'])
   if c.execute("SELECT 1 FROM jobs WHERE owner=? AND status IN ('queued','running')",(u['id'],)).fetchone():fail('이미 보낸 질문에 답변하는 중이에요.',409)
   if Q.full():fail('대기 중인 질문이 많아요. 잠시 뒤 다시 시도하세요.',429)
   jid=secrets.token_hex(16)
   c.execute('INSERT INTO jobs(id,owner,request_id,status,message,created) VALUES(?,?,?,?,?,?)',(jid,u['id'],rid,'queued',message,store.now()))
   c.execute('INSERT INTO events(time,kind,payload,owner_id) VALUES(?,?,?,?)',(store.now(),'user',json.dumps({'text':message,'model':MODEL,'prompt_version':store.PROMPT_VERSION,'request_id':rid},ensure_ascii=False),u['id']))
  # DB commit must precede worker notification.
  Q.put_nowait(jid)
 return jsonify(job_id=jid),202
@app.get('/api/jobs/active')
def active_job():
 u=session()
 with store.connect() as c:r=c.execute("SELECT id FROM jobs WHERE owner=? AND status IN ('queued','running') ORDER BY created DESC LIMIT 1",(u['id'],)).fetchone()
 return jsonify(job_id=r['id'] if r else None)
@app.get('/api/jobs/<jid>')
def job(jid):
 u=session()
 with store.connect() as c:
  r=c.execute('SELECT * FROM jobs WHERE id=? AND owner=?',(jid,u['id'])).fetchone()
  if not r:fail('질문을 찾을 수 없습니다.',404)
  position=c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') AND created<=?",(r['created'],)).fetchone()[0]
 return jsonify(status=r['status'],answer=r['answer'],error=r['error'],position=position)
def worker():
 while True:
  jid=Q.get()
  try:
   with MUTEX,store.connect() as c:
    row=c.execute('SELECT j.* FROM jobs j JOIN users u ON j.owner=u.id WHERE j.id=? AND u.active=1',(jid,)).fetchone()
    if not row:
     c.execute("UPDATE jobs SET status='failed',error='계정이 중지됐어요.' WHERE id=?",(jid,));continue
    c.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
   records=store.records(row['owner']);notes=[r['payload']['note'] for r in records if r['kind']=='note'];history=[]
   for r in records:
    if r['kind'] in ('user','assistant'):history.append({'role':r['kind'],'content':r['payload']['text']})
   msgs=[{'role':'system','content':store.PROMPT}]
   if notes:msgs.append({'role':'user','content':'참고용 프로젝트 메모:\n'+notes[-1]})
   result=store.ollama('/api/chat',{'model':MODEL,'messages':msgs+history[-9:],'stream':False,'options':{'temperature':0.3,'num_ctx':8192,'num_predict':700}},240)
   answer=result['message']['content']
   if not answer:raise ValueError('empty')
   with MUTEX:
    store.save(row['owner'],'assistant',{'text':answer,'model':MODEL,'prompt_version':store.PROMPT_VERSION,'duration_ns':result.get('total_duration'),'job_id':jid})
    with store.connect() as c:c.execute("UPDATE jobs SET status='done',answer=? WHERE id=?",(answer,jid))
  except Exception:
   with store.connect() as c:c.execute("UPDATE jobs SET status='failed',error='AI 답변에 실패했어요. 잠시 뒤 다시 시도하세요.' WHERE id=?",(jid,))
  finally:Q.task_done()
if __name__=='__main__':
 from waitress import serve
 threading.Thread(target=worker,daemon=True).start()
 print('ProjectHelper API: 127.0.0.1:8877 (no public signup)',flush=True)
 serve(app,host='127.0.0.1',port=int(os.environ.get('PROJECTHELPER_PORT','8877')),threads=8,channel_timeout=30,ident='ProjectHelper')
