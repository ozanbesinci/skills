"""Denetim bulguları: yalnız geçici sentetik veri, sahte COM/Chroma/gömücü."""
import contextlib
import copy
import csv
import email
import email.policy
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

SKILLS = Path(__file__).resolve().parents[2]
SCRIPTS = SKILLS / 'kurumsal-mail-cek' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SKILLS / 'mail-ara' / 'scripts'))
import archive_contract as contract
import mail_yaz
import mail_export_mapi as mapi
import mail_export
import mail_onar
import aktarim
import ortak
import indeksle
import ek_cikar
import ek_indeksle
REAL_ENSURE_GENERATION = aktarim.ensure_generation
REAL_VERIFY_GENERATION = aktarim.verify_generation


def message(mid='one', calendar=False, signed=False):
    msg = EmailMessage()
    msg['Message-ID'] = f'<{mid}@example.test>'
    msg['From'] = 'sentetik@example.test'
    msg['To'] = 'alici@example.test'
    msg['Subject'] = 'Sentetik test'
    msg.set_content('Sentetik gövde; gerçek mail içermez.', charset='utf-8')
    msg.add_attachment(b'%PDF-sentetik', maintype='application', subtype='pdf', filename='belge.pdf')
    if calendar:
        msg.add_attachment(b'BEGIN:VCALENDAR\r\nEND:VCALENDAR', maintype='text', subtype='calendar', filename='davet.ics')
    if signed:
        msg.add_attachment(b'signature', maintype='application', subtype='pkcs7-signature', filename='smime.p7s')
    return msg


def fixture(root, seq=1, mid='one', msg=None, folder='Arşiv'):
    root = Path(root)
    (root / 'ham').mkdir(parents=True, exist_ok=True)
    raw = root / 'ham' / f'202608-{seq:05d}.eml'
    raw.write_bytes((msg or message(mid)).as_bytes())
    record = dict(id=mid, internetMessageId=f'<{mid}@example.test>',
                  receivedDateTime='2026-08-03T10:00:00Z', sentDateTime='2026-08-03T10:00:00Z')
    page = root / f'page-{seq}.json'
    contract.atomic_json(page, dict(value=[record]))
    return raw, page, record


def write(root, page, seq=1, folder='Arşiv'):
    return mail_yaz.sayfayi_isle(str(page), str(root), folder, '202608', seq)


def control(root, start='2026-08-01', end='2026-08-31'):
    result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'kontrol.py'), '--kosu', str(root),
                             '--baslangic', start, '--bitis', end], check=True, capture_output=True,
                            text=True, encoding='utf-8')
    return json.loads(result.stdout)


def seal(root, run='fixture-run'):
    contract.atomic_json(Path(root) / '_aktarim.json', dict(schema=1, run_id=run, durum='GECTI',
                         kaynak_turu='graph', fingerprint=contract.archive_fingerprint(root)))


class PersistenceTests(unittest.TestCase):
    def test_atomic_replace_retries_transient_windows_sharing_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.json'
            path.write_bytes(b'old')
            original = os.replace
            calls = []
            def transient(src, dst):
                calls.append(1)
                if len(calls) == 1:
                    self.assertEqual(path.read_bytes(), b'old')
                    raise PermissionError('sentetik paylaşım kilidi')
                return original(src, dst)
            with mock.patch.object(contract.os, 'replace', side_effect=transient):
                contract.atomic_bytes(path, b'new')
            self.assertEqual(path.read_bytes(), b'new')
            self.assertEqual(len(calls), 2)
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])

    def test_same_source_id_cannot_be_assigned_a_new_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, page, _ = fixture(root)
            write(root, page)
            raw, page, _ = fixture(root, 2, 'one')
            with self.assertRaises(ValueError):
                write(root, page, 2)
            self.assertTrue(raw.exists())
            self.assertEqual(len(contract.rows(root / 'mailler.csv')), 1)

    def test_crashes_at_both_csv_boundaries_recover_same_record(self):
        for boundary in ('mailler.csv', 'ekler.csv'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                raw, page, _ = fixture(root)
                original = mail_yaz.csv_ekle
                def crash(path, columns, records):
                    original(path, columns, records)
                    if Path(path).name == boundary:
                        raise OSError('sentetik kesinti')
                with mock.patch.object(mail_yaz, 'csv_ekle', side_effect=crash):
                    with self.assertRaises(OSError):
                        write(root, page)
                self.assertTrue(raw.exists())
                self.assertTrue((root / '_islem.json').exists())
                self.assertEqual(write(root, page)['hata'], 0)
                self.assertEqual(write(root, page)['hata'], 0)
                self.assertEqual(len(contract.rows(root / 'mailler.csv')), 1)
                self.assertEqual(len(contract.rows(root / 'ekler.csv')), 1)
                self.assertEqual(len(list((root / 'govdeler').iterdir())), 1)
                self.assertFalse(raw.exists())
                self.assertFalse((root / '_islem.json').exists())

    def test_json_and_commit_marker_crash_matrix(self):
        for boundary in ('_gorulen.json', 'before_commit', 'after_commit'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                raw, page, _ = fixture(root)
                original_json = contract.atomic_json
                original_open = open
                def fail_json(path, value):
                    if Path(path).name == '_islem.json' and value['state'] == 'COMMITTED':
                        if boundary == 'before_commit':
                            raise OSError('before commit')
                        if boundary == 'after_commit':
                            original_json(path, value)
                            raise OSError('after commit')
                    return original_json(path, value)
                def fail_open(path, mode='r', *args, **kwargs):
                    if boundary == '_gorulen.json' and Path(path).name == boundary and 'w' in mode:
                        raise OSError('JSON yazımı kesildi')
                    return original_open(path, mode, *args, **kwargs)
                with mock.patch.object(contract, 'atomic_json', side_effect=fail_json), mock.patch('builtins.open', side_effect=fail_open):
                    with self.assertRaises(OSError):
                        write(root, page)
                self.assertTrue(raw.exists())
                self.assertEqual(write(root, page)['hata'], 0)
                self.assertEqual(len(contract.rows(root / 'mailler.csv')), 1)
                self.assertEqual(len(contract.rows(root / 'ekler.csv')), 1)
                self.assertEqual(contract.integrity_errors(root), [])

    def test_same_message_id_different_source_entries_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, page, _ = fixture(root)
            write(root, page)
            _, page, record = fixture(root, 2, 'two', message('one'))
            record['internetMessageId'] = '<one@example.test>'
            contract.atomic_json(page, dict(value=[record]))
            write(root, page, 2)
            rows = contract.rows(root / 'mailler.csv')
            self.assertEqual([r['mesaj_id'] for r in rows], ['one', 'two'])
            self.assertEqual(rows[1]['mukerrer_mi'], 'evet')

    def test_normal_mail_calendar_attachment_and_signature_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, page, _ = fixture(root, msg=message(calendar=True, signed=True))
            self.assertEqual(write(root, page)['islenen'], 1)
            self.assertEqual(len(contract.rows(root / 'mailler.csv')), 1)
            attachments = contract.rows(root / 'ekler.csv')
            self.assertEqual({a['ek_adi'] for a in attachments}, {'belge.pdf', 'davet.ics'})
            self.assertTrue((root / 'sorunlu_eml' / '202608-00001.eml').exists())
            self.assertEqual(control(root)['hukum'], 'GECTI')

    def test_image_name_does_not_authorize_skipping_and_threshold_is_strict(self):
        for size, inline, expected in ((10, False, False), (10, True, True), (200*1024, True, False)):
            with self.subTest(size=size, inline=inline):
                msg = EmailMessage()
                msg.set_content('Gövde')
                msg.add_attachment(b'x'*size, maintype='image', subtype='png', filename='image001.png')
                part = list(msg.iter_attachments())[0]
                del part['Content-Disposition']
                if inline:
                    part['Content-Disposition'] = 'inline; filename="image001.png"'
                else:
                    part.set_param('name', 'image001.png', header='Content-Type')
                self.assertEqual(mail_yaz.govde_ve_ekler(msg)[2][0][3], expected)

    def test_sent_month_controls_use_sent_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, page, record = fixture(root)
            record['receivedDateTime'] = '2026-09-01T10:00:00Z'
            contract.atomic_json(page, dict(value=[record]))
            write(root, page, folder='Gönderilmiş Öğeler')
            self.assertEqual(control(root)['hukum'], 'GECTI')

    def test_same_size_output_corruption_detected(self):
        for sub in ('govdeler', 'basliklar', 'ekler'):
            with self.subTest(sub=sub), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, page, _ = fixture(root)
                write(root, page)
                path = next(p for p in (root / sub).rglob('*') if p.is_file())
                path.write_bytes(b'x' * path.stat().st_size)
                self.assertEqual(control(root)['hukum'], 'BASARISIZ')

    def test_wrong_or_fake_mime_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            msg = message()
            msg.get_payload(0).set_content('kaynak \ufffd', charset='utf-8')
            _, page, _ = fixture(root, msg=msg)
            write(root, page)
            proof = root / 'sorunlu_eml' / '202608-00001.eml'
            self.assertEqual(control(root)['hukum'], 'GECTI')
            proof.write_bytes(b'raw')
            warnings = contract.read_json(root / '_uyarilar.json')
            warnings[0]['ham_sha256'] = contract.digest(proof)
            contract.atomic_json(root / '_uyarilar.json', warnings)
            self.assertEqual(control(root)['hukum'], 'BASARISIZ')


class GateTests(unittest.TestCase):
    def test_repair_refreshes_receipt_and_verification_without_live_graph(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            archive = root/'archive'
            run = archive/'2026'/'agustos-2026'
            _, page, _ = fixture(run)
            write(run, page)
            seal(run, 'before-repair')
            body = next((run/'govdeler').iterdir())
            body.write_text('bozuk\x00 gövde', encoding='utf-8')
            work = root/'repair'
            manifest = mail_onar.discover(archive, work)
            fake_graph = Namespace(download=lambda endpoint, path: path.write_bytes(message().as_bytes()))
            with mock.patch.object(mail_onar, 'GraphClient', return_value=fake_graph), mock.patch.object(mail_onar, 'TokenProvider'):
                manifest = mail_onar.prepare(archive, work, manifest)
            self.assertEqual(manifest['status'], 'READY')
            manifest = mail_onar.apply_repair(archive, work, manifest)
            self.assertEqual(manifest['status'], 'APPLIED')
            with self.assertRaises(ValueError):
                contract.require_verified(run)
            self.assertEqual(contract.integrity_errors(run), [])
            manifest = mail_onar.refresh_reports(archive, work, manifest)
            self.assertTrue(all(v == 'GECTI' for v in manifest['report_verdicts'].values()))
            self.assertNotEqual(contract.require_verified(run)['run_id'], 'before-repair')

    def test_stale_pass_invalidated_on_failed_new_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, page, _ = fixture(root)
            write(root, page)
            seal(root)
            self.assertEqual(contract.require_verified(root)['durum'], 'GECTI')
            with self.assertRaises(RuntimeError):
                with contract.ExportSession(root, 'graph', '202608'):
                    with self.assertRaises(ValueError):
                        contract.require_verified(root)
                    raise RuntimeError('yeni koşu başarısız')
            with self.assertRaises(ValueError):
                contract.require_verified(root)
            self.assertIn('BASARISIZ', (root / 'kontrol.txt').read_text())

    def test_broken_pending_and_source_switch_leave_manifests_unchanged(self):
        for contents in ('{broken', '{}', '[{"sira_no":"202607-00001","id":"x"}]'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                contract.atomic_json(root / '_klasorler.json', {'store_id': 'mapi'})
                (root / '_bekleyen.json').write_text(contents)
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                with self.assertRaises(ValueError):
                    contract.source_guard(root, 'mapi', '202608')
                with self.assertRaises(ValueError):
                    contract.source_guard(root, 'graph', '202608')
                self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_duplicate_writer_and_unsafe_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with contract.lock(root / 'writer.lock'):
                with self.assertRaises(RuntimeError):
                    with contract.lock(root / 'writer.lock'):
                        pass
            with self.assertRaises(ValueError):
                contract.inside(root, '../outside.txt')

    def test_pst_copy_hash_guard_uses_only_synthetic_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'sentetik.pst'
            source.write_bytes(b'This is not a real PST; synthetic bytes only')
            before = source.read_bytes()
            target, proof = contract.prepare_pst(source, root / 'archive')
            self.assertNotEqual(target, source)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(contract.digest(source), proof['sha256'])
            def bad_copy(src, dst):
                Path(dst).write_bytes(b'bad')
            with mock.patch.object(contract.shutil, 'copyfile', side_effect=bad_copy):
                with self.assertRaises(ValueError):
                    contract.prepare_pst(source, root / 'archive')
            self.assertEqual(source.read_bytes(), before)


class MapiReadTests(unittest.TestCase):
    def test_past_pst_report_does_not_claim_complete_calendar_month(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapi.write_reports(root, '2025-08', 0, 0, {'hukum': 'GECTI', 'sayilar': {}}, 'PST')
            text = (root/'ozet.txt').read_text(encoding='utf-8')
            self.assertIn('KAYNAK_KAPSAMI_TAMAMLANDI', text)
            self.assertNotIn('Durum: AY_TAMAM', text)

    def build(self, item, has_attachments=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = dict(id='fake-entry', subject='Sentetik', _message_class='IPM.Note', hasAttachments=has_attachments)
            with mock.patch.object(mapi, 'original_headers', return_value='From: fake@example.test\n'), mock.patch.object(mapi, 'safe_prop', return_value=''):
                mapi.PROCESS.prefetch_msg = False
                mapi.build_eml(Namespace(GetItemFromID=lambda *a: item), 'fake-store', metadata,
                               root / 'out.eml', root / 'header.txt', root)
            return email.message_from_bytes((root / 'out.eml').read_bytes(), policy=email.policy.default)

    def item(self, **kwargs):
        values = dict(Body='Gövde', HTMLBody='', Attachments=Namespace(Count=0), MessageClass='IPM.Note')
        values.update(kwargs)
        return Namespace(**values)

    def test_body_error_can_use_successful_html_fallback(self):
        class Item:
            @property
            def Body(self):
                raise OSError('COM')
            HTMLBody = '<html><body>HTML gövdesi</body></html>'
            Attachments = Namespace(Count=0)
        self.assertIn('HTML gövdesi', self.build(Item()).get_body(preferencelist=('plain',)).get_content())

    def test_both_body_paths_failed_or_attachment_count_failed_stop(self):
        class BodyError:
            @property
            def Body(self):
                raise OSError('COM')
            @property
            def HTMLBody(self):
                raise OSError('COM')
        class CountError:
            @property
            def Count(self):
                raise OSError('COM')
        for item in (BodyError(), self.item(Attachments=CountError()), self.item(Attachments=None)):
            with self.subTest(item=type(item).__name__), self.assertRaises((OSError, RuntimeError, AttributeError)):
                self.build(item)

    def test_source_attachment_flag_cannot_turn_into_empty_collection(self):
        with self.assertRaises(RuntimeError):
            self.build(self.item(), has_attachments=True)

    def test_pst_inventory_gate_runs_in_export_invocation_before_mail_reads(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            root = Path(tmp)
            source = root/'sentetik.pst'
            source.write_bytes(b'NOT A REAL PST; synthetic test bytes')
            original_hash = contract.digest(source)
            store = Namespace(StoreID='fake', DisplayName='Fake', GetRootFolder=lambda: Namespace())
            ns = Namespace(RemoveStore=mock.Mock())
            stack.enter_context(mock.patch.object(sys, 'argv', ['export.py', '--ay', '2026-08', '--pst', str(source), '--cikti-koku', str(root/'archive')]))
            stack.enter_context(mock.patch.object(mapi.pythoncom, 'CoInitialize'))
            stack.enter_context(mock.patch.object(mapi.pythoncom, 'CoUninitialize'))
            stack.enter_context(mock.patch.object(mapi.win32com.client, 'Dispatch', return_value=Namespace(GetNamespace=lambda _: ns)))
            attach = stack.enter_context(mock.patch.object(mapi, 'pst_store', return_value=(store, True)))
            gate = stack.enter_context(mock.patch.object(mapi, 'full_pst_inventory', return_value=dict(gecti=False)))
            table = stack.enter_context(mock.patch.object(mapi, 'table_metadata', side_effect=AssertionError('mail read before inventory')))
            with self.assertRaises(ValueError):
                mapi.main()
            gate.assert_called_once()
            table.assert_not_called()
            self.assertNotEqual(Path(attach.call_args.args[1]), source)
            self.assertEqual(contract.digest(source), original_hash)
            ns.RemoveStore.assert_called_once()

    def test_completed_mapi_pending_is_not_exported_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / '2026' / 'agustos-2026'
            _, page, record = fixture(run)
            record.update(_folder_path='Arşiv', _message_class='IPM.Note')
            write(run, page)
            contract.atomic_json(run / '_klasorler.json', {'store_id': 'fake'})
            contract.atomic_json(run / '_bekleyen.json', [dict(sira_no='202608-00001', id='one', klasor_yolu='Arşiv')])
            ns = Namespace()
            store = Namespace(StoreID='fake', DisplayName='Sentetik store')
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(sys, 'argv', ['mail_export_mapi.py', '--ay', '2026-08', '--cikti-koku', str(root)]))
                stack.enter_context(mock.patch.object(mapi.pythoncom, 'CoInitialize'))
                stack.enter_context(mock.patch.object(mapi.pythoncom, 'CoUninitialize'))
                stack.enter_context(mock.patch.object(mapi.win32com.client, 'Dispatch', return_value=Namespace(GetNamespace=lambda _: ns)))
                stack.enter_context(mock.patch.object(mapi, 'archive_store', return_value=store))
                stack.enter_context(mock.patch.object(mapi, 'scope_folders', return_value=[(Namespace(EntryID='folder'), 'Arşiv', False)]))
                stack.enter_context(mock.patch.object(mapi, 'table_metadata', return_value=[record]))
                build = stack.enter_context(mock.patch.object(mapi, 'build_eml', side_effect=AssertionError('completed mail rebuilt')))
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(mapi.main(), 0)
                build.assert_not_called()
            self.assertEqual(len(contract.rows(run / 'mailler.csv')), 1)
            self.assertEqual(contract.read_json(run / '_bekleyen.json'), [])


class Vectors(list):
    def tolist(self):
        return list(self)
    def __getitem__(self, key):
        value = super().__getitem__(key)
        return Vectors(value) if isinstance(key, slice) else value


class FakeEmbedder:
    def gom(self, texts, *args, **kwargs):
        return Vectors([[0.1, 0.2] for _ in texts])


class FakeCollection:
    def __init__(self):
        self.data = {}
    def delete(self, ids):
        for key in ids:
            self.data.pop(key, None)
    def upsert(self, ids, metadatas, **kwargs):
        self.data.update(zip(ids, copy.deepcopy(metadatas)))
    def get(self, where=None, include=None, offset=0, limit=None):
        data = [(k, v) for k, v in self.data.items() if not where or all(v.get(f) == x for f, x in where.items())]
        data = data[offset:None if limit is None else offset+limit]
        return dict(ids=[k for k, _ in data], metadatas=[v for _, v in data])
    def count(self):
        return len(self.data)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive, self.index = self.root/'archive', self.root/'index-root'
        self.run = self.archive/'2026'/'agustos-2026'
        _, page, _ = fixture(self.run)
        write(self.run, page)
        seal(self.run)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for module, name, value in ((ortak, 'KOK', self.index), (ortak, 'ARSIV', self.archive),
                                    (ek_cikar, 'KOK', self.index), (ek_cikar, 'ARSIV', self.archive)):
            self.stack.enter_context(mock.patch.object(module, name, value))
        self.stack.enter_context(mock.patch.object(aktarim, 'ensure_generation', return_value='synthetic-generation'))
        self.stack.enter_context(mock.patch.object(aktarim, 'verify_generation', return_value=True))
        self.stack.enter_context(mock.patch.object(ortak, 'v2_var', return_value=True))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.index.mkdir()
        self.db = sqlite3.connect(self.index/'mail.sqlite')
        self.db.executescript(ortak.SEMA)
        self.addCleanup(self.db.close)
        self.collection = FakeCollection()

    def index_body(self):
        return indeksle.ay_indeksle('2026-08', self.db, self.collection, FakeEmbedder())

    def test_flat_and_yearly_layout_shared_and_ambiguity_rejected(self):
        self.assertEqual(aktarim.ay_klasoru(self.archive, '2026-08'), self.run)
        flat = self.archive/'agustos-2026'
        self.run.rename(flat)
        self.assertEqual(ortak.ay_klasoru('2026-08'), flat)
        self.assertEqual(ek_cikar.ay_klasoru('2026-08'), flat)
        self.assertIn('2026-08', ortak.arsiv_aylari())
        self.run.mkdir()
        with self.assertRaises(ValueError):
            ortak.ay_klasoru('2026-08')

    def test_body_metadata_only_change_and_delete_only_commit(self):
        self.assertEqual(self.index_body(), 1)
        header = self.run/'basliklar'/'202608-00001.txt'
        header.write_text('From: degisti@example.test\nSubject: Düzeltildi\nDate: Mon, 3 Aug 2026 10:00:00 +0300\n')
        seal(self.run, 'changed')
        self.assertEqual(self.index_body(), 1)
        self.assertIn('degisti', self.db.execute('SELECT kimden FROM mail').fetchone()[0])
        for path in (self.run/'govdeler').iterdir():
            path.unlink()
        seal(self.run, 'removed')
        self.assertEqual(self.index_body(), 0)
        with contextlib.closing(sqlite3.connect(self.index/'mail.sqlite')) as other:
            self.assertEqual(other.execute('SELECT COUNT(*) FROM mail').fetchone()[0], 0)
            self.assertEqual(other.execute('SELECT COUNT(*) FROM mail_fts').fetchone()[0], 0)
        self.assertEqual(self.collection.count(), 0)

    def test_partial_vector_write_resumes_without_duplicates(self):
        real = self.collection.upsert
        def crash(**kwargs):
            real(**kwargs)
            raise OSError('Chroma sonrasında kesinti')
        with mock.patch.object(self.collection, 'upsert', side_effect=crash):
            with self.assertRaises(OSError):
                self.index_body()
        self.db.rollback()
        self.assertEqual(self.index_body(), 1)
        self.assertEqual(self.collection.count(), 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM mail_fts').fetchone()[0], 1)

    def test_new_csv_row_does_not_reembed_unchanged_mails(self):
        self.assertEqual(self.index_body(), 1)
        _, page, _ = fixture(self.run, 2, 'two')
        write(self.run, page, 2)
        seal(self.run, 'appended')
        self.assertEqual(self.index_body(), 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM mail').fetchone()[0], 2)

    def test_csv_fallback_metadata_change_is_not_cached(self):
        (self.run/'basliklar'/'202608-00001.txt').write_text('MAPI transport başlığı yok\n')
        seal(self.run, 'fallback')
        self.index_body()
        rows = contract.rows(self.run/'mailler.csv')
        rows[0]['gonderen_mail'] = 'csv-degisti@example.test'
        with (self.run/'mailler.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=mail_yaz.MAIL_KOLONLAR, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
        seal(self.run, 'csv-changed')
        self.assertEqual(self.index_body(), 1)
        self.assertIn('csv-degisti', self.db.execute('SELECT kimden FROM mail').fetchone()[0])

    def test_fresh_index_creates_v2_collection(self):
        kol = Namespace(configuration_json={'embedding_function': {'name': ortak.EF_ADI}})
        client = Namespace(get_or_create_collection=mock.Mock(return_value=kol))
        constructor = mock.Mock(return_value=client)
        with mock.patch.dict(sys.modules, {'chromadb': Namespace(PersistentClient=constructor)}), \
             mock.patch.object(ortak, 'v2_var', return_value=False), \
             mock.patch.object(ortak, 'CHROMA_V2', self.index/'chroma_v2'), \
             mock.patch.object(ortak, 'CHROMA_DIZIN', self.index/'chroma'), \
             mock.patch.object(ortak, 'e5_ef', return_value=object()):
            self.assertIs(ortak.koleksiyon(), kol)
        self.assertEqual(constructor.call_args.kwargs['path'], str(self.index/'chroma_v2'))

    def test_attachment_index_partial_write_retry_and_removed_hash_cleanup(self):
        source_path, search_path = self.index/'ekler.sqlite', self.index/'ek_arama.sqlite'
        with contextlib.closing(sqlite3.connect(source_path)) as db:
            db.executescript(ek_cikar.SEMA)
            with mock.patch.object(ek_cikar, 'cikar', return_value=('Sentetik ek metni', 1, 'ok')):
                ek_cikar.ay_isle(db, '2026-08')
        kol = FakeCollection()
        with contextlib.ExitStack() as stack:
            for name, value in (('EK_DB', source_path), ('ARAMA_DB', search_path), ('KILIT', self.index/'index'/'indeksle.kilit')):
                stack.enter_context(mock.patch.object(ek_indeksle, name, value))
            stack.enter_context(mock.patch.object(sys, 'argv', ['ek_indeksle.py']))
            stack.enter_context(mock.patch.object(ortak, 'Gomucu', return_value=FakeEmbedder()))
            stack.enter_context(mock.patch.object(ek_indeksle, 'ek_koleksiyon', return_value=kol))
            real = kol.upsert
            def crash(**kwargs):
                real(**kwargs)
                raise OSError('ek vektörü yazıldıktan sonra kesinti')
            with mock.patch.object(kol, 'upsert', side_effect=crash):
                with self.assertRaises(OSError):
                    ek_indeksle.main()
            ek_indeksle.main()
            self.assertEqual(kol.count(), 1)
            with contextlib.closing(sqlite3.connect(search_path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ek_fts').fetchone()[0], 1)
            next((self.run/'ekler'/'202608-00001').iterdir()).unlink()
            seal(self.run, 'ek-removed')
            with contextlib.closing(sqlite3.connect(source_path)) as db:
                ek_cikar.ay_isle(db, '2026-08')
            ek_indeksle.main()
            self.assertEqual(kol.count(), 0)
            with contextlib.closing(sqlite3.connect(search_path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM yapildi').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ek_fts').fetchone()[0], 0)

    def test_attachment_deleted_reference_and_shared_content_reconciled(self):
        dbpath = self.index/'ekler.sqlite'
        with contextlib.closing(sqlite3.connect(dbpath)) as db:
            db.executescript(ek_cikar.SEMA)
            second = self.run/'ekler'/'202608-00002'
            second.mkdir()
            (second/'ortak.pdf').write_bytes(b'%PDF-sentetik')
            seal(self.run)
            with mock.patch.object(ek_cikar, 'cikar', return_value=('Sentetik ek metni', 1, 'ok')):
                ek_cikar.ay_isle(db, '2026-08')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM icerik').fetchone()[0], 1)
                first = next((self.run/'ekler'/'202608-00001').iterdir())
                first.unlink()
                seal(self.run, 'one-ref')
                ek_cikar.ay_isle(db, '2026-08')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ek').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM icerik').fetchone()[0], 1)
                (second/'ortak.pdf').unlink()
                seal(self.run, 'no-refs')
                ek_cikar.ay_isle(db, '2026-08')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ek').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM icerik').fetchone()[0], 0)

    def test_delivery_requires_all_three_current_stages(self):
        aktarim.stage(self.index, self.archive, '2026-08', 'govde', True, dict(generation='synthetic-generation'))
        with self.assertRaises(ValueError):
            aktarim.finish(self.index, self.archive, '2026-08')
        for name in ('ek_cikar', 'ek_indeks'):
            aktarim.stage(self.index, self.archive, '2026-08', name, True, dict(generation='synthetic-generation'))
        self.assertEqual(aktarim.finish(self.index, self.archive, '2026-08')['teslim'], 'TAMAMLANDI')
        seal(self.run, 'new-run')
        with self.assertRaises(ValueError):
            aktarim.finish(self.index, self.archive, '2026-08')

    def test_model_same_size_change_rejects_generation_mix(self):
        # setUp'ın nesil mock'unu bu test için aş; gerçek fingerprint stdlib ile hesaplanır.
        self.make_model()
        old = REAL_ENSURE_GENERATION(self.index, 'govde')
        model = self.index/'model'/'onnx'/'model.onnx'
        model.write_bytes(b'BBBB')
        new, _ = aktarim.generation(self.index, 'govde')
        self.assertNotEqual(old, new)
        with self.assertRaises(ValueError):
            REAL_ENSURE_GENERATION(self.index, 'govde')
        with self.assertRaises(ValueError):
            REAL_VERIFY_GENERATION(self.index, 'govde', old)

    def test_generation_verification_does_not_guess_other_python_environment(self):
        self.make_model()
        fingerprint = REAL_ENSURE_GENERATION(self.index, 'ek_cikar')
        with mock.patch.object(aktarim.platform, 'python_version', return_value='different-python'):
            self.assertTrue(REAL_VERIFY_GENERATION(self.index, 'ek_cikar', fingerprint))
            with self.assertRaises(ValueError):
                REAL_ENSURE_GENERATION(self.index, 'ek_cikar')

    def test_unversioned_populated_index_requires_separate_generation(self):
        self.make_model()
        index_dir = self.index/'index'
        index_dir.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(index_dir/'mail.sqlite')) as db:
            db.execute('CREATE TABLE mail(id TEXT)')
            db.execute('INSERT INTO mail VALUES (?)', ('old',))
            db.commit()
        with self.assertRaises(ValueError):
            REAL_ENSURE_GENERATION(self.index, 'govde')
        self.assertFalse((index_dir/'nesil-govde.json').exists())

    def make_model(self):
        model = self.index/'model'/'onnx'
        model.mkdir(parents=True)
        (model/'model.onnx').write_bytes(b'AAAA')
        (model/'tokenizer.json').write_bytes(b'{}')
        return self.index


if __name__ == '__main__':
    unittest.main()
