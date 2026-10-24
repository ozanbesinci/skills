import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import control as c
import source as s
import kur as ins

def try_symlink(link,target):
    try: link.symlink_to(target,target_is_directory=True)
    except OSError as exc: raise unittest.SkipTest('symlink privilege unavailable: '+str(exc))

SHA='a'*40
BYTES=b'def sample():\n    return 1\n'
HASH=c.digest(BYTES)
BLOB=hashlib.sha1(b'blob '+str(len(BYTES)).encode()+b'\0'+BYTES).hexdigest()

def fixture(root,mode='native'):
    (root/'blobs').mkdir(parents=True)
    (root/'blobs'/HASH).write_bytes(BYTES)
    inventory=[{'path':'src/a.py','blob_sha':BLOB,'sha256':HASH,'content_path':'blobs/'+HASH,
                'text':True,'line_count':2,'size':len(BYTES),'kind':'blob'}]
    manifest={'repo':'a/b','commit':SHA,'scope':'','mode':mode,'profile':'guvence','static_only':True}
    c.initialize(root,manifest,inventory)

def ev():
    return {'path':'src/a.py','start':1,'end':2,'sha256':HASH}

def side(root,stage,findings=None,mode='native'):
    report=f'# {stage} Report\n\nCommit: {SHA}\n\n'+('SIRALI CALISMA\n' if mode=='sequential' else '')
    report+='Static fixture report for structural testing only. This is synthetic source and not a real audit.\n'
    for f in findings or []: report+=f['id']+' '+f['title']+'\n'
    (root/'reports'/f'{stage}.md').write_text(report)
    data={'stage':stage,'commit':SHA,'report_path':f'reports/{stage}.md','mode':'static',
          'coverage':[{**ev(),'status':'reviewed'}],'findings':findings or [],'limitations':[],
          'telemetry':{'actual_model':None,'actual_effort':None}}
    c.atomic_json(root/'findings'/f'{stage}.json',data)
    if stage=='DISCOVERY': (root/'context.md').write_text('Project context '+SHA)
    if stage=='PLAN':
        for name in (*c.AUDITS,'LIFE'): (root/'prompts'/f'{name}.md').write_text('Prompt '+name+' '+SHA)
    return data

def finding(stage='BIZ'):
    d={'id':stage+'-001','severity':'P2','evidence':[ev()]}
    for k in ('title','kind','confidence','evidence_level','observed','expected','impact','recommendation','acceptance'):
        d[k]='Synthetic '+k
    return d

def reach(root,through='QA',with_finding=False):
    for stage in ('DISCOVERY','PLAN',*c.AUDITS):
        side(root,stage,[finding()] if stage=='BIZ' and with_finding else [])
        c.accept(root,stage)
        if stage==through: return

def complete(root,with_finding=False):
    reach(root,with_finding=with_finding)
    d=side(root,'VERIFY')
    d['verification']=[{'finding_id':'BIZ-001','status':'confirmed','reason':'Fixture verified','evidence':[ev()]}] if with_finding else []
    c.atomic_json(root/'findings/VERIFY.json',d); c.accept(root,'VERIFY')
    side(root,'LIFE')
    cons=[{'id':'CONS-001','source_ids':['BIZ-001'],'disposition':'open','reason':'Fixture retained'}] if with_finding else []
    c.atomic_json(root/'findings/consolidated.json',cons)
    for name in ('roadmap.md','executive-summary.md'): (root/name).write_text('Summary '+SHA)
    c.accept(root,'LIFE')
    approve_fixture(root)


def approve_fixture(root):
    """Synthetic review fixture only; never a substitute for a real output review."""
    review=c.review_template(root)
    review['status']='approved'; review['reviewer']['name']='Synthetic test fixture'
    for row in review['checks'].values(): row.update(status='passed',reason='Synthetic fixture checked')
    for row in review['findings']: row.update(status='confirmed',reason='Synthetic fixture',evidence=[ev()])
    c.atomic_json(root/'review.json',review)
    return review

class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)/'run'; fixture(self.root)
    def tearDown(self): self.tmp.cleanup()
    def assert_error(self,fn,*args):
        with self.assertRaises(c.AuditError): fn(*args)

class WorkflowTests(Temp):
    def test_initialize(self): self.assertEqual(c.load(self.root)[0]['commit'],SHA)
    def test_refuse_overwrite(self): self.assert_error(c.initialize,self.root,{'commit':SHA},[])
    def test_no_premature_audit(self): self.assert_error(c.accept,self.root,'BIZ')
    def test_no_premature_life(self): self.assert_error(c.accept,self.root,'LIFE')
    def test_no_premature_finalize(self): self.assert_error(c.finalize,self.root)
    def test_discovery_accept(self): side(self.root,'DISCOVERY'); self.assertEqual(c.accept(self.root,'DISCOVERY')['status'],'accepted')
    def test_missing_discovery_coverage(self):
        d=side(self.root,'DISCOVERY'); d['coverage']=[]; c.atomic_json(self.root/'findings/DISCOVERY.json',d)
        self.assert_error(c.accept,self.root,'DISCOVERY')
    def test_discovery_context_required(self):
        side(self.root,'DISCOVERY'); (self.root/'context.md').unlink(); self.assert_error(c.accept,self.root,'DISCOVERY')
    def test_plan_prompts_required(self):
        reach(self.root,'DISCOVERY'); side(self.root,'PLAN'); (self.root/'prompts/LIFE.md').unlink(); self.assert_error(c.accept,self.root,'PLAN')
    def test_wrong_commit(self):
        d=side(self.root,'DISCOVERY'); d['commit']='b'*40; c.atomic_json(self.root/'findings/DISCOVERY.json',d); self.assert_error(c.accept,self.root,'DISCOVERY')
    def test_attempt_limit(self):
        for _ in range(2): self.assert_error(c.accept,self.root,'DISCOVERY')
        side(self.root,'DISCOVERY'); self.assert_error(c.accept,self.root,'DISCOVERY')
    def test_full_empty_findings(self):
        complete(self.root); result=c.finalize(self.root); self.assertTrue(Path(result['archive']).exists())
    def test_full_with_findings(self):
        complete(self.root,True); self.assertEqual(c.finalize(self.root)['status'],'STRUCTURALLY_VALIDATED_STATIC_AUDIT')
    def test_archive_excludes_source(self):
        complete(self.root); result=c.finalize(self.root)
        with zipfile.ZipFile(result['archive']) as z:
            self.assertFalse(any(x.startswith(('blobs/','source.git/')) for x in z.namelist()))
            self.assertIn('reports/LIFE.md',z.namelist()); self.assertIsNone(z.testzip())
    def test_report_change_detected(self):
        reach(self.root,'DISCOVERY'); (self.root/'reports/DISCOVERY.md').write_text('changed'); self.assert_error(c.accept,self.root,'PLAN')
    def test_reopen_invalidates_downstream(self):
        complete(self.root); result=c.reopen(self.root,'BIZ','New evidence')
        self.assertEqual(set(result['invalidated']),{'BIZ','VERIFY','LIFE'})
        self.assertEqual(c.load(self.root)[0]['stages']['ARCH']['status'],'accepted')
    def test_source_tamper(self):
        (self.root/'blobs'/HASH).write_bytes(b'changed'); self.assert_error(c.get_source,self.root,c.load(self.root)[2][0])
    def test_inventory_tamper(self):
        (self.root/'inventory.json').write_text('[]'); self.assert_error(c.load,self.root)
    def test_dispatch_limit(self):
        state,_,_=c.load(self.root); state['dispatch_limit']=1; c.atomic_json(self.root/'state.json',state)
        c.dispatch(self.root,'biz'); self.assert_error(c.dispatch,self.root,'biz')
    def test_unknown_role(self): self.assert_error(c.dispatch,self.root,'outsider')
    def test_telemetry_not_fabricated(self): self.assertIsNone(c.dispatch(self.root,'biz')['actual_model'])
    def test_verification_must_cover_findings(self):
        reach(self.root,with_finding=True); d=side(self.root,'VERIFY'); d['verification']=[]
        c.atomic_json(self.root/'findings/VERIFY.json',d); self.assert_error(c.accept,self.root,'VERIFY')
    def test_consolidation_cannot_drop_findings(self):
        complete(self.root,True); c.reopen(self.root,'LIFE','Check omission')
        c.atomic_json(self.root/'findings/consolidated.json',[]); self.assert_error(c.accept,self.root,'LIFE')
    def test_sequential_limitation_required(self):
        root=Path(self.tmp.name)/'sequential'; fixture(root,'sequential'); side(root,'DISCOVERY')
        self.assert_error(c.accept,root,'DISCOVERY')
    def test_sequential_label_accepted(self):
        root=Path(self.tmp.name)/'sequential'; fixture(root,'sequential'); side(root,'DISCOVERY',mode='sequential'); c.accept(root,'DISCOVERY')

class EvidenceTests(Temp):
    def test_valid_range(self): c.evidence(self.root,ev(),{'src/a.py':c.load(self.root)[2][0]})
    def test_unknown_path(self): self.assert_error(c.evidence,self.root,{**ev(),'path':'missing'}, {})
    def test_bad_hash(self): self.assert_error(c.evidence,self.root,{**ev(),'sha256':'x'}, {'src/a.py':c.load(self.root)[2][0]})
    def test_bad_range(self): self.assert_error(c.evidence,self.root,{**ev(),'end':3}, {'src/a.py':c.load(self.root)[2][0]})
    def test_bad_quote(self): self.assert_error(c.evidence,self.root,{**ev(),'quote':'return 2'}, {'src/a.py':c.load(self.root)[2][0]})
    def test_good_quote(self): c.evidence(self.root,{**ev(),'quote':'return 1'}, {'src/a.py':c.load(self.root)[2][0]})
    def test_coverage_does_not_count_gap(self):
        summary=c.validate_coverage(self.root,[{**ev(),'start':2,'status':'reviewed'}],{'src/a.py':c.load(self.root)[2][0]})
        self.assertEqual(summary['fully_reviewed_text_files'],0)
    def test_traversal_blocked(self): self.assert_error(c.within,self.root,'../secret')
    def test_absolute_blocked(self): self.assert_error(c.within,self.root,'/etc/passwd')
    def test_windows_path_blocked(self): self.assert_error(c.within,self.root,'C:/secret')
    def test_symlink_blocked(self):
        try_symlink(self.root/'link',self.root/'blobs')
        self.assert_error(c.within,self.root,'link/'+HASH)

class UrlTests(unittest.TestCase):
    def test_root(self): self.assertEqual(s.parse_url('https://github.com/a/b')['repo'],'a/b')
    def test_git_suffix(self): self.assertEqual(s.parse_url('https://github.com/a/b.git')['repo'],'a/b')
    def test_tree(self): self.assertEqual(s.parse_url('https://github.com/a/b/tree/main/src')['tail'],'main/src')
    def test_blob(self): self.assertEqual(s.parse_url('https://github.com/a/b/blob/main/a.py')['kind'],'blob')
    def test_http(self):
        with self.assertRaises(c.AuditError): s.parse_url('http://github.com/a/b')
    def test_bad_host(self):
        with self.assertRaises(c.AuditError): s.parse_url('https://github.com.evil/a/b')
    def test_credentials(self):
        with self.assertRaises(c.AuditError): s.parse_url('https://secret@github.com/a/b')
    def test_encoded_traversal(self):
        with self.assertRaises(c.AuditError): s.parse_url('https://github.com/a/b/tree/main/%2e%2e/x')
    def test_query(self):
        with self.assertRaises(c.AuditError): s.parse_url('https://github.com/a/b?token=x')
    def test_default_head(self): self.assertEqual(s.resolve_ref(s.parse_url('https://github.com/a/b'),SHA+'\tHEAD\n'),(SHA,''))
    def test_slash_branch_longest(self):
        parsed=s.parse_url('https://github.com/a/b/tree/feature/test/src')
        self.assertEqual(s.resolve_ref(parsed,SHA+'\trefs/heads/feature/test\n'),(SHA,'src'))
    def test_annotated_tag(self):
        parsed=s.parse_url('https://github.com/a/b/tree/v1/src')
        listing='b'*40+'\trefs/tags/v1\n'+SHA+'\trefs/tags/v1^{}\n'
        self.assertEqual(s.resolve_ref(parsed,listing),(SHA,'src'))
    def test_explicit_sha(self):
        self.assertEqual(s.resolve_ref(s.parse_url('https://github.com/a/b/tree/'+SHA+'/x'),''),(SHA,'x'))
    def test_branch_unresolved(self):
        with self.assertRaises(c.AuditError): s.resolve_ref(s.parse_url('https://github.com/a/b/tree/nope/src'),'')
    def test_ambiguous_ref(self):
        listing=SHA+'\trefs/heads/v1\n'+'b'*40+'\trefs/tags/v1\n'
        with self.assertRaises(c.AuditError): s.resolve_ref(s.parse_url('https://github.com/a/b/tree/v1'),listing)
    def test_scope_selection(self):
        self.assertTrue(s.selected('.github/workflows/ci.yml','pkg/a')[0])
        self.assertTrue(s.selected('pkg/a/code.py','pkg/a')[0])
        self.assertFalse(s.selected('other/code.py','pkg/a')[0])

class SourceTests(Temp):
    def test_correct_blob(self):
        row=s.add_bytes(self.root,{'path':'b.py','blob_sha':BLOB,'kind':'blob'},BYTES)
        self.assertEqual(row['sha256'],HASH)
    def test_wrong_blob(self): self.assert_error(s.add_bytes,self.root,{'path':'b.py','blob_sha':'0'*40},BYTES)
    def test_lfs_is_not_content(self):
        data=b'version https://git-lfs.github.com/spec/v1\noid sha256:abc\n'
        blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        row=s.add_bytes(self.root,{'path':'a.bin','blob_sha':blob,'kind':'blob'},data)
        self.assertFalse(row['text']); self.assertEqual(row['kind'],'lfs_pointer')
    def test_connector_import(self):
        acq=Path(self.tmp.name)/'acq'; acq.mkdir(); (acq/'a.txt').write_bytes(BYTES)
        obj={'repo':'a/b','commit':SHA,'tree_complete':True,'scope':'','files':[{'path':'a.py','blob_sha':BLOB,'kind':'blob','local_file':'a.txt'}]}
        c.atomic_json(acq/'acq.json',obj); out=Path(self.tmp.name)/'import'
        s.import_connector(out,acq/'acq.json','guvence','native'); self.assertEqual(len(c.load(out)[2]),1)
    def test_connector_incomplete_rejected(self):
        p=Path(self.tmp.name)/'acq.json'; c.atomic_json(p,{'tree_complete':False,'commit':SHA})
        self.assert_error(s.import_connector,Path(self.tmp.name)/'import',p,'guvence','native')
    @unittest.skipUnless(shutil.which('git'),'Git not installed')
    def test_git_snapshot_no_checkout(self):
        repo=Path(self.tmp.name)/'repo'; repo.mkdir()
        def git(*args):
            return subprocess.run(['git','-C',str(repo),*args],capture_output=True,check=True).stdout
        git('init'); (repo/'a.py').write_bytes(BYTES); git('add','a.py')
        git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture')
        sha=git('rev-parse','HEAD').decode().strip(); out=Path(self.tmp.name)/'snapshot'; out.mkdir()
        s.snapshot(out,'a/b',sha,'',repo/'.git','guvence','native','local_git')
        self.assertEqual(c.load(out)[1]['commit'],sha); self.assertFalse((out/'a.py').exists())

class InstallerTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.home=Path(self.tmp.name)/'home'
    def tearDown(self):
        ins.uninstall(self.home,list(ins.TARGETS)); self.tmp.cleanup()
    def skill(self,target): return self.home.joinpath(*ins.TARGETS[target])/'repo-denetle'
    def test_dry_run(self):
        self.assertEqual(len(ins.install(self.home,list(ins.TARGETS),dry_run=True)),3); self.assertFalse(self.home.exists())
    def test_link_all_three(self):
        rows=ins.install(self.home,list(ins.TARGETS))
        self.assertEqual([r['status'] for r in rows],['linked','linked','registered'])
        for t in ('claude','codex'):
            self.assertTrue(ins.is_link(self.skill(t))); self.assertTrue((self.skill(t)/'SKILL.md').is_file())
        self.assertFalse(os.path.lexists(self.skill('antigravity')))
        cfg=json.loads((self.home/'.gemini/config/skills.json').read_text(encoding='utf-8'))
        self.assertEqual(cfg['entries'],[ins.ag_entry()]); self.assertTrue((Path(cfg['entries'][0]['path'])/'repo-denetle'/'SKILL.md').is_file())
    def test_antigravity_registry_keeps_foreign_entries(self):
        cfg=self.home/'.gemini/config/skills.json'; cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({'entries':[{'path':'~/baska'}],'inherits':[]}),encoding='utf-8')
        stale=self.skill('antigravity'); stale.mkdir(parents=True)
        row=ins.install(self.home,['antigravity'])[0]; self.assertEqual(row['status'],'registered')
        self.assertTrue(row['config_backup']); self.assertFalse(stale.exists())
        self.assertEqual(ins.install(self.home,['antigravity'])[0]['status'],'already_installed')
        ins.uninstall(self.home,['antigravity'])
        self.assertEqual(json.loads(cfg.read_text(encoding='utf-8')),{'entries':[{'path':'~/baska'}],'inherits':[]})
    def test_idempotent(self):
        ins.install(self.home,['claude']); self.assertEqual(ins.install(self.home,['claude'])[0]['status'],'already_installed')
    def test_existing_copy_moved_out_of_skills_dir(self):
        old=self.skill('codex'); old.mkdir(parents=True); (old/'SKILL.md').write_text('---\nname: repo-denetle\n---\nold')
        row=ins.install(self.home,['codex'])[0]
        self.assertTrue(ins.is_link(old)); self.assertEqual(Path(row['backup']).relative_to(self.home).parts[0],'.repo-denetle-yedek')
        self.assertTrue((Path(row['backup'])/'SKILL.md').read_text().endswith('old'))
        self.assertEqual([x.name for x in old.parent.iterdir()],['repo-denetle'])
    def test_uninstall_keeps_source(self):
        ins.install(self.home,['claude']); ins.uninstall(self.home,['claude'])
        self.assertFalse(os.path.lexists(self.skill('claude'))); self.assertTrue((ins.ROOT/'SKILL.md').is_file())
    def test_uninstall_ignores_foreign_folder(self):
        d=self.skill('claude'); d.mkdir(parents=True)
        self.assertEqual(ins.uninstall(self.home,['claude'])[0]['status'],'left_untouched_not_our_link'); self.assertTrue(d.is_dir())
    def test_copy_mode(self):
        ins.install(self.home,['antigravity'],mode='copy'); d=self.skill('antigravity')
        self.assertFalse(ins.is_link(d)); self.assertTrue((d/'scripts/control.py').is_file()); self.assertFalse((d/'tests').exists())
    def test_settings_untouched(self):
        (self.home/'.codex').mkdir(parents=True); cfg=self.home/'.codex/config.toml'; cfg.write_text('existing = true\n')
        ins.install(self.home,['codex']); self.assertEqual(cfg.read_text(),'existing = true\n')

class WindowsAndV11Tests(Temp):
    def test_check_costs_no_attempt(self):
        self.assert_error(c.check,self.root,'DISCOVERY')
        side(self.root,'DISCOVERY'); self.assertEqual(c.check(self.root,'DISCOVERY')['attempts_left'],2)
        self.assertFalse((self.root/'coverage.json').exists()); c.accept(self.root,'DISCOVERY')
    def test_reopen_restores_attempts_and_is_capped(self):
        reach(self.root,'DISCOVERY')
        for _ in range(3): c.reopen(self.root,'DISCOVERY','new evidence'); c.accept(self.root,'DISCOVERY')
        self.assertEqual(c.load(self.root)[0]['stages']['DISCOVERY']['status'],'accepted')
        self.assert_error(c.reopen,self.root,'DISCOVERY','again')
    def test_bom_and_crlf_report_accepted(self):
        side(self.root,'DISCOVERY'); rp=self.root/'reports/DISCOVERY.md'
        rp.write_bytes(b'\xef\xbb\xbf'+rp.read_text().replace('\n','\r\n').encode('utf-8')); c.accept(self.root,'DISCOVERY')
    def test_non_utf8_report_clear_error(self):
        side(self.root,'DISCOVERY'); (self.root/'reports/DISCOVERY.md').write_bytes(('Rapor '+SHA+' ').encode('utf-16')*5)
        with self.assertRaisesRegex(c.AuditError,'UTF-8'): c.check(self.root,'DISCOVERY')
    def test_quote_whitespace_tolerant(self):
        c.evidence(self.root,{**ev(),'quote':'def  sample():\n\treturn 1'},{'src/a.py':c.load(self.root)[2][0]})
    def test_telemetry_records_host_values(self):
        d=c.dispatch(self.root,'biz','opus','high'); row=c.telemetry(self.root,d['id'],'claude-opus-5-5',agent_id='A1',tokens=10)
        self.assertEqual((row['requested_model'],row['actual_model'],row['tokens']),('opus','claude-opus-5-5',10))
        self.assert_error(c.telemetry,self.root,'D-9999','x')
    def test_repo_path_with_colon_allowed_but_output_path_strict(self):
        self.assertEqual(c.valid_repo_path('docs/12:30 notlar.md'),'docs/12:30 notlar.md')
        self.assert_error(c.valid_path,'docs/a:b'); self.assert_error(c.valid_repo_path,'a/../b')
    def test_workspace_rules(self):
        repo=Path(self.tmp.name)/'repo'; (repo/'.git').mkdir(parents=True)
        self.assert_error(s.check_workspace,repo/'out',repo)
        notes=s.check_workspace(repo/'sub'/'out',None); self.assertTrue(notes and 'unrelated Git' in notes[0])
        self.assert_error(s.check_workspace,self.root,None)

def make_repo(base,files):
    repo=Path(base)/'repo'; repo.mkdir()
    def git(*args): return subprocess.run(['git','-C',str(repo),*args],capture_output=True,check=True).stdout
    git('init','-q')
    for name,data in files.items():
        (repo/name).parent.mkdir(parents=True,exist_ok=True); (repo/name).write_bytes(data)
    git('-c','core.autocrlf=false','add','-A')
    git('-c','core.autocrlf=false','-c','user.name=F','-c','user.email=f@example.invalid','commit','-qm','f')
    return repo,git('rev-parse','HEAD').decode().strip()

TR='satır ığüşöç İĞÜŞÖÇ 🚀\n'.encode('utf-8')

@unittest.skipUnless(shutil.which('git'),'Git not installed')
class GitBatchTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self): self.tmp.cleanup()
    def test_local_cli_ignores_replaced_commit(self):
        repo,sha=make_repo(self.tmp.name,{'a.py':BYTES})
        def git(*args): return subprocess.run(['git','-C',str(repo),*args],capture_output=True,check=True).stdout
        original_blob=git('rev-parse',sha+':a.py').decode().strip()
        (repo/'a.py').write_bytes(b'replacement commit\n'); git('add','a.py')
        git('-c','user.name=F','-c','user.email=f@example.invalid','commit','-qm','replacement')
        replacement=git('rev-parse','HEAD').decode().strip(); git('replace',sha,replacement)
        self.assertNotEqual(git('rev-parse',sha+':a.py').decode().strip(),original_blob)
        out=Path(self.tmp.name)/'ws'
        cp=subprocess.run([sys.executable,'-I',str(ROOT/'scripts/source.py'),'--local-git',str(repo),
                           '--ref',sha,'--out',str(out)],capture_output=True)
        self.assertEqual(cp.returncode,0,cp.stderr)
        _,manifest,inventory=c.load(out)
        self.assertEqual(manifest['commit'],sha)
        self.assertEqual(inventory[0]['blob_sha'],original_blob)
        self.assertEqual(c.get_source(out,inventory[0]),BYTES.decode())
    def test_snapshot_ignores_replaced_blob(self):
        repo,sha=make_repo(self.tmp.name,{'a.py':BYTES})
        def git(*args,stdin=None):
            return subprocess.run(['git','-C',str(repo),*args],input=stdin,capture_output=True,check=True).stdout
        blob=git('rev-parse',sha+':a.py').decode().strip()
        replacement=git('hash-object','-w','--stdin',stdin=b'replacement blob\n').decode().strip()
        git('replace',blob,replacement)
        self.assertNotEqual(git('cat-file','blob',blob),BYTES)
        out=Path(self.tmp.name)/'ws'; out.mkdir()
        s.snapshot(out,'a/b',sha,'',repo/'.git','guvence','native','local_git')
        self.assertEqual(c.get_source(out,c.load(out)[2][0]),BYTES.decode())
    def test_file_limit_applies_after_scope_selection(self):
        files={f'other/f{i}.txt':BYTES for i in range(4)}
        files.update({'pkg/a.py':BYTES,'README.md':b'shared metadata\n'})
        repo,sha=make_repo(self.tmp.name,files)
        with mock.patch.object(s,'MAX_FILES',2):
            for n,scope in enumerate(('pkg','pkg/a.py')):
                with self.subTest(scope=scope):
                    out=Path(self.tmp.name)/f'ws{n}'; out.mkdir()
                    result=s.snapshot(out,'a/b',sha,scope,repo/'.git','guvence','native','local_git')
                    self.assertEqual(result['inventory_items'],2)
                    self.assertEqual({i['path'] for i in c.load(out)[2]},{'pkg/a.py','README.md'})
                    self.assertEqual(len(json.loads((out/'full-tree.json').read_text(encoding='utf-8'))),len(files))
    def test_file_limit_still_rejects_oversized_scope(self):
        repo,sha=make_repo(self.tmp.name,{'pkg/a.py':BYTES,'pkg/b.py':BYTES})
        with mock.patch.object(s,'MAX_FILES',1):
            for n,scope in enumerate(('','pkg')):
                with self.subTest(scope=scope):
                    out=Path(self.tmp.name)/f'ws{n}'; out.mkdir()
                    with self.assertRaisesRegex(c.AuditError,'File limit exceeded'):
                        s.snapshot(out,'a/b',sha,scope,repo/'.git','guvence','native','local_git')
                    self.assertFalse((out/'blobs').exists())
    def test_file_limit_counts_shared_candidates(self):
        repo,sha=make_repo(self.tmp.name,{'pkg/a.py':BYTES,'README.md':BYTES})
        out=Path(self.tmp.name)/'ws'; out.mkdir()
        with mock.patch.object(s,'MAX_FILES',1):
            with self.assertRaisesRegex(c.AuditError,'File limit exceeded'):
                s.snapshot(out,'a/b',sha,'pkg/a.py',repo/'.git','guvence','native','local_git')
    def test_batch_snapshot_many_files_and_budget(self):
        files={f'd/f{i}.txt':f'line {i}\n'.encode() for i in range(60)}
        files.update({'tr.md':TR,'dup1.txt':b'same\n','dup2.txt':b'same\n','empty.txt':b'','big.bin':b'\0'*(s.MAX_FILE+1)})
        repo,sha=make_repo(self.tmp.name,files); out=Path(self.tmp.name)/'ws'; out.mkdir()
        r=s.snapshot(out,'a/b',sha,'',repo/'.git','guvence','native','local_git')
        inv={i['path']:i for i in c.load(out)[2]}; self.assertEqual(r['inventory_items'],len(files))
        self.assertEqual(c.get_source(out,inv['tr.md']),TR.decode()); self.assertEqual(inv['empty.txt']['line_count'],0)
        self.assertIn('byte budget',inv['big.bin']['limitation']); self.assertEqual(inv['big.bin']['size'],s.MAX_FILE+1)
        self.assertEqual(inv['dup1.txt']['sha256'],inv['dup2.txt']['sha256'])
    def test_cli_read_is_utf8_on_a_pipe(self):
        repo,sha=make_repo(self.tmp.name,{'tr.md':TR}); out=Path(self.tmp.name)/'ws'; out.mkdir()
        s.snapshot(out,'a/b',sha,'',repo/'.git','guvence','native','local_git')
        env={k:v for k,v in os.environ.items() if k not in ('PYTHONUTF8','PYTHONIOENCODING')}
        cp=subprocess.run([sys.executable,'-I',str(ROOT/'scripts/control.py'),'read',str(out),'tr.md'],capture_output=True,env=env)
        self.assertEqual(cp.returncode,0,cp.stderr); self.assertEqual(cp.stdout.decode('utf-8').replace('\r\n','\n'),'1: '+TR.decode())
        f=Path(self.tmp.name)/'r.txt'
        subprocess.run([sys.executable,'-I',str(ROOT/'scripts/control.py'),'read',str(out),'tr.md','--out',str(f)],check=True,capture_output=True,env=env)
        self.assertEqual(f.read_text(encoding='utf-8'),'1: '+TR.decode())
    def test_cli_source_isolated_mode_and_workspace_note(self):
        repo,sha=make_repo(self.tmp.name,{'a.py':BYTES}); out=Path(self.tmp.name)/'ws'
        cp=subprocess.run([sys.executable,'-I',str(ROOT/'scripts/source.py'),'--local-git',str(repo),'--repo','a/b','--out',str(out)],capture_output=True)
        self.assertEqual(cp.returncode,0,cp.stderr); self.assertEqual(json.loads(cp.stdout)['commit'],sha)
        inside=repo/'ws2'
        cp=subprocess.run([sys.executable,'-I',str(ROOT/'scripts/source.py'),'--local-git',str(repo),'--out',str(inside)],capture_output=True)
        self.assertEqual(cp.returncode,2); self.assertFalse(inside.exists())

class PackageTests(unittest.TestCase):
    def test_skill_frontmatter(self):
        head=(ROOT/'SKILL.md').read_text(encoding='utf-8').split('---')[1]
        self.assertIn('name: repo-denetle',head); self.assertIn('description:',head)
    def test_no_old_name(self):
        for f in ROOT.rglob('*'):
            if f.is_file() and f.suffix in ('.md','.py','.json','.yaml','.cmd') and f.name not in ('CHANGELOG.md','test_package.py','TEST-RESULTS.md'):
                self.assertNotIn('repo-denetim',f.read_text(encoding='utf-8'),str(f))
    def test_manifest_matches(self):
        m=json.loads((ROOT/'MANIFEST.sha256.json').read_text(encoding='utf-8'))
        files={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        self.assertEqual(set(m),files-{'MANIFEST.sha256.json'})
        for rel,h in m.items(): self.assertEqual(c.digest((ROOT/rel).read_bytes()),h,rel)

if __name__=='__main__': unittest.main(verbosity=2)
