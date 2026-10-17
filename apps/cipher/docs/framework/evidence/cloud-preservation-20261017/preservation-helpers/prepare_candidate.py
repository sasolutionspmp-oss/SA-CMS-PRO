from pathlib import Path
import hashlib,json,shutil,subprocess

R=Path('/dev/shm/cipher-cloud-preservation-20261017')
D=Path('/dev/shm/cipher-documents-doc03')
U=D/'ui-workspace'
P=Path('/tmp/cipher-company-publication-r10')
E=P/'apps/cipher/docs/framework/evidence/r3/document-control-doc03-source'
F=R/'candidate-freeze-v1'
F.mkdir(exist_ok=False)
E.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
write=lambda p,d:p.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
base=json.loads((D/'UI_COMPOSED_BASELINE_v1.json').read_text())['source_inventory']
extra=[
'apps/cipher/product/src/api/document-control.ts',
'apps/cipher/product/src/DocumentControlChoices.tsx',
'apps/cipher/product/src/DocumentControl.tsx',
'apps/cipher/product/tests/document-control-fixture.ts',
'apps/cipher/product/tests/document-control-validation.spec.ts',
'apps/cipher/product/tests/document-control.spec.ts',
'apps/cipher/product/playwright.document-control.config.ts']
inventory={k:sha(U/k) for k in sorted(set(base)|set(extra))}
changed=[k for k,v in base.items() if inventory[k]!=v]
assert set(changed)=={'apps/cipher/product/src/App.tsx','apps/cipher/product/src/Approvals.tsx','apps/cipher/product/src/Documents.tsx','apps/cipher/product/src/styles.css'}
assert len(inventory)==890
backend=json.loads((D/'frozen-backend-v1/MANIFEST.json').read_text())
backend_inv=json.loads((D/'frozen-backend-v1/SOURCE_INVENTORY.json').read_text())
upstream=json.loads((D/'UI_COMPOSED_BASELINE_v1.json').read_text())
upstream_paths=set(upstream['upstream6_paths'])|set(upstream['ENG02_wire_correction3_paths'])
assert len(upstream_paths)==9
assert all(inventory[k]==v for k,v in backend_inv.items() if k not in upstream_paths and k not in changed)
assert all(inventory[k]==sha(P/k) for k in upstream_paths)
delta=[k for k,v in inventory.items() if not (P/k).is_file() or sha(P/k)!=v]
assert len(delta)==82
assert set(delta)==set(backend['source_delta'])|set(changed)|set(extra)
for k in delta:
 target=F/'files'/k;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(U/k,target);target.chmod(0o400)
write(F/'SOURCE_INVENTORY.json',inventory)
dist={str(p.relative_to(D/'dist-v1')):sha(p) for p in sorted((D/'dist-v1').rglob('*')) if p.is_file()}
assert len(dist)==931
write(F/'DIST_INVENTORY.json',dist)
for k in ['BASELINE.json','COMPATIBILITY.json','FAILURES.json','HANDOFF.md','QUALIFICATION.json','UI_COMPOSED_BASELINE_v1.json','UI_DRAFT_BASELINE.json','build_contracts.py','native-fixture-version-correction.private.json','native-fixture-version-review.private.json']:
 target=E/'originals'/k;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(D/k,target)
for p in sorted((D/'logs').iterdir()):
 if p.is_file():target=E/'originals'/'backend-logs'/p.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
for p in D.iterdir():
 if p.is_file() and (p.name.endswith('-report.json') or p.name.endswith('.private.log')):
  target=E/'originals'/'ui-reports'/p.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
for directory in ['focused-v1','affected-v2','affected-v3','journey-v4']:
 for p in (D/directory).rglob('*'):
  if p.is_file() and p.suffix in ['.md','.json']:
   target=E/'originals'/'browser-context'/directory/p.relative_to(D/directory);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
for k in ['MANIFEST.json','SOURCE_INVENTORY.json']:
 target=E/'originals'/'backend-freeze'/k;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(D/'frozen-backend-v1'/k,target)
results={}
for name in ['focused-v1','affected-v2','affected-v3','journey-v4']:
 p=D/(name+'-report.json');report=json.loads(p.read_text());assert report['config']['workers']==1
 results[name]={'report':'originals/ui-reports/'+p.name,'sha256':sha(p),'stats':report['stats']}
assert results['focused-v1']['stats']['expected']==26 and results['focused-v1']['stats']['unexpected']==4
assert results['affected-v2']['stats']['expected']==2 and results['affected-v2']['stats']['unexpected']==2
assert results['affected-v3']['stats']['expected']==1 and results['affected-v3']['stats']['unexpected']==1
assert results['journey-v4']['stats']['expected']==1 and results['journey-v4']['stats']['unexpected']==0
assert all(x['stats']['skipped']==0 and x['stats']['flaky']==0 for x in results.values())
qualification={
 'schema':'cipher.doc03.project-candidate-qualification.v1','base_commit':'f79df23af5bdb1c8cccf538241452bef2c459672',
 'backend_host_cases':183,'new_backend_cases':31,'compatibility_backend_cases':152,'generated_contracts':16,
 'typecheck':'passed retained integrated v4 log','build':'passed retained dist-v1 build; 931 files',
 'focused_checks':{'distinct_passed':30,'fresh_all_pass_run':False,'composition':'26 initial + 2 recovery continuation + 1 access-denial continuation + 1 final complete journey','runs':results},
 'browser_mode':'explicit RPC contract fixtures; not native UI evidence','native_DOC03':'declared workflow; not executed locally; hosted candidate pending',
 'full_DOC03_C20_complete':False,'remaining_original_scope':['Company/global library','Clause Use/Redline','withdrawal/supersession lifecycle','native UI and runtime qualification'],
 'withdrawn_observation':'native fixture expected_revision detour withdrawn after service read; original native fixture restored byte-for-byte',
 'source_changed_after_build':'only browser test helpers/assertions; application source unchanged',
 'no_award_action':True,'no_runtime_restarts':True}
write(E/'QUALIFICATION.json',qualification)
write(F/'QUALIFICATION.json',qualification)
manifest={'schema':'cipher.doc03.project-source-freeze.v1','base_commit':qualification['base_commit'],'source_files':890,'source_delta':delta,'changed_source_paths':82,'source_inventory':'SOURCE_INVENTORY.json','source_inventory_sha256':sha(F/'SOURCE_INVENTORY.json'),'dist_files':931,'dist_inventory':'DIST_INVENTORY.json','dist_inventory_sha256':sha(F/'DIST_INVENTORY.json'),'backend_original_freeze_sha256':sha(D/'frozen-backend-v1/MANIFEST.json'),'native_installed':False,'full_DOC03_C20_complete':False,'upstream_CI_and_ENG02_wire_paths_preserved':sorted(upstream_paths)}
write(F/'MANIFEST.json',manifest)
for k in ['MANIFEST.json','SOURCE_INVENTORY.json','DIST_INVENTORY.json']:shutil.copyfile(F/k,E/k)
for k in delta:
 target=P/k;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(F/'files'/k,target)
assert all(sha(P/k)==v for k,v in inventory.items())
for p in F.rglob('*'):
 if p.is_file():p.chmod(0o400)
print(json.dumps({'freeze':str(F),'manifest_sha256':sha(F/'MANIFEST.json'),'source_delta':len(delta),'source_inventory_sha256':sha(F/'SOURCE_INVENTORY.json'),'evidence_files':sum(p.is_file() for p in E.rglob('*'))}))
