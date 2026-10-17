from pathlib import Path
import hashlib,json,shutil,subprocess

R=Path('/dev/shm/cipher-cloud-preservation-20261017');P=Path('/tmp/cipher-company-publication-r10');W=R/'wip-prep'
candidate=json.loads((R/'candidate-remote-receipt.json').read_text())
subprocess.run(['git','switch','-c','cipher/preserve-doc03-successor-wip-20261017',candidate['candidate_sha']],cwd=P,check=True,capture_output=True)
E=P/'apps/cipher/docs/framework/evidence/cloud-preservation-20261017';E.mkdir(exist_ok=False)
delta=json.loads((W/'SOURCE_DELTA.json').read_text());paths=[x['path'] for kind in ['modified','added'] for x in delta[kind]];assert len(paths)==55 and not delta['deleted']
original=json.loads((W/'SOURCE_INVENTORY.json').read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for k in paths:
 assert sha(W/'workspace'/k)==original[k]
 assert sha(Path('/dev/shm/cipher-documents-doc03-successor/workspace')/k)==original[k]
 target=P/k;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(W/'workspace'/k,target)
combined=json.loads((R/'candidate-freeze-v1/SOURCE_INVENTORY.json').read_text());combined.update({k:original[k] for k in paths});assert len(combined)==914
assert all(sha(P/k)==v for k,v in combined.items())
(E/'COMPOSED_WIP_SOURCE_INVENTORY.json').write_text(json.dumps(combined,indent=2,sort_keys=True)+'\n');assert sha(E/'COMPOSED_WIP_SOURCE_INVENTORY.json')=='bb93a9fb55bd86ed22533fe16458581dd2f9235b632afd85e53af0ac40233664'
for f in W.rglob('*'):
 if not f.is_file() or 'workspace' in f.relative_to(W).parts:continue
 target=E/'successor-originals'/f.relative_to(W);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,target)
for f in (R/'archive-parts').iterdir():
 target=E/'archive-parts'/f.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,target)
for f in (R/'archives').glob('*.manifest.json'):
 target=E/'archive-manifests'/f.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,target)
shutil.copyfile(R/'candidate-remote-receipt.json',E/'CANDIDATE_REMOTE_RECEIPT.json')
shutil.copyfile('/tmp/cipher-completion/new-framework-active.json',E/'cloud-active-journal.original.json')
for name in ['prepare_candidate.py','prepare_archives.py','verify_preservation.py','prepare_wip.py']:
 target=E/'preservation-helpers'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(R/name,target)
readme='''# Cloud preservation retrieval

This ref is incomplete WIP, not a sandbox release. Use the Project candidate for integration. No current-WIP test/type/build/native pass is claimed. Generated wire files are stale relative to later backend changes. Do not run lifecycle hooks as a completed feature.

## Source refs

- Repository: https://github.com/sasolutionspmp-oss/SA-CMS-PRO
- Base: `f79df23af5bdb1c8cccf538241452bef2c459672`.
- Reviewed Project candidate: `cipher/preserve-doc03-project-20261017`, commit `CANDIDATE_SHA`.
- Paused successor: `cipher/preserve-doc03-successor-wip-20261017`, descends from that candidate. Its final remote SHA is supplied in the external publication receipt after readback.

The current WIP tree composes exactly the 55 successor changes onto the candidate; its 914-file inventory is `COMPOSED_WIP_SOURCE_INVENTORY.json`. The 9 newer CI/engineering-wire paths and 11 handwritten UI paths have no overlap with those changes. Original successor metadata in `successor-originals/` refers to its earlier 904-file source tree and 880-file parent, not to this composed tree. Historical nine clause and six Company passes precede later incomplete edits; they do not qualify this checkout.

## Retrieve original snapshots and evidence

Fetch the WIP ref into a sparse checkout that includes `apps/cipher/docs/framework/evidence/cloud-preservation-20261017`. Files under `archive-parts/` are exact binary chunks, not Git LFS pointers. `ARCHIVES.json` records each part's length/SHA256, concatenation order and complete archive SHA256. Check those hashes before extracting.

Concatenate an archive's parts in the order listed in `archive-parts/ARCHIVES.json`, without decoding or modifying them. For example:

```sh
cat archive-parts/doc03-original-backend-source.tar.gz.part-* > /path/to/empty-transfer/doc03-original-backend-source.tar.gz
sha256sum /path/to/empty-transfer/doc03-original-backend-source.tar.gz
```

Extract each archive into a different empty directory. `archive-manifests/*.manifest.json` pins every member's uncompressed bytes and SHA256. No absolute or parent-relative tar paths are used.

| Archive | Exact retained content |
| --- | --- |
| doc03-original-backend-source.tar.gz | Original 880-file Project backend workspace |
| doc03-project-candidate-source.tar.gz | Combined 890-file Project backend/UI candidate |
| doc03-successor-wip-source-and-handoff.tar.gz | Original paused 904-file successor plus boundaries, contracts, logs and hash inventories |
| doc03-project-dist.tar.gz | Original 931-file production build; application source unchanged during later test-only continuations |
| doc03-reports-traces-and-handoff.tar.gz | Original backend/UI reports, logs, raw browser traces/error contexts, handoffs, frozen metadata, both hosted engineering success logs and original active journal |

Browser evidence uses explicit RPC contract fixtures and is not native UI evidence. Hosted engineering receipts qualify only their exact engineering commits. No new native DOC-03 run is scheduled by preservation. Main and isolated runtimes were not changed or restarted.

`EVIDENCE_SHA256.json` pins all files in this evidence subtree except itself. `successor-originals/HANDOFF.md` describes incomplete work and `QUALIFICATION.json` ties historical results to their source phase. Absolute cloud paths in historical records identify their former locations; use these copied files/archive members after transfer. Helper scripts are preserved forensic records, may be non-idempotent, and must not be replayed blindly.

Excluded: live credentials, runtime configuration, database volumes, dependency caches, node_modules and model weights. Dependencies should be restored from pinned manifests. The local coordinator owns sandbox packaging/integration. Continue original dependencies and retain the blocked award boundary; this transfer performs no award or deployment action.
'''.replace('CANDIDATE_SHA',candidate['candidate_sha'])
(E/'README.md').write_text(readme)
manifest={'schema':'cipher.doc03.successor-preservation.v1','base_sha':candidate['base_sha'],'parent_candidate_sha':candidate['candidate_sha'],'original_successor_source_files':904,'composed_source_files':914,'successor_delta_paths':paths,'original_successor_manifest_sha256':sha(W/'MANIFEST.json'),'original_successor_inventory_sha256':sha(W/'SOURCE_INVENTORY.json'),'composed_inventory_sha256':sha(E/'COMPOSED_WIP_SOURCE_INVENTORY.json'),'candidate_qualification':'reviewed source with retained host/generated/type/build/composed browser checks; native pending','successor_qualification':'INCOMPLETE UNQUALIFIED WIP; historical checks do not qualify current source','no_runtime_restart_deploy_award_action':True,'archives_index':'archive-parts/ARCHIVES.json'}
(E/'MANIFEST.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
hashes={str(f.relative_to(E)):sha(f) for f in sorted(E.rglob('*')) if f.is_file()};(E/'EVIDENCE_SHA256.json').write_text(json.dumps(hashes,indent=2,sort_keys=True)+'\n')
stage=paths+[str(f.relative_to(P)) for f in E.rglob('*') if f.is_file()];subprocess.run(['git','add','-f','--',*stage],cwd=P,check=True)
# Preserve original WIP bytes, including pre-existing formatting diagnostics.
raw=subprocess.run(['git','diff','--cached','--check','--','apps/cipher/platform','apps/cipher/product'],cwd=P,text=True,capture_output=True)
(R/'wip-original-whitespace.private.log').write_text(raw.stdout+raw.stderr)
subprocess.run(['git','commit','-m','WIP preserve paused DOC03 successor and exact cloud evidence archives'],cwd=P,check=True,capture_output=True)
local={'local_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=P,text=True).strip(),'tree':subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=P,text=True).strip(),'parent_sha':candidate['candidate_sha'],'base_tree':candidate['candidate_tree'],'paths':sorted(stage),'message':'WIP preserve paused DOC03 successor and exact cloud evidence archives','evidence_manifest_sha256':sha(E/'EVIDENCE_SHA256.json'),'wip_manifest_sha256':sha(E/'MANIFEST.json')}
(R/'wip-local-commit.json').write_text(json.dumps(local,indent=2)+'\n')
print(json.dumps({k:v for k,v in local.items() if k!='paths'}));print('committed_paths',len(stage));print(subprocess.check_output(['git','status','--short'],cwd=P,text=True))
