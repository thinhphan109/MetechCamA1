#!/usr/bin/env python3
"""Development-only VPS API. Put it behind Caddy/Nginx TLS in production."""
import hashlib, hmac, json, os, sqlite3, time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(os.environ.get('METECH_DATA','./data')); ROOT.mkdir(parents=True,exist_ok=True)
DB=ROOT/'metech.sqlite3'; MAX_IMAGE=800_000; WINDOW=300

def conn():
    db=sqlite3.connect(DB); db.execute('pragma journal_mode=wal');
    db.executescript('create table if not exists device(id text primary key, secret text not null); create table if not exists nonce(device text, value text, seen integer, primary key(device,value)); create table if not exists status(device text primary key, body text, seen integer); create table if not exists command(id integer primary key, device text, kind text, payload text, state text default "queued", result text);')
    return db

def authorized(h,body):
    device=h.headers.get('X-Metech-Device',''); stamp=h.headers.get('X-Metech-Time',''); nonce=h.headers.get('X-Metech-Nonce',''); signed=h.headers.get('X-Metech-Signature','')
    if not device or not stamp.isdigit() or not nonce or len(nonce)>64 or abs(time.time()-int(stamp))>WINDOW: return None
    db=conn(); row=db.execute('select secret from device where id=?',(device,)).fetchone()
    mac=hmac.new((row[0] if row else '').encode(),(stamp+'\n'+nonce+'\n').encode()+body,hashlib.sha256).hexdigest()
    if not row or not hmac.compare_digest(mac,signed): db.close(); return None
    try: db.execute('insert into nonce values(?,?,?)',(device,nonce,int(time.time()))); db.execute('delete from nonce where seen<?',(int(time.time())-WINDOW,)); db.commit()
    except sqlite3.IntegrityError: db.close(); return None
    db.close(); return device

class API(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def reply(self,status,body,ctype='application/json'):
        raw=json.dumps(body,separators=(',',':')).encode() if isinstance(body,(dict,list)) else body
        self.send_response(status); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        size=int(self.headers.get('Content-Length','0'))
        if size<0 or size>MAX_IMAGE: return self.reply(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,{'error':'size'})
        raw=self.rfile.read(size); device=authorized(self,raw)
        if not device:return self.reply(HTTPStatus.UNAUTHORIZED,{'error':'auth'})
        if self.path=='/v1/device/heartbeat':
            try: body=json.loads(raw); assert isinstance(body,dict)
            except: return self.reply(HTTPStatus.BAD_REQUEST,{'error':'json'})
            db=conn();db.execute('insert into status values(?,?,?) on conflict(device) do update set body=excluded.body,seen=excluded.seen',(device,json.dumps(body),int(time.time())));db.commit();db.close();return self.reply(200,{'ok':True})
        if self.path=='/v1/device/poll':
            db=conn();row=db.execute('select id,kind,payload from command where device=? and state="queued" order by id limit 1',(device,)).fetchone()
            if row: db.execute('update command set state="sent" where id=?',(row[0],));db.commit();db.close();return self.reply(200,{'command':{'id':row[0],'kind':row[1],'payload':json.loads(row[2])}})
            db.close();return self.reply(200,{'command':None})
        if self.path=='/v1/device/image':
            if self.headers.get('Content-Type')!='image/jpeg' or len(raw)<4 or raw[:2]!=b'\xff\xd8':return self.reply(HTTPStatus.BAD_REQUEST,{'error':'jpeg'})
            path=ROOT/f'{device}.jpg';path.write_bytes(raw);return self.reply(200,{'ok':True})
        return self.reply(404,{'error':'path'})

if __name__=='__main__':
    # ponytail: provision devices directly in sqlite for initial setup; add authenticated admin provisioning after VPS deployment.
    ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','8080'))),API).serve_forever()
