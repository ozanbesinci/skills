#!/usr/bin/env python3
"""Make repo-denetle visible to Claude Code, Codex and Antigravity.

Default mode keeps ONE real copy (this package folder) and points every host at it:
  Claude Code  ~/.claude/skills/repo-denetle        junction (Windows) / symlink
  Codex        ~/.codex/skills/repo-denetle         junction (Windows) / symlink
  Antigravity  ~/.gemini/config/skills.json         entry for this package's parent folder
Antigravity's skill discovery does not follow junctions (measured 2026-10-23), so it gets a
declared `skills.json` entry instead. Anything already in the way is moved to
~/.repo-denetle-yedek/<time>/, never left inside a skills folder where a host would load it
as a duplicate skill. No downloads, no model/permission/credential settings.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

NAME='repo-denetle'
ROOT=Path(__file__).resolve().parent.parent
TARGETS={
    'claude': ('.claude','skills'),
    'codex': ('.codex','skills'),
    'antigravity': ('.gemini','config','skills'),
}
AG_JSON=('.gemini','config','skills.json')

def is_link(path: Path) -> bool:
    # Path.is_symlink() is False for a Windows junction; check the reparse-point attribute too.
    try: st=os.lstat(path)
    except OSError: return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st,'st_file_attributes',0) & 0x400)

def link_target(path: Path) -> Path|None:
    try: return Path(os.path.realpath(path)) if is_link(path) else None
    except OSError: return None

def make_link(src: Path,dst: Path) -> None:
    if os.name=='nt':
        import _winapi
        _winapi.CreateJunction(str(src),str(dst))  # no admin/developer-mode needed, unlike symlinks
    else:
        os.symlink(src,dst,target_is_directory=True)

def remove_link(path: Path) -> None:
    # rmdir/unlink removes only the link entry; shutil.rmtree would follow a junction into the source.
    if os.name=='nt': os.rmdir(path)
    else: path.unlink()

def source() -> Path:
    return Path(os.path.realpath(ROOT))

def ag_entry() -> dict:
    return {'path':source().parent.as_posix(),'include_only':[NAME]}

def read_config(path: Path) -> dict:
    if not path.exists(): return {}
    data=json.loads(path.read_text(encoding='utf-8-sig') or '{}')
    if not isinstance(data,dict) or not isinstance(data.get('entries',[]),list):
        raise RuntimeError('Unexpected skills.json shape, not touching it: '+str(path))
    return data

def write_config(path: Path,data: dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.skills-',dir=str(path.parent))
    with os.fdopen(fd,'w',encoding='utf-8') as fh: fh.write(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    os.replace(tmp,path)

def clear_path(dst: Path,backup: Path,row: dict) -> None:
    """Move whatever occupies dst out of the skills folder (a link is just removed)."""
    if not os.path.lexists(dst): return
    if is_link(dst):
        row['removed_link']=str(link_target(dst)); remove_link(dst)
    else:
        backup.parent.mkdir(parents=True,exist_ok=True); os.replace(dst,backup); row['backup']=str(backup)

def register_antigravity(home: Path,backup_root: Path,dry_run: bool) -> dict:
    cfg=home.joinpath(*AG_JSON); folder=home.joinpath(*TARGETS['antigravity'])/NAME
    row={'target':'antigravity','path':str(cfg)}
    data=read_config(cfg); entries=data.setdefault('entries',[]); want=ag_entry()
    same=[e for e in entries if isinstance(e,dict) and e.get('path')==want['path']]
    covered=any('include_only' not in e or NAME in e.get('include_only',[]) for e in same)
    stale=os.path.lexists(folder)
    if covered and not stale: return {**row,'status':'already_installed'}
    if dry_run: return {**row,'status':'planned'}
    clear_path(folder,backup_root/'antigravity'/NAME,row)
    if not covered:
        if cfg.exists():
            b=backup_root/'antigravity'/'skills.json'; b.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(cfg,b); row['config_backup']=str(b)
        if same: same[0]['include_only']=[*same[0]['include_only'],NAME]
        else: entries.append(want)
        write_config(cfg,data)
    return {**row,'status':'registered'}

def install(home: Path,targets: list[str],mode: str='link',dry_run: bool=False,backup_root: Path|None=None) -> list[dict]:
    if sys.version_info<(3,10): raise RuntimeError('Python 3.10+ required')
    if not (ROOT/'SKILL.md').is_file(): raise RuntimeError('SKILL.md not found next to scripts/')
    home=home.expanduser().absolute()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup_root=(backup_root or home/'.repo-denetle-yedek')/stamp
    src=source(); results=[]
    for target in targets:
        if target=='antigravity' and mode=='link':
            results.append(register_antigravity(home,backup_root,dry_run)); continue
        dst=home.joinpath(*TARGETS[target])/NAME
        row={'target':target,'path':str(dst)}
        if is_link(dst) and link_target(dst)==src and mode=='link':
            results.append({**row,'status':'already_installed'}); continue
        if not is_link(dst) and os.path.lexists(dst) and Path(os.path.realpath(dst))==src:
            results.append({**row,'status':'already_at_source'}); continue
        if src==dst or src in dst.parents or dst in src.parents:
            raise RuntimeError('Install path overlaps the package folder: '+str(dst))
        if dry_run:
            results.append({**row,'status':'planned','replaces':str(dst) if os.path.lexists(dst) else None}); continue
        dst.parent.mkdir(parents=True,exist_ok=True)
        clear_path(dst,backup_root/target/NAME,row)
        try:
            if mode=='link': make_link(src,dst)
            else: shutil.copytree(src,dst,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.zip','tests'))
        except Exception:
            if 'backup' in row and not os.path.lexists(dst): os.replace(row['backup'],dst)
            raise
        if not (dst/'SKILL.md').is_file(): raise RuntimeError('Installed path has no SKILL.md: '+str(dst))
        results.append({**row,'status':'linked' if mode=='link' else 'copied'})
    return results

def uninstall(home: Path,targets: list[str],dry_run: bool=False) -> list[dict]:
    home=home.expanduser().absolute(); src=source(); results=[]
    for target in targets:
        if target=='antigravity':
            cfg=home.joinpath(*AG_JSON); row={'target':target,'path':str(cfg)}
            data=read_config(cfg); entries=data.get('entries',[]); want=ag_entry(); changed=False
            for e in list(entries):
                if isinstance(e,dict) and e.get('path')==want['path'] and NAME in e.get('include_only',[]):
                    e['include_only']=[x for x in e['include_only'] if x!=NAME]; changed=True
                    if not e['include_only']: entries.remove(e)
            if changed and not dry_run:
                if entries or set(data)-{'entries'}: write_config(cfg,data)
                else: cfg.unlink()
            results.append({**row,'status':('planned_removal' if dry_run else 'removed') if changed else 'absent'})
        dst=home.joinpath(*TARGETS[target])/NAME
        row={'target':target,'path':str(dst)}
        if not os.path.lexists(dst):
            if target!='antigravity': results.append({**row,'status':'absent'})
            continue
        if not is_link(dst) or link_target(dst)!=src:
            results.append({**row,'status':'left_untouched_not_our_link'}); continue
        if not dry_run: remove_link(dst)
        results.append({**row,'status':'planned_removal' if dry_run else 'removed'})
    return results

def main() -> int:
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='replace')
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--target',choices=('all',*TARGETS),default='all')
    p.add_argument('--mode',choices=('link','copy'),default='link',help='copy only for distributing to another machine')
    p.add_argument('--home',type=Path,default=Path.home())
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--uninstall',action='store_true',help='remove only links/entries that point to this package')
    a=p.parse_args()
    targets=list(TARGETS) if a.target=='all' else [a.target]
    try:
        rows=uninstall(a.home,targets,a.dry_run) if a.uninstall else install(a.home,targets,a.mode,a.dry_run)
        for row in rows:
            print(f"{row['status']}: {row['target']} -> {row['path']}")
            for key,label in (('backup','backup'),('config_backup','config backup'),('removed_link','replaced link that pointed to')):
                if row.get(key): print(f'  {label}: {row[key]}')
        if not a.uninstall and not a.dry_run:
            print('Complete. Open a NEW Claude Code / Codex / Antigravity session to load the skill.')
        return 0
    except (OSError,RuntimeError,ValueError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
