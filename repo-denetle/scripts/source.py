#!/usr/bin/env python3
"""Acquire a pinned GitHub Git tree as non-executable blobs; never checkout source."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, unquote
# Sibling import must work under `python -I` (isolated mode drops the script directory from sys.path).
sys.path.insert(0,str(Path(__file__).resolve().parent))
from control import AuditError, SHA_RE, atomic_json, digest, initialize, now, utf8_stdio, valid_repo_path, within

MAX_FILE=2*1024*1024
MAX_TOTAL=256*1024*1024
MAX_FILES=50000

def parse_url(url: str) -> dict:
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname!='github.com' or u.username or u.password or u.port or u.query or u.fragment:
        raise AuditError('Use a credential-free HTTPS github.com repository/tree/blob URL')
    parts=[unquote(p) for p in u.path.strip('/').split('/')]
    if len(parts)<2 or not all(re.fullmatch(r'[A-Za-z0-9_.-]+',p or '') and p not in ('.','..') for p in parts[:2]):
        raise AuditError('Invalid owner/repository')
    owner,repo=parts[:2]
    if repo.endswith('.git'): repo=repo[:-4]
    if not repo: raise AuditError('Empty repository')
    kind='root'; tail=''
    if len(parts)>2:
        if parts[2] not in ('tree','blob') or len(parts)<4: raise AuditError('Unsupported GitHub URL type')
        kind=parts[2]; tail='/'.join(parts[3:]); valid_repo_path(tail)
    return {'repo':owner+'/'+repo,'remote':f'https://github.com/{owner}/{repo}.git','kind':kind,'tail':tail}

def run_git(args: list[str], gitdir: Path|None=None, stdin: bytes|None=None) -> bytes:
    env=os.environ.copy()
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_TERMINAL_PROMPT='0',GIT_LFS_SKIP_SMUDGE='1')
    # Do not inherit environment-injected Git configuration, repo paths, alternate object stores or hooks.
    for k in list(env):
        if k in ('GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_OBJECT_DIRECTORY') or k.startswith('GIT_CONFIG_KEY_') or k.startswith('GIT_CONFIG_VALUE_') or k in ('GIT_CONFIG_COUNT','GIT_CONFIG_PARAMETERS'):
            env.pop(k,None)
    # safe.directory: the global config is ignored above, so a --local-git repo created by another
    # account (e.g. a sandbox user) would otherwise fail as "dubious ownership". Only plumbing reads run.
    cmd=['git','-c','core.hooksPath='+os.devnull,'-c','core.fsmonitor=false','-c','safe.directory=*',
         '-c','protocol.file.allow=never','-c','protocol.ext.allow=never','-c','protocol.ssh.allow=never',
         '-c','credential.helper=','-c','fetch.recurseSubmodules=false']
    if gitdir: cmd+=['--git-dir='+str(gitdir)]
    cmd+=args
    try:
        cp=subprocess.run(cmd,env=env,input=stdin,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=600,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise AuditError('Git unavailable or timed out; use an authorized connector import') from exc
    if cp.returncode:
        # No raw remote error echo: it may contain private host details or credentials.
        raise AuditError('Git command failed: '+args[0]+'; use authorized connector/local Git input if necessary')
    return cp.stdout

def read_blobs(gitdir: Path,shas: list[str]) -> dict[str,bytes]:
    """One `cat-file --batch` process instead of one process per file (~120 ms each on Windows)."""
    unique=list(dict.fromkeys(shas))
    if not unique: return {}
    out=run_git(['cat-file','--batch'],gitdir,('\n'.join(unique)+'\n').encode('ascii'))
    result={}; pos=0
    for sha in unique:
        nl=out.find(b'\n',pos)
        header=out[pos:nl].decode('ascii','replace').split(' ') if nl>=0 else []
        if len(header)!=3 or header[0]!=sha or header[1]!='blob':
            raise AuditError('Git batch read failed for object '+sha)
        size=int(header[2]); start=nl+1
        result[sha]=out[start:start+size]; pos=start+size+1
    return result

def resolve_ref(parsed: dict, listing: str, override: str|None=None) -> tuple[str,str]:
    refs={}; head=None
    for line in listing.splitlines():
        fields=line.split('\t')
        if len(fields)!=2: continue
        left,right=fields
        if SHA_RE.fullmatch(left):
            refs[right]=left
            if right=='HEAD': head=left
    if override and not SHA_RE.fullmatch(override): raise AuditError('--ref requires full lowercase SHA')
    scope=''
    if parsed['kind']=='root':
        sha=override or head
    else:
        tail=parsed['tail']; chunks=tail.split('/')
        if SHA_RE.fullmatch(chunks[0]):
            sha=chunks[0]; scope='/'.join(chunks[1:])
        else:
            matches=[]
            for key,value in refs.items():
                if key.startswith('refs/heads/'): label=key[len('refs/heads/'):]
                elif key.startswith('refs/tags/') and not key.endswith('^{}'): label=key[len('refs/tags/'):]
                else: continue
                if tail==label or tail.startswith(label+'/'):
                    matches.append((len(label),refs.get(key+'^{}',value),tail[len(label):].lstrip('/')))
            if not matches: raise AuditError('URL branch/tag could not be resolved; do not guess')
            best=max(x[0] for x in matches); matches=[x for x in matches if x[0]==best]
            if len({(x[1],x[2]) for x in matches})>1: raise AuditError('Ambiguous branch/tag URL')
            _,sha,scope=matches[0]
        sha=override or sha
    if not sha or not SHA_RE.fullmatch(sha): raise AuditError('Full commit could not be resolved')
    if scope: valid_repo_path(scope)
    if parsed['kind']=='blob' and not scope: raise AuditError('Blob URL needs a path')
    return sha,scope

def selected(path: str,scope: str) -> tuple[bool,str]:
    if not scope or path==scope or path.startswith(scope.rstrip('/')+'/'): return True,'primary'
    # Ancestor-level metadata plus repository-wide CI/config. Other shared code is added explicitly.
    ancestors=['']
    pieces=scope.split('/')[:-1]
    for i in range(1,len(pieces)+1): ancestors.append('/'.join(pieces[:i])+'/')
    for a in ancestors:
        if not path.startswith(a): continue
        rest=path[len(a):]
        if '/' not in rest or rest.startswith(('.github/','.agents/','.codex/','.claude/')):
            return True,'shared_candidate'
    return False,'out_of_scope'

def add_bytes(root: Path,entry: dict,data: bytes|None) -> dict:
    item=dict(entry); valid_repo_path(item['path'])
    if data is None:
        item.update(content_path=None,sha256=None,text=False,line_count=None)
        return item
    blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    if blob!=entry['blob_sha']: raise AuditError('Git blob hash mismatch: '+entry['path'])
    h=digest(data); rel='blobs/'+h
    dest=within(root,rel); dest.parent.mkdir(parents=True,exist_ok=True)
    if not dest.exists(): dest.write_bytes(data)
    try:
        text=data.decode('utf-8'); is_text=b'\0' not in data
    except UnicodeError:
        text=''; is_text=False
    kind=item.get('kind','blob')
    if data.startswith(b'version https://git-lfs.github.com/spec/v1'): kind='lfs_pointer'
    item.update(kind=kind,sha256=h,content_path=rel,text=is_text and kind=='blob',
                line_count=len(text.splitlines()) if is_text and kind=='blob' else None)
    return item

def snapshot(root: Path,repo: str,sha: str,scope: str,gitdir: Path,profile: str,mode: str,origin: str,kind: str='tree',notes: list|None=None) -> dict:
    rows=run_git(['ls-tree','-r','-z','-l','--full-tree',sha],gitdir).split(b'\0')
    full=[]; skipped=[]
    for row in rows:
        if not row: continue
        head,rawpath=row.split(b'\t',1)
        permissions,objtype,blob,size=head.decode('ascii').split()
        try:
            path=valid_repo_path(rawpath.decode('utf-8'))
        except (UnicodeError,AuditError):
            # One odd name must not abort the whole audit; it becomes a reported limitation instead.
            skipped.append(rawpath.decode('utf-8','replace')); continue
        full.append({'path':path,'mode':permissions,'object_type':objtype,'blob_sha':blob,
                     'size':0 if size=='-' else int(size)})
    if len(full)>MAX_FILES: raise AuditError('File limit exceeded; narrow scope or partition explicitly')
    if scope and not any(i['path']==scope or i['path'].startswith(scope+'/') for i in full):
        raise AuditError('Requested path not present at pinned commit')
    planned=[]; total=0
    for row in full:
        take,role=selected(row['path'],scope)
        if not take: continue
        kind2='submodule' if row['mode']=='160000' else 'symlink' if row['mode']=='120000' else 'blob'
        entry={**row,'kind':kind2,'scope_role':role}
        fetch=False
        if kind2=='submodule': entry['limitation']='Submodule contents not fetched'
        elif row['size']>MAX_FILE or total+row['size']>MAX_TOTAL: entry['limitation']='Content excluded by explicit byte budget'
        else: fetch=True; total+=row['size']
        planned.append((entry,fetch))
    contents=read_blobs(gitdir,[e['blob_sha'] for e,f in planned if f])
    entries=[add_bytes(root,e,contents[e['blob_sha']] if f else None) for e,f in planned]
    atomic_json(root/'full-tree.json',full)
    limitations=list(notes or [])
    if skipped: limitations.append(f'{len(skipped)} repository paths skipped: not valid UTF-8 or unsafe names: '+'; '.join(skipped[:20]))
    manifest={'repo':repo,'commit':sha,'scope':scope,'url':f'https://github.com/{repo}',
              'profile':profile,'mode':mode,'created_at':now(),'origin':origin,
              'input_kind':kind,'static_only':True,'tree_complete':not skipped,
              'limits':{'max_file_bytes':MAX_FILE,'max_total_bytes':MAX_TOTAL,'max_files':MAX_FILES},
              'limitations':limitations,
              'scope_note':'Primary path and ancestor metadata/CI candidates. Trace other shared dependencies explicitly.'}
    initialize(root,manifest,entries)
    return {'workspace':str(root),'commit':sha,'scope':scope,'inventory_items':len(entries),
            'source_bytes':total,'limitations':limitations}

def import_connector(root: Path,package: Path,profile: str,mode: str) -> dict:
    obj=json.loads(package.read_text(encoding='utf-8-sig'))
    if obj.get('tree_complete') is not True or not SHA_RE.fullmatch(obj.get('commit','')):
        raise AuditError('Connector import requires full commit and explicit complete tree')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',obj.get('repo','')):
        raise AuditError('Invalid connector repository')
    entries=[]; seen=set(); total=0
    if len(obj.get('files',[]))>MAX_FILES: raise AuditError('Connector file limit exceeded')
    for row in obj.get('files',[]):
        path=valid_repo_path(row['path'])
        if path in seen: raise AuditError('Duplicate connector path')
        seen.add(path); data=None
        if row.get('local_file'):
            local=within(package.parent,row['local_file'])
            if local.stat().st_size>MAX_FILE or total+local.stat().st_size>MAX_TOTAL:
                raise AuditError('Connector byte budget exceeded')
            data=local.read_bytes(); total+=len(data)
        elif not row.get('limitation'): raise AuditError('Missing connector bytes without limitation')
        entries.append(add_bytes(root,{k:v for k,v in row.items() if k!='local_file'},data))
    manifest={'repo':obj['repo'],'commit':obj['commit'],'scope':obj.get('scope',''),
              'url':'https://github.com/'+obj['repo'],'profile':profile,'mode':mode,
              'created_at':now(),'origin':'connector','tree_complete':True,
              'static_only':True,'limitations':[],
              'scope_note':'Completeness is asserted by the authorized connector acquisition; independently review pagination.'}
    initialize(root,manifest,entries)
    return {'workspace':str(root),'commit':obj['commit'],'inventory_items':len(entries),'source_bytes':total}

def default_workspace(label: str) -> Path:
    base=Path(os.environ.get('REPO_DENETLE_ROOT') or Path.home()/'repo-denetle-calisma')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    return base/(re.sub(r'[^A-Za-z0-9_.-]+','-',label).strip('-')+'-'+stamp)

def check_workspace(root: Path,local_git: Path|None=None) -> list[str]:
    """Hard stop only inside the audited worktree; an unrelated ancestor repository is a note."""
    if root.exists(): raise AuditError('Output must be a NEW workspace; use control.py to resume existing runs')
    real=root.resolve()  # expands Windows 8.3 short names (OZANBE~1) before comparing
    if local_git is not None:
        src=local_git.resolve(); tree=src.parent if src.name=='.git' else src
        if real==tree or tree in real.parents: raise AuditError('Workspace must be outside the audited repository')
    return [f'Workspace lies inside an unrelated Git worktree ({p}); source bytes are stored by hash, no checkout.'
            for p in root.parents if (p/'.git').exists()]

def main() -> int:
    utf8_stdio()
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--url'); g.add_argument('--local-git',type=Path); g.add_argument('--connector-import',type=Path)
    p.add_argument('--out',type=Path,help='new workspace folder (default: $REPO_DENETLE_ROOT or ~/repo-denetle-calisma/<repo>-<time>)')
    p.add_argument('--ref'); p.add_argument('--scope',default='')
    p.add_argument('--repo',default='local/source'); p.add_argument('--profile',choices=('guvence','dengeli','derin'),default='guvence')
    p.add_argument('--mode',choices=('native','sequential'),default='native')
    a=p.parse_args()
    try:
        parsed=parse_url(a.url) if a.url else None
        label=parsed['repo'] if parsed else a.repo if a.local_git else 'connector'
        root=(a.out or default_workspace(label)).absolute()
        notes=check_workspace(root,a.local_git)
        root.mkdir(parents=True)
        if a.connector_import:
            result=import_connector(root,a.connector_import.resolve(),a.profile,a.mode)
        elif a.local_git:
            gitdir=a.local_git.resolve()
            if (gitdir/'.git').is_dir(): gitdir=gitdir/'.git'
            ref=a.ref or 'HEAD'
            if ref!='HEAD' and not SHA_RE.fullmatch(ref): raise AuditError('--ref requires full SHA')
            sha=run_git(['rev-parse','--verify',ref+'^{commit}'],gitdir).decode().strip()
            result=snapshot(root,a.repo,sha,a.scope,gitdir,a.profile,a.mode,'local_git',notes=notes)
        else:
            listing=run_git(['ls-remote','--symref',parsed['remote']]).decode('utf-8')
            sha,scope=resolve_ref(parsed,listing,a.ref)
            gitdir=root/'source.git'; run_git(['init','--bare',str(gitdir)])
            run_git(['fetch','--depth=1','--no-tags',parsed['remote'],sha],gitdir)
            actual=run_git(['rev-parse','--verify','FETCH_HEAD^{commit}'],gitdir).decode().strip()
            if actual!=sha: raise AuditError('Fetched commit differs from pinned commit')
            result=snapshot(root,parsed['repo'],sha,scope,gitdir,a.profile,a.mode,'github_git',parsed['kind'],notes)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    except (AuditError,OSError,ValueError,KeyError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
