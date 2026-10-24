import os,sys,tempfile,threading,uuid,time
from pathlib import Path
os.environ['PROJECTHELPER_DATA']=tempfile.mkdtemp()
sys.path.insert(0,str(Path(__file__).resolve().parent))
import server as s
c=s.app.test_client();origin={'Origin':s.ORIGIN}
with s.store.connect() as db:
 t=s.store.new_user(db,'teacher','teacher','teacher-pass-123')
 a=s.store.new_user(db,'student-a','student','student-pass-123',t)
 b=s.store.new_user(db,'student-b','student','student-pass-123',t)
 s.store.set_password(db,b,'student-pass-123',False)
def login(name):
 r=c.post('/api/login',json={'username':name,'password':'student-pass-123'},headers=origin);assert r.status_code==200,r.json
 return origin|{'Authorization':'Bearer '+r.json['access_token']}
ha=login('student-a');hb=login('student-b')
assert c.get('/api/events',headers=ha).status_code==403
r=c.post('/api/password',json={'old':'student-pass-123','password':'changed-password-123'},headers=ha);assert r.status_code==200
ha=origin|{'Authorization':'Bearer '+r.json['access_token']}
assert c.get('/api/events?owner='+b,headers=ha).status_code==403
assert c.get('/api/events',headers=origin).status_code==401
assert c.get('/api/events',headers={'Origin':'https://evil.example'}).status_code==403
assert c.post('/api/students/create',json={'count':1,'class_name':'x'},headers=ha).status_code==403
assert c.post('/api/note',json={'note':'test note'},headers=ha).status_code==200
assert c.get('/api/events',headers=hb).json==[]
s.store.ollama=lambda *a,**k:{'message':{'content':'어떤 의견을 모으고 싶어?'}}
threading.Thread(target=s.worker,daemon=True).start()
body={'message':'급식 의견','request_id':str(uuid.uuid4())}
r=c.post('/api/chat',json=body,headers=ha);assert r.status_code==202,r.json
jid=r.json['job_id'];assert c.post('/api/chat',json=body,headers=ha).json['job_id']==jid
s.Q.join();assert c.get('/api/jobs/'+jid,headers=ha).json['status']=='done'
assert c.get('/api/jobs/'+jid,headers=hb).status_code==404
assert len(c.get('/api/events',headers=ha).json)==3
c.post('/api/logout',json={},headers=ha);assert c.get('/api/events',headers=ha).status_code==401
print('PASS: password rotation, owner isolation, teacher authorization, origin restriction, saved notes/chat, queue idempotency, logout')
