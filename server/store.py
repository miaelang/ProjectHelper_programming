"""Local pilot: account isolation. Not a production HTTP deployment."""
import hashlib, hmac, json, re, secrets, sqlite3, threading, time, urllib.request
from pathlib import Path
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
ROOT=Path(__file__).resolve().parent
DB=ROOT/'prototype.sqlite3'
TOKEN=secrets.token_urlsafe(32)
LOCK=threading.Lock()
AUTH_LOCK=threading.Lock()
PROMPT=(ROOT/'tutor_prompt.txt').read_text()
PROMPT_VERSION='0.4-socratic-role-clarity'
SESSION_IDLE=30*60
SESSION_MAX=8*60*60
ATTEMPTS={}
DUMMY_SALT=secrets.token_hex(16)
def now():return datetime.now(timezone.utc).isoformat()
class ClosingConnection(sqlite3.Connection):
 def __exit__(self,*args):
  try:return super().__exit__(*args)
  finally:self.close()
def connect():
 c=sqlite3.connect(DB,timeout=15,factory=ClosingConnection);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA secure_delete=ON');return c
def initialize():
 with connect() as c:
  c.execute('PRAGMA journal_mode=WAL')
  c.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,time TEXT,kind TEXT,payload TEXT)')
  if 'owner_id' not in [r['name'] for r in c.execute('PRAGMA table_info(events)')]:c.execute('ALTER TABLE events ADD COLUMN owner_id TEXT')
  c.executescript('''
  CREATE INDEX IF NOT EXISTS event_owner ON events(owner_id,id);
  CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,role TEXT NOT NULL,teacher_id TEXT,class_name TEXT NOT NULL DEFAULT '',salt TEXT NOT NULL,password_hash TEXT NOT NULL,must_change INTEGER NOT NULL DEFAULT 1,active INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL,research_allowed INTEGER NOT NULL DEFAULT 0);
  CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,created REAL NOT NULL,last_seen REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,time TEXT NOT NULL,actor TEXT,action TEXT NOT NULL,target TEXT);
  ''')
  if 'research_id' not in [r['name'] for r in c.execute('PRAGMA table_info(users)')]:c.execute('ALTER TABLE users ADD COLUMN research_id TEXT')
  for row in c.execute('SELECT id FROM users WHERE research_id IS NULL').fetchall():c.execute('UPDATE users SET research_id=? WHERE id=?',('r-'+secrets.token_hex(8),row['id']))
 try:DB.chmod(0o600)
 except OSError:pass
def password_hash(password,salt):return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
def set_password(c,uid,password,must_change):
 if not isinstance(password,str) or not 12<=len(password)<=128:raise ValueError('비밀번호는 12~128자로 입력하세요.')
 salt=secrets.token_hex(16)
 c.execute('UPDATE users SET salt=?,password_hash=?,must_change=? WHERE id=?',(salt,password_hash(password,salt),must_change,uid))
 c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
def audit(c,actor,action,target=None):c.execute('INSERT INTO audit(time,actor,action,target) VALUES(?,?,?,?)',(now(),actor,action,target))
def public_user(u):return {k:u[k] for k in ('id','username','role','class_name','must_change')}
def new_user(c,username,role,password,teacher=None,class_name=''):
 uid=secrets.token_hex(16)
 c.execute('INSERT INTO users(id,username,role,teacher_id,class_name,salt,password_hash,created) VALUES(?,?,?,?,?,?,?,?)',(uid,username,role,teacher,class_name,'','',now()))
 c.execute('UPDATE users SET research_id=? WHERE id=?',('r-'+secrets.token_hex(8),uid))
 set_password(c,uid,password,role=='student');return uid
def records(owner):
 with connect() as c:
  rows=c.execute('SELECT * FROM events WHERE owner_id IS ? ORDER BY id',(owner,)).fetchall()
 return [dict(r)|{'payload':json.loads(r['payload'])} for r in rows]
def save(owner,kind,payload):
 with connect() as c:
  u=c.execute('SELECT active FROM users WHERE id=?',(owner,)).fetchone()
  if not u or not u['active']:raise ValueError('비활성 계정')
  c.execute('INSERT INTO events(time,kind,payload,owner_id) VALUES(?,?,?,?)',(now(),kind,json.dumps(payload,ensure_ascii=False),owner))
def ollama(path,body=None,timeout=4):
 req=urllib.request.Request('http://127.0.0.1:11434'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)
