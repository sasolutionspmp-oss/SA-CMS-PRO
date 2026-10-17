from pathlib import Path
import ast,hashlib,io,json,re,subprocess,tarfile,zipfile

R=Path('/dev/shm/cipher-cloud-preservation-20261017')
P=Path('/tmp/cipher-company-publication-r10')
E=P/'apps/cipher/docs/framework/evidence/r3/document-control-doc03-source'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
inventory=json.loads((R/'candidate-freeze-v1/SOURCE_INVENTORY.json').read_text())
assert all(sha(P/k)==v for k,v in inventory.items())
module=ast.parse(Path('/dev/shm/cipher-r15-scan-actual-credentials.py').read_text())
code=next(ast.literal_eval(x.value) for x in module.body if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='code' for t in x.targets))
result=subprocess.run(['docker','exec','-i','cipher-ai04-stage-a-20261016-runtime-1','python','-'],input=code,text=True,capture_output=True,check=True)
needles=[x.encode() for x in json.loads(result.stdout)['needles']];assert len(needles)==16
count=0
def check(data,name):
 global count
 count+=1
 assert not any(v in data for v in needles),'private credential match: '+name
for k in inventory:check((P/k).read_bytes(),k)
for f in (P/'apps/cipher/docs/framework').rglob('*'):
 if f.is_file() and not f.is_symlink():check(f.read_bytes(),str(f.relative_to(P)))
for p in (R/'archives').glob('*.tar.gz'):
 with tarfile.open(p,mode='r|gz') as tar:
  for member in tar:
   assert member.isfile()
   data=tar.extractfile(member).read();check(data,p.name+':'+member.name)
   if member.name.endswith('.zip'):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
     for name in z.namelist():
      if not name.endswith('/'):check(z.read(name),p.name+':'+member.name+':'+name)
legacy=Path('/dev/shm/cipher-r15-required-legacy')
tree=subprocess.check_output(['git','ls-tree','-r','-z','HEAD','--','apps/cipher'],cwd=P).split(b'\0');blobs={}
for row in tree:
 if row:
  meta,path=row.split(b'\t',1);blobs[path.decode()]=meta.split()[2].decode()
for f in legacy.rglob('*'):
 if f.is_file():
  key=str(f.relative_to(legacy));data=f.read_bytes();blob=hashlib.sha1(('blob '+str(len(data))+'\0').encode()+data).hexdigest();assert blobs.get(key)==blob,key
  if (P/key).is_file():assert (P/key).read_bytes()==data,key
assert sum(f.is_file() for f in legacy.rglob('*'))==395
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd='/workspace/cipher-framework-draft',text=True).strip()=='7248171c14584deeaa308f850646ef5d7aeec891'
expected={'cipher-r0-runtime-1':('131d33103a68d12a763eb9402a0e4ca6792343d0a5d571d284feae98acd9bdb3','2026-10-15T15:11:47.70663337Z'),'cipher-ai04-stage-a-20261016-runtime-1':('fd5e233cbfd69890afc29e09bcc968d695e5a5c2b90bc60feee61b78be1f11e8','2026-10-16T03:12:18.081208862Z')}
for name,values in expected.items():assert tuple(subprocess.check_output(['docker','inspect','--format','{{.Id}} {{.State.StartedAt}}',name],text=True).strip().split())==values
delta=set(json.loads((R/'candidate-freeze-v1/MANIFEST.json').read_text())['source_delta'])
changes=subprocess.check_output(['git','diff','--name-only'],cwd=P,text=True).splitlines()+subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=P,text=True).splitlines()
assert all(k in delta or k.startswith('apps/cipher/docs/framework/') for k in changes)
links=0
for key in changes:
 f=P/key
 if not key.endswith('.md') or '/originals/' in key:continue
 for target in re.findall(r'\]\(([^)]+)\)',f.read_text()):
  target=target.strip('<>').split('#')[0]
  if not target or re.match(r'^[A-Za-z]+:',target) or target.startswith('/'):continue
  assert (f.parent/target).exists(),(key,target);links+=1
proof={'schema':'cipher.cloud-preservation-checks.v1','source_files_verified':len(inventory),'candidate_source_changes':82,'actual_private_values_checked':16,'files_or_archive_members_scanned':count,'private_credential_matches':0,'private_values_emitted':False,'legacy_files_unchanged':395,'legacy_suite':'2703 earlier cases reused; legacy source unchanged; not new-ERP qualification','MAIN_HEAD_and_runtime_ID_start_unchanged':True,'isolated_runtime_ID_start_unchanged':True,'no_install_deploy_award_restart':True,'source_scope_verified':True,'relative_links_verified':links,'current_WIP_test_pass_claimed':False,'heavy_unchanged_suites_rerun':False}
(E/'PRESERVATION_CHECKS.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
