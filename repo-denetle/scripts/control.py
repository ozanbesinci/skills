#!/usr/bin/env python3
"""Local evidence/workflow gates; does not call an LLM or execute audited code."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

DEPS = {
    'DISCOVERY': [], 'PLAN': ['DISCOVERY'],
    'BIZ': ['PLAN'], 'ARCH': ['PLAN'], 'REL': ['PLAN'], 'QA': ['PLAN'],
    'VERIFY': ['BIZ', 'ARCH', 'REL', 'QA'],
    'LIFE': ['BIZ', 'ARCH', 'REL', 'QA', 'VERIFY'],
}
ROLES = {'discovery','planner','biz','arch','rel','qa','verifier','life'}
AUDITS = ('BIZ','ARCH','REL','QA')
SHA_RE = re.compile(r'^[0-9a-f]{40}$')
MAX_ATTEMPTS = 2
MAX_REOPENS = 3
REVIEW_CHECKS = ('applicability','measurements','verification_preserved','synthesis')
VERDICTS = ('confirmed','disputed','unverified','rejected')
class AuditError(ValueError):
    pass

def utf8_stdio() -> None:
    # Windows pipes default to the ANSI code page (cp1254): Turkish turns to mojibake, emoji crashes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='replace')

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def valid_path(value: str) -> str:
    """Workspace-relative output path: strict, because it touches the local filesystem."""
    if not isinstance(value,str) or not value or '\\' in value or any(ord(c)<32 for c in value):
        raise AuditError('Invalid relative path')
    p=PurePosixPath(value)
    if p.is_absolute() or any(x in ('..','.') for x in value.split('/')) or ':' in value:
        raise AuditError('Unsafe relative path: '+value)
    return p.as_posix()

def valid_repo_path(value: str) -> str:
    """Repository path used only as an inventory key; bytes are stored by hash, never by this name."""
    if not isinstance(value,str) or not value or any(ord(c)<32 for c in value):
        raise AuditError('Invalid repository path')
    if value.startswith('/') or any(x in ('','.','..') for x in value.split('/')):
        raise AuditError('Unsafe repository path: '+value)
    return value

def within(root: Path, rel: str) -> Path:
    rel=valid_path(rel)
    candidate=root/rel
    # Reject symlink components even when their resolved target is inside root.
    current=root
    for part in PurePosixPath(rel).parts:
        current=current/part
        if current.is_symlink():
            raise AuditError('Symlink output not accepted: '+rel)
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise AuditError('Path outside workspace') from exc
    return candidate

def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8-sig')
    except UnicodeError as exc:
        raise AuditError('Not UTF-8 (save as UTF-8, e.g. not PowerShell 5 Set-Content): '+str(path)) from exc

def read_json(path: Path) -> Any:
    try:
        return json.loads(read_text(path))
    except (OSError,json.JSONDecodeError) as exc:
        raise AuditError('Cannot read JSON: '+str(path)) from exc

def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    fd,tmp=tempfile.mkstemp(prefix='.write-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as fh:
            fh.write(data); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def initialize(root: Path, manifest: dict, inventory: list) -> dict:
    if (root/'state.json').exists():
        raise AuditError('Run already initialized; do not overwrite source state')
    if not SHA_RE.fullmatch(manifest.get('commit','')):
        raise AuditError('Full lowercase 40-character commit required')
    if manifest.get('mode') not in ('native','sequential'):
        raise AuditError('Mode must be native or sequential')
    if manifest.get('profile') not in ('guvence','dengeli','derin'):
        raise AuditError('Unknown profile')
    seen=set()
    for item in inventory:
        p=valid_repo_path(item['path'])
        if p in seen: raise AuditError('Duplicate inventory path')
        seen.add(p)
        if item.get('content_path'):
            data=within(root,item['content_path']).read_bytes()
            if digest(data)!=item.get('sha256'): raise AuditError('Source hash mismatch: '+p)
    root.mkdir(parents=True,exist_ok=True)
    for folder in ('reports','findings','prompts','receipts'):
        (root/folder).mkdir(exist_ok=True)
    atomic_json(root/'manifest.json',manifest)
    atomic_json(root/'inventory.json',inventory)
    state={'version':2,'created_at':now(),'commit':manifest['commit'],
           'manifest_hash':digest((root/'manifest.json').read_bytes()),
           'inventory_hash':digest((root/'inventory.json').read_bytes()),
           'dispatch_limit':120,'dispatches':[],'reopens':0,
           'stages':{s:{'status':'pending','attempts':0,'artifacts':{}} for s in DEPS},
           'events':[]}
    atomic_json(root/'state.json',state)
    return state

def load(root: Path) -> tuple[dict,dict,list]:
    state=read_json(root/'state.json')
    for name,key in (('manifest.json','manifest_hash'),('inventory.json','inventory_hash')):
        if digest(within(root,name).read_bytes())!=state[key]:
            raise AuditError('Pinned input changed: '+name)
    manifest=read_json(root/'manifest.json'); inventory=read_json(root/'inventory.json')
    if state['commit']!=manifest['commit']: raise AuditError('Commit mismatch')
    return state,manifest,inventory

def verify_artifacts(root: Path,state: dict) -> None:
    for stage,info in state['stages'].items():
        if info['status']!='accepted': continue
        for rel,h in info['artifacts'].items():
            p=within(root,rel)
            if not p.is_file() or digest(p.read_bytes())!=h:
                raise AuditError('Accepted artifact changed: '+stage+' '+rel+'; reopen stage first')

def get_source(root: Path,item: dict) -> str:
    if not item.get('text') or not item.get('content_path'):
        raise AuditError('Source is unavailable/non-text: '+item['path'])
    data=within(root,item['content_path']).read_bytes()
    if digest(data)!=item.get('sha256'): raise AuditError('Source content changed: '+item['path'])
    try: return data.decode('utf-8')
    except UnicodeError as exc: raise AuditError('Source not UTF-8') from exc

def normalize(text: str) -> str:
    # Console copies lose NBSP/tab/CRLF distinctions and may change Unicode composition.
    return ' '.join(unicodedata.normalize('NFC',text).split())

def evidence(root: Path,ev: dict,idx: dict) -> None:
    path=ev.get('path'); item=idx.get(path)
    if item is None: raise AuditError('Evidence path not in inventory: '+str(path))
    if ev.get('sha256')!=item.get('sha256'): raise AuditError('Evidence hash mismatch: '+path)
    lines=get_source(root,item).splitlines()
    start,end=ev.get('start'),ev.get('end')
    if type(start) is not int or type(end) is not int or not 1<=start<=end<=len(lines):
        raise AuditError('Evidence range invalid: '+path)
    quote=ev.get('quote')
    if quote is not None and (not isinstance(quote,str) or not normalize(quote)
                              or normalize(quote) not in normalize('\n'.join(lines[start-1:end]))):
        raise AuditError('Evidence quote does not match source: '+path)

def validate_coverage(root: Path,rows: list,idx: dict,complete: bool=False) -> dict:
    if not isinstance(rows,list): raise AuditError('coverage must be an array')
    seen=set(); intervals={}
    for row in rows:
        p=row.get('path'); item=idx.get(p)
        if item is None: raise AuditError('Coverage path not found: '+str(p))
        seen.add(p); status=row.get('status')
        if status=='reviewed':
            if item.get('line_count')==0 and item.get('text'):
                if row.get('sha256')!=item['sha256']: raise AuditError('Empty file hash mismatch')
                get_source(root,item); intervals[p]=[(0,0)]
            else:
                evidence(root,row,idx); intervals.setdefault(p,[]).append((row['start'],row['end']))
        elif status in ('partial','unreviewed'):
            if not row.get('reason'): raise AuditError('Coverage gap requires a reason')
        else: raise AuditError('Unknown coverage status')
    if complete and set(idx)!=seen:
        raise AuditError('Discovery coverage omits '+str(len(set(idx)-seen))+' inventory items')
    full=0; partial=0
    for path,pairs in intervals.items():
        end=0
        for a,b in sorted(pairs):
            if a>end+1: break
            end=max(end,b)
        n=idx[path].get('line_count',0)
        if end>=n: full+=1
        else: partial+=1
    return {'inventory_items':len(idx),'fully_reviewed_text_files':full,
            'partly_reviewed_text_files':partial,'other_or_unreviewed':len(idx)-full-partial,
            'self_reported':True}

def audit_ids(root: Path,stages: tuple= AUDITS) -> set:
    result=set()
    for stage in stages:
        obj=read_json(root/'findings'/f'{stage}.json')
        for f in obj.get('findings',[]):
            if f['id'] in result: raise AuditError('Duplicate finding ID')
            result.add(f['id'])
    return result

def validate_stage(root: Path,stage: str,manifest: dict,inventory: list,write: bool=True) -> list[str]:
    report_rel=f'reports/{stage}.md'; side_rel=f'findings/{stage}.json'
    rp=within(root,report_rel); sp=within(root,side_rel)
    if not rp.is_file() or not sp.is_file(): raise AuditError('Report/sidecar missing for '+stage)
    report=read_text(rp); data=read_json(sp)
    if len(report.strip())<100 or manifest['commit'] not in report:
        raise AuditError('Report too short or full commit missing')
    if manifest['mode']=='sequential' and 'SIRALI CALISMA' not in report:
        raise AuditError('Sequential independence limitation missing from report')
    if data.get('stage')!=stage or data.get('commit')!=manifest['commit']:
        raise AuditError('Sidecar stage/commit mismatch')
    if data.get('report_path')!=report_rel or data.get('mode')!='static':
        raise AuditError('Sidecar report_path/mode mismatch')
    if not isinstance(data.get('limitations'),list): raise AuditError('limitations array required')
    if not isinstance(data.get('telemetry'),dict): raise AuditError('telemetry object required')
    idx={i['path']:i for i in inventory}
    summary=validate_coverage(root,data.get('coverage'),idx,stage=='DISCOVERY')
    fs=data.get('findings')
    if not isinstance(fs,list): raise AuditError('findings array required')
    seen=set()
    for f in fs:
        fid=f.get('id','')
        if not re.fullmatch(stage+r'-[0-9]{3,}',fid) or fid in seen:
            raise AuditError('Invalid or duplicate finding ID: '+fid)
        seen.add(fid)
        if stage not in (*AUDITS,'LIFE'): raise AuditError('Only domain auditors create findings')
        if f.get('severity') not in ('P0','P1','P2','P3'): raise AuditError('Invalid priority')
        for key in ('title','kind','confidence','evidence_level','observed','expected','impact','recommendation','acceptance'):
            if not isinstance(f.get(key),str) or not f[key].strip(): raise AuditError('Finding missing '+key)
        if not f.get('evidence'): raise AuditError('Finding requires source evidence')
        if fid not in report: raise AuditError('Finding ID absent from full report')
        for ev in f['evidence']: evidence(root,ev,idx)
    artifacts=[report_rel,side_rel]
    if stage=='DISCOVERY':
        context=within(root,'context.md')
        if not context.is_file() or manifest['commit'] not in read_text(context):
            raise AuditError('context.md with full commit is required')
        if write: atomic_json(root/'coverage.json',summary)
        artifacts+=['context.md','coverage.json']
    if stage=='PLAN':
        for name in (*AUDITS,'LIFE'):
            rel=f'prompts/{name}.md'; p=within(root,rel)
            if not p.is_file() or manifest['commit'] not in read_text(p):
                raise AuditError('Missing pinned prompt: '+name)
            artifacts.append(rel)
    if stage=='VERIFY':
        needed=audit_ids(root); verdicts=data.get('verification')
        if not isinstance(verdicts,list): raise AuditError('verification array required')
        ids=[v.get('finding_id') for v in verdicts]
        if set(ids)!=needed or len(ids)!=len(set(ids)):
            raise AuditError('Verification must classify every original finding exactly once')
        for v in verdicts:
            if v.get('status') not in ('confirmed','disputed','unverified','rejected') or not v.get('reason'):
                raise AuditError('Invalid verification verdict')
            if v['status']!='unverified' and not v.get('evidence'):
                raise AuditError('Substantiated verification verdict requires source evidence')
            for ev in v.get('evidence',[]): evidence(root,ev,idx)
    if stage=='LIFE':
        cons=read_json(root/'findings/consolidated.json')
        needed=audit_ids(root)|seen
        if not isinstance(cons,list): raise AuditError('Consolidated findings must be array')
        used=set(); cids=set()
        for c in cons:
            if not re.fullmatch(r'CONS-[0-9]{3,}',c.get('id','')) or c['id'] in cids:
                raise AuditError('Invalid consolidation ID')
            cids.add(c['id'])
            ss=c.get('source_ids',[])
            if not ss or not set(ss)<=needed or not c.get('reason') or not c.get('disposition'):
                raise AuditError('Invalid consolidation mapping')
            used.update(ss)
        if used!=needed: raise AuditError('Consolidation drops findings')
        artifacts.append('findings/consolidated.json')
        for rel in ('roadmap.md','executive-summary.md'):
            p=within(root,rel)
            if not p.is_file() or manifest['commit'] not in read_text(p):
                raise AuditError('Missing pinned '+rel)
            artifacts.append(rel)
    return artifacts

def check(root: Path,stage: str) -> dict:
    """Dry run of accept: same validation, no attempt consumed, no state written."""
    state,manifest,inventory=load(root)
    if stage not in DEPS: raise AuditError('Unknown stage')
    verify_artifacts(root,state)
    missing=[d for d in DEPS[stage] if state['stages'][d]['status']!='accepted']
    if missing: raise AuditError('Prerequisite stages not accepted for '+stage+': '+', '.join(missing))
    validate_stage(root,stage,manifest,inventory,write=False)
    return {'stage':stage,'check':'passed','attempts_left':MAX_ATTEMPTS-state['stages'][stage]['attempts']}

def accept(root: Path,stage: str) -> dict:
    state,manifest,inventory=load(root)
    if stage not in DEPS: raise AuditError('Unknown stage')
    verify_artifacts(root,state)
    info=state['stages'][stage]
    if info['status']=='accepted': return {'stage':stage,'status':'already_accepted'}
    if any(state['stages'][d]['status']!='accepted' for d in DEPS[stage]):
        raise AuditError('Prerequisite stages not accepted for '+stage)
    if info['attempts']>=MAX_ATTEMPTS: raise AuditError('Stage attempt budget exhausted; record limitation, do not loop')
    info['attempts']+=1
    try:
        artifacts=validate_stage(root,stage,manifest,inventory)
    except (AuditError,OSError,UnicodeError,KeyError,TypeError) as exc:
        info['status']='rejected'; info['last_error']=str(exc)
        state['events'].append({'at':now(),'stage':stage,'event':'rejected','reason':str(exc)})
        atomic_json(root/'state.json',state)
        raise AuditError(str(exc)) from exc
    info.update(status='accepted',accepted_at=now(),artifacts={r:digest(within(root,r).read_bytes()) for r in artifacts})
    info.pop('last_error',None)
    state['events'].append({'at':now(),'stage':stage,'event':'accepted'})
    atomic_json(root/'state.json',state)
    return {'stage':stage,'status':'accepted','structural_only':True}

def reopen(root: Path,stage: str,reason: str) -> dict:
    state,_,_=load(root)
    if stage not in DEPS or not reason.strip(): raise AuditError('Valid stage and reason required')
    if state.get('reopens',0)>=MAX_REOPENS: raise AuditError('Reopen budget exhausted; start a new run and record why')
    # Preserve earlier delivery as history; it must no longer look like the active result.
    previous=[within(root,name) for name in ('completion.json','repo-denetle-raporlar.zip','review.json')
              if within(root,name).exists()]
    historical=[]
    if previous:
        history=within(root,'superseded'); history.mkdir(exist_ok=True)
        folder=Path(tempfile.mkdtemp(prefix='delivery-',dir=history))
        for path in previous:
            destination=folder/path.name
            os.replace(path,destination)
            historical.append(destination.relative_to(root).as_posix())
    affected={stage}
    while True:
        expanded=affected|{s for s,deps in DEPS.items() if set(deps)&affected}
        if expanded==affected: break
        affected=expanded
    # New evidence restarts the attempt budget; MAX_REOPENS and the dispatch cap still stop loops.
    for s in affected:
        info=state['stages'][s]
        info.update(status='pending',artifacts={},attempts=0); info.pop('last_error',None)
    state['reopens']=state.get('reopens',0)+1
    state['events'].append({'at':now(),'event':'reopened','stage':stage,'reason':reason,'invalidated':sorted(affected),
                            'superseded_delivery':historical})
    atomic_json(root/'state.json',state)
    return {'invalidated':sorted(affected),'reopens_left':MAX_REOPENS-state['reopens']}

def require_open_delivery(root: Path) -> None:
    if any(within(root,name).exists() for name in ('completion.json','repo-denetle-raporlar.zip')):
        raise AuditError('Delivery already exists; reopen the affected stage before changing execution records')

def dispatch(root: Path,role: str,requested_model: str='',requested_effort: str='') -> dict:
    require_open_delivery(root)
    state,manifest,_=load(root)
    if role not in ROLES: raise AuditError('Unknown role')
    if len(state['dispatches'])>=state['dispatch_limit']: raise AuditError('Dispatch budget exhausted')
    row={'id':f'D-{len(state["dispatches"])+1:04d}','role':role,'time':now(),
         'requested_model':requested_model or None,'requested_effort':requested_effort or None,
         'actual_model':None,'actual_effort':None,'agent_id':None,'tokens':None,'mode':manifest['mode']}
    state['dispatches'].append(row); atomic_json(root/'state.json',state); return row

def telemetry(root: Path,dispatch_id: str,model: str='',effort: str='',agent_id: str='',tokens: int|None=None) -> dict:
    """Record values the HOST reported for a dispatch. Never fill these from the requested settings."""
    require_open_delivery(root)
    state,_,_=load(root)
    row=next((d for d in state['dispatches'] if d['id']==dispatch_id),None)
    if row is None: raise AuditError('Unknown dispatch ID')
    if model: row['actual_model']=model
    if effort: row['actual_effort']=effort
    if agent_id: row['agent_id']=agent_id
    if tokens is not None:
        if tokens<0: raise AuditError('Token count cannot be negative')
        row['tokens']=tokens
    atomic_json(root/'state.json',state); return row

def review_template(root: Path) -> dict:
    """Unapproved form only. A real reader must assess the final LIFE and synthesis output."""
    state,manifest,_=load(root); verify_artifacts(root,state)
    if any(i['status']!='accepted' for i in state['stages'].values()):
        raise AuditError('All stages must be accepted before final review')
    artifacts={p:h for info in state['stages'].values() for p,h in info['artifacts'].items()}
    return {'schema':1,'commit':manifest['commit'],'state_sha256':digest((root/'state.json').read_bytes()),
            'artifacts':artifacts,'status':'needs_revision',
            'reviewer':{'kind':'coordinator','name':'','agent_id':None},
            'checks':{k:{'status':'needs_revision','reason':'','evidence':[]} for k in REVIEW_CHECKS},
            'findings':[{'finding_id':fid,'status':'unverified','reason':'','evidence':[]}
                        for fid in sorted(audit_ids(root,(*AUDITS,'LIFE')))],
            'claims':[],'limitations':[]}

def validate_review(root: Path) -> dict:
    expected=review_template(root)
    review=read_json(within(root,'review.json'))
    if not isinstance(review,dict) or review.get('schema')!=1 or review.get('commit')!=expected['commit']:
        raise AuditError('Final review schema/commit mismatch')
    if review.get('state_sha256')!=expected['state_sha256'] or review.get('artifacts')!=expected['artifacts']:
        raise AuditError('Final review is stale; re-read changed outputs and review again')
    if review.get('status')!='approved': raise AuditError('Final content review requires revision')
    reviewer=review.get('reviewer',{})
    if not isinstance(reviewer,dict) or reviewer.get('kind') not in ('coordinator','independent') or not str(reviewer.get('name') or '').strip():
        raise AuditError('Final reviewer identity required')
    if reviewer['kind']=='independent' and not reviewer.get('agent_id'):
        raise AuditError('Independent reviewer needs a real host agent ID')
    _,_,inventory=load(root); idx={i['path']:i for i in inventory}
    checks=review.get('checks')
    if not isinstance(checks,dict) or set(checks)!=set(REVIEW_CHECKS):
        raise AuditError('Final review must cover applicability, measurements, verdicts and synthesis')
    for key,row in checks.items():
        if not isinstance(row,dict) or row.get('status')!='passed' or not str(row.get('reason') or '').strip():
            raise AuditError('Final review check needs revision: '+key)
        for ev in row.get('evidence',[]): evidence(root,ev,idx)
    rows=review.get('findings')
    if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):
        raise AuditError('Final review findings must be an array of objects')
    ids=[r.get('finding_id') for r in rows]
    if len(ids)!=len(set(ids)) or set(ids)!={r['finding_id'] for r in expected['findings']}:
        raise AuditError('Final review must classify every original and LIFE finding exactly once')
    earlier={r['finding_id']:r['status'] for r in read_json(within(root,'findings/VERIFY.json'))['verification']}
    verdicts={}
    for row in rows:
        fid=row['finding_id']; status=row.get('status')
        if status not in VERDICTS or not str(row.get('reason') or '').strip():
            raise AuditError('Invalid final review verdict: '+fid)
        if status=='confirmed' and earlier.get(fid,'confirmed')!='confirmed':
            raise AuditError('Reopen VERIFY before promoting its disputed/unverified/rejected finding: '+fid)
        if status!='unverified' and not row.get('evidence'):
            raise AuditError('Final review verdict requires source evidence: '+fid)
        for ev in row.get('evidence',[]): evidence(root,ev,idx)
        verdicts[fid]=status
    claims=review.get('claims')
    if not isinstance(claims,list) or not isinstance(review.get('limitations'),list):
        raise AuditError('Final review claims and limitations must be arrays')
    seen=set()
    for claim in claims:
        if not isinstance(claim,dict): raise AuditError('Synthesis claim must be an object')
        cid=claim.get('id',''); path=claim.get('path')
        if not re.fullmatch(r'CLM-[0-9]{3,}',cid) or cid in seen:
            raise AuditError('Invalid/duplicate synthesis claim ID')
        seen.add(cid)
        if path not in ('reports/LIFE.md','executive-summary.md','roadmap.md'):
            raise AuditError('Invalid synthesis claim path')
        quote=claim.get('quote'); text=read_text(within(root,path))
        if not isinstance(quote,str) or not normalize(quote) or normalize(quote) not in normalize(text):
            raise AuditError('Synthesis claim quote does not match reviewed output')
        sources=claim.get('source_ids'); status=claim.get('status')
        if not isinstance(sources,list) or not sources or not set(sources)<=set(verdicts) or status not in VERDICTS:
            raise AuditError('Invalid synthesis source/status mapping')
        if status=='confirmed' and any(verdicts[fid]!='confirmed' for fid in sources):
            raise AuditError('Synthesis promotes an unconfirmed finding')
    return {'status':'review_record_validated','reviewer':reviewer,'structural_only':True,
            'review_sha256':digest(within(root,'review.json').read_bytes())}

def publish_delivery(root: Path,temporary: str,result: dict) -> None:
    """Publish the ZIP/marker pair, restoring both previous files on an ordinary I/O error."""
    targets=(within(root,'repo-denetle-raporlar.zip'),within(root,'completion.json'))
    rollback=Path(tempfile.mkdtemp(prefix='.delivery-',dir=root))
    moved={}; publishing=False; clean=False
    try:
        for path in targets:
            if path.exists():
                saved=rollback/path.name; os.replace(path,saved); moved[path]=saved
        publishing=True
        os.replace(temporary,targets[0])
        atomic_json(targets[1],result)
        clean=True
    except OSError:
        if publishing:
            for path in targets:
                if path.exists(): path.unlink()
        for path,saved in moved.items(): os.replace(saved,path)
        clean=True
        raise
    finally:
        # If rollback itself fails, retain its files for recovery instead of hiding the loss.
        if clean:
            for saved in moved.values():
                if saved.exists(): saved.unlink()
            rollback.rmdir()

def finalize(root: Path) -> dict:
    state,manifest,inventory=load(root); verify_artifacts(root,state)
    pending=[s for s,i in state['stages'].items() if i['status']!='accepted']
    if pending: raise AuditError('Incomplete stages: '+', '.join(pending))
    # Recheck citations against source bytes, not just report hashes.
    for s in DEPS: validate_stage(root,s,manifest,inventory,write=False)
    review=validate_review(root)
    result={'commit':manifest['commit'],'mode':manifest['mode'],
            'scope':manifest['scope'],'status':'STRUCTURALLY_VALIDATED_STATIC_AUDIT',
            'coverage':read_json(root/'coverage.json'),
            'state_sha256':digest((root/'state.json').read_bytes()),
            'review_sha256':review['review_sha256'],
            'warning':'Structural checks do not prove semantic accuracy, independence, or production readiness.'}
    files={'manifest.json','inventory.json','coverage.json','context.md','state.json',
           'completion.json','executive-summary.md','roadmap.md','review.json'}
    for info in state['stages'].values(): files.update(info['artifacts'])
    dest=within(root,'repo-denetle-raporlar.zip')
    fd,tmp=tempfile.mkstemp(prefix='.report-',suffix='.zip',dir=root)
    try:
        with os.fdopen(fd,'w+b') as fh:
            with zipfile.ZipFile(fh,'w',zipfile.ZIP_DEFLATED) as z:
                for rel in sorted(files):
                    data=((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
                          if rel=='completion.json' else within(root,rel).read_bytes())
                    z.writestr(rel,data)
            fh.flush(); os.fsync(fh.fileno())
        publish_delivery(root,tmp,result)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return {**result,'archive':str(dest),'archive_sha256':digest(dest.read_bytes())}

def read_range(root: Path,path: str,start: int,end: int) -> str:
    _,_,inv=load(root); idx={i['path']:i for i in inv}
    if path not in idx: raise AuditError('Path not in inventory')
    lines=get_source(root,idx[path]).splitlines()
    if start<1 or end<start: raise AuditError('Invalid range')
    return ''.join(f'{n}: {lines[n-1]}\n' for n in range(start,min(end,len(lines))+1))

def listing(root: Path,prefix: str='') -> str:
    _,_,inv=load(root); rows=[]
    for i in inv:
        if not i['path'].startswith(prefix): continue
        lines='-' if i.get('line_count') is None else str(i['line_count'])
        note=i.get('limitation') or ('text' if i.get('text') else i.get('kind','blob'))
        rows.append(f"{i['path']}\t{lines}\t{i.get('size',0)}\t{i.get('scope_role','')}\t{note}")
    return 'path\tlines\tbytes\tscope_role\tnote\n'+''.join(r+'\n' for r in rows)

def main() -> int:
    utf8_stdio()
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    for cmd in ('status','finalize','review-template','review-check'):
        q=sub.add_parser(cmd); q.add_argument('workspace',type=Path)
    q=sub.add_parser('list'); q.add_argument('workspace',type=Path); q.add_argument('--prefix',default='')
    q=sub.add_parser('read'); q.add_argument('workspace',type=Path); q.add_argument('path'); q.add_argument('--start',type=int,default=1); q.add_argument('--end',type=int,default=160)
    q.add_argument('--out',type=Path,help='write the numbered range to this UTF-8 file instead of stdout')
    for cmd in ('accept','check'):
        q=sub.add_parser(cmd); q.add_argument('workspace',type=Path); q.add_argument('stage',choices=DEPS)
    q=sub.add_parser('reopen'); q.add_argument('workspace',type=Path); q.add_argument('stage',choices=DEPS); q.add_argument('--reason',required=True)
    q=sub.add_parser('dispatch'); q.add_argument('workspace',type=Path); q.add_argument('role',choices=sorted(ROLES)); q.add_argument('--model',default=''); q.add_argument('--effort',default='')
    q=sub.add_parser('telemetry'); q.add_argument('workspace',type=Path); q.add_argument('dispatch_id')
    q.add_argument('--model',default=''); q.add_argument('--effort',default=''); q.add_argument('--agent-id',default=''); q.add_argument('--tokens',type=int)
    a=p.parse_args()
    try:
        root=a.workspace.resolve()
        if a.command in ('read','list'):
            text=read_range(root,a.path,a.start,a.end) if a.command=='read' else listing(root,a.prefix)
            if getattr(a,'out',None):
                a.out.write_text(text,encoding='utf-8'); print('written: '+str(a.out))
            else: sys.stdout.write(text)
            return 0
        if a.command=='accept': result=accept(root,a.stage)
        elif a.command=='check': result=check(root,a.stage)
        elif a.command=='reopen': result=reopen(root,a.stage,a.reason)
        elif a.command=='dispatch': result=dispatch(root,a.role,a.model,a.effort)
        elif a.command=='telemetry': result=telemetry(root,a.dispatch_id,a.model,a.effort,a.agent_id,a.tokens)
        elif a.command=='finalize': result=finalize(root)
        elif a.command=='review-template': result=review_template(root)
        elif a.command=='review-check': result=validate_review(root)
        else:
            state,manifest,inv=load(root); verify_artifacts(root,state)
            result={'commit':manifest['commit'],'repo':manifest.get('repo'),'mode':manifest['mode'],
                    'items':len(inv),'dispatches':len(state['dispatches']),
                    'reopens_left':MAX_REOPENS-state.get('reopens',0),
                    'stages':{s:f"{i['status']} ({i['attempts']}/{MAX_ATTEMPTS})" for s,i in state['stages'].items()}}
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    except (AuditError,OSError,UnicodeError,KeyError,TypeError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
