from pathlib import Path
import gzip,hashlib,io,json,tarfile

R=Path('/dev/shm/cipher-cloud-preservation-20261017')
D=Path('/dev/shm/cipher-documents-doc03')
A=R/'archives';A.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def archive(name,rows):
 p=A/name;members={}
 with p.open('xb') as out,gzip.GzipFile(fileobj=out,mode='wb',mtime=0) as compressed,tarfile.open(fileobj=compressed,mode='w|') as tar:
  for k,f in sorted(rows):
   assert f.is_file() and not f.is_symlink(),str(f)
   data=f.read_bytes();members[k]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
   info=tarfile.TarInfo(k);info.size=len(data);info.mode=0o644;info.mtime=0;tar.addfile(info,io.BytesIO(data))
 index={'archive':name,'sha256':sha(p),'bytes':p.stat().st_size,'members':members}
 (A/(name+'.manifest.json')).write_text(json.dumps(index,indent=2,sort_keys=True)+'\n');p.chmod(0o400)
 print(json.dumps({k:v for k,v in index.items() if k!='members'}))
 return index
backend=json.loads((D/'frozen-backend-v1/SOURCE_INVENTORY.json').read_text())
assert all(sha(D/'workspace'/k)==v for k,v in backend.items())
archive('doc03-original-backend-source.tar.gz',[(k,D/'workspace'/k) for k in backend])
candidate=json.loads((R/'candidate-freeze-v1/SOURCE_INVENTORY.json').read_text())
assert all(sha(D/'ui-workspace'/k)==v for k,v in candidate.items())
archive('doc03-project-candidate-source.tar.gz',[(k,D/'ui-workspace'/k) for k in candidate])
archive('doc03-project-dist.tar.gz',[(str(p.relative_to(D/'dist-v1')),p) for p in (D/'dist-v1').rglob('*') if p.is_file()])
rows=[]
for directory in ['focused-v1','affected-v2','affected-v3','journey-v4','adapter-tests-v1','logs']:
 for p in (D/directory).rglob('*'):
  if p.is_file():rows.append((directory+'/'+str(p.relative_to(D/directory)),p))
for p in D.iterdir():
 if p.is_file():rows.append((p.name,p))
for p in (D/'frozen-backend-v1').iterdir():
 if p.is_file():rows.append(('frozen-backend-v1/'+p.name,p))
for name,folder in [('eng02-compiled','ci-static-v1'),('eng02-approval-wire','approval-wire-v1')]:
 p=Path('/dev/shm/cipher-engineering-eng02')/folder/'hosted-success.private.log';rows.append((name+'/hosted-success.private.log',p))
p=Path('/tmp/cipher-completion/new-framework-active.json');rows.append(('journals/new-framework-active.original.json',p))
archive('doc03-reports-traces-and-handoff.tar.gz',rows)
