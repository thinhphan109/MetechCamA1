import hashlib,hmac,json,os,sqlite3,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
root=Path(tempfile.mkdtemp());env={**os.environ,'METECH_DATA':str(root),'PORT':'18080'}
db=sqlite3.connect(root/'metech.sqlite3');db.executescript('create table device(id text primary key,secret text not null);');db.execute('insert into device values(?,?)',('cam','secret'));db.commit();db.close()
p=subprocess.Popen([sys.executable,str(Path(__file__).with_name('server.py'))],env=env);time.sleep(.5)
def request(path,body,nonce='n'):
 raw=body if isinstance(body,bytes) else json.dumps(body).encode(); t=str(int(time.time())); sig=hmac.new(b'secret',(t+'\n'+nonce+'\n').encode()+raw,hashlib.sha256).hexdigest(); r=urllib.request.Request('http://127.0.0.1:18080'+path,data=raw,method='POST',headers={'X-Metech-Device':'cam','X-Metech-Time':t,'X-Metech-Nonce':nonce,'X-Metech-Signature':sig,'Content-Type':'image/jpeg' if path.endswith('image') else 'application/json'});return urllib.request.urlopen(r).read()
try:
 assert json.loads(request('/v1/device/heartbeat',{'ok':1}))['ok'];assert json.loads(request('/v1/device/poll',{},'p'))['command'] is None;assert json.loads(request('/v1/device/image',b'\xff\xd8ok','i'))['ok'];assert (root/'cam.jpg').exists();print('PASS: remote API auth/storage/poll')
finally:p.terminate();p.wait()
