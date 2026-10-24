"""Regression cases from independent full-package review, using isolated fixtures."""
import os
from pathlib import Path
import tempfile
import subprocess
import shutil
import unittest
from unittest import mock

from test_package import Temp, complete, c, ins, s, make_repo, BYTES, approve_fixture, ev, side, finding


class DeliveryRegressionTests(Temp):
    def test_final_delivery_rejects_dispatch_and_telemetry_until_reopen(self):
        complete(self.root)
        dispatch = c.dispatch(self.root, 'life')
        approve_fixture(self.root)
        c.finalize(self.root)
        state = (self.root / 'state.json').read_bytes()
        archive = (self.root / 'repo-denetle-raporlar.zip').read_bytes()
        self.assert_error(c.dispatch, self.root, 'life')
        self.assert_error(c.telemetry, self.root, dispatch['id'], '', '', 'new-agent')
        self.assertEqual((self.root / 'state.json').read_bytes(), state)
        self.assertEqual((self.root / 'repo-denetle-raporlar.zip').read_bytes(), archive)

    def test_final_review_required(self):
        complete(self.root)
        (self.root / 'review.json').unlink()
        self.assert_error(c.finalize, self.root)

    def test_review_template_is_never_an_approval(self):
        complete(self.root)
        c.atomic_json(self.root / 'review.json', c.review_template(self.root))
        self.assert_error(c.finalize, self.root)

    def test_review_becomes_stale_after_state_change(self):
        complete(self.root)
        c.dispatch(self.root, 'life')
        self.assert_error(c.validate_review, self.root)

    def test_unsupported_context_and_token_checks_block_delivery(self):
        complete(self.root)
        for key in ('applicability', 'measurements'):
            with self.subTest(check=key):
                review = approve_fixture(self.root)
                review['checks'][key] = {'status': 'needs_revision', 'reason': 'Missing actual usage or measurement evidence'}
                c.atomic_json(self.root / 'review.json', review)
                self.assert_error(c.finalize, self.root)

    def test_unverified_finding_cannot_be_a_confirmed_summary_claim(self):
        complete(self.root, True)
        review = approve_fixture(self.root)
        review['findings'][0]['status'] = 'unverified'
        review['claims'] = [{'id': 'CLM-001', 'path': 'executive-summary.md', 'quote': 'Summary',
                             'source_ids': ['BIZ-001'], 'status': 'confirmed'}]
        c.atomic_json(self.root / 'review.json', review)
        self.assert_error(c.validate_review, self.root)
        review['claims'][0]['status'] = 'unverified'
        c.atomic_json(self.root / 'review.json', review)
        self.assertEqual(c.finalize(self.root)['status'], 'STRUCTURALLY_VALIDATED_STATIC_AUDIT')

    def test_new_life_finding_cannot_skip_final_review(self):
        complete(self.root)
        c.reopen(self.root, 'LIFE', 'New lifecycle finding')
        side(self.root, 'LIFE', [finding('LIFE')])
        c.atomic_json(self.root / 'findings/consolidated.json', [
            {'id': 'CONS-001', 'source_ids': ['LIFE-001'], 'disposition': 'open', 'reason': 'Fixture'}])
        c.accept(self.root, 'LIFE')
        review = approve_fixture(self.root)
        review['findings'] = []
        c.atomic_json(self.root / 'review.json', review)
        self.assert_error(c.finalize, self.root)

    def test_final_review_cannot_silently_promote_a_rejected_verdict(self):
        complete(self.root, True)
        c.reopen(self.root, 'VERIFY', 'Fixture rejected')
        data = c.read_json(self.root / 'findings/VERIFY.json')
        data['verification'][0]['status'] = 'rejected'
        c.atomic_json(self.root / 'findings/VERIFY.json', data)
        c.accept(self.root, 'VERIFY'); c.accept(self.root, 'LIFE')
        approve_fixture(self.root)
        self.assert_error(c.validate_review, self.root)

    def test_zip_write_failure_keeps_previous_delivery(self):
        complete(self.root)
        c.finalize(self.root)
        archive = (self.root / 'repo-denetle-raporlar.zip').read_bytes()
        marker = (self.root / 'completion.json').read_bytes()
        with mock.patch.object(c.zipfile.ZipFile, 'writestr', side_effect=OSError('injected write failure')):
            with self.assertRaises(OSError): c.finalize(self.root)
        self.assertEqual((self.root / 'repo-denetle-raporlar.zip').read_bytes(), archive)
        self.assertEqual((self.root / 'completion.json').read_bytes(), marker)
        self.assertFalse(list(self.root.glob('.report-*.zip')))

    def test_completion_write_failure_restores_both_previous_files(self):
        complete(self.root)
        c.finalize(self.root)
        archive = (self.root / 'repo-denetle-raporlar.zip').read_bytes()
        marker = (self.root / 'completion.json').read_bytes()
        review = c.read_json(self.root / 'review.json')
        review['checks']['synthesis']['reason'] = 'A fresh real review would have different bytes'
        c.atomic_json(self.root / 'review.json', review)
        original = c.atomic_json
        def fail_marker(path, value):
            if path == self.root / 'completion.json': raise OSError('injected completion write failure')
            return original(path, value)
        with mock.patch.object(c, 'atomic_json', side_effect=fail_marker):
            with self.assertRaises(OSError): c.finalize(self.root)
        self.assertEqual((self.root / 'repo-denetle-raporlar.zip').read_bytes(), archive)
        self.assertEqual((self.root / 'completion.json').read_bytes(), marker)

    def test_first_delivery_marker_failure_leaves_no_success_files(self):
        complete(self.root)
        with mock.patch.object(c, 'atomic_json', side_effect=OSError('first completion write failed')):
            with self.assertRaises(OSError): c.finalize(self.root)
        self.assertFalse((self.root / 'repo-denetle-raporlar.zip').exists())
        self.assertFalse((self.root / 'completion.json').exists())

    def test_archive_hardlink_cannot_overwrite_another_file(self):
        complete(self.root)
        outside = Path(self.tmp.name) / 'keep.txt'
        outside.write_bytes(b'user content must survive')
        os.link(outside, self.root / 'repo-denetle-raporlar.zip')
        c.finalize(self.root)
        self.assertEqual(outside.read_bytes(), b'user content must survive')

    def test_reopen_invalidates_visible_delivery_and_preserves_previous_archive(self):
        complete(self.root)
        result = c.finalize(self.root)
        old = Path(result['archive']).read_bytes()
        c.reopen(self.root, 'LIFE', 'Review found an unsupported summary claim')
        self.assertFalse((self.root / 'completion.json').exists())
        self.assertFalse((self.root / 'repo-denetle-raporlar.zip').exists())
        previous = list((self.root / 'superseded').rglob('repo-denetle-raporlar.zip'))
        self.assertEqual(len(previous), 1)
        self.assertEqual(previous[0].read_bytes(), old)


class InstallerRegressionTests(unittest.TestCase):
    def test_source_inside_later_target_is_rejected_before_any_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            package = home / '.gemini/config/skills/repo-denetle/nested-package'
            package.mkdir(parents=True)
            (package / 'SKILL.md').write_text('keep', encoding='utf-8')
            with mock.patch.object(ins, 'ROOT', package):
                with self.assertRaisesRegex(RuntimeError, 'overlaps'):
                    ins.install(home, list(ins.TARGETS))
            self.assertFalse((home / '.claude').exists())
            self.assertFalse((home / '.codex').exists())
            self.assertEqual((package / 'SKILL.md').read_text(), 'keep')

    def test_default_install_from_antigravity_copy_keeps_its_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            package = home / '.gemini/config/skills/repo-denetle'
            package.mkdir(parents=True)
            (package / 'SKILL.md').write_text('original skill', encoding='utf-8')
            with mock.patch.object(ins, 'ROOT', package):
                try:
                    rows = ins.install(home, list(ins.TARGETS))
                    self.assertEqual((package / 'SKILL.md').read_text(), 'original skill')
                    for target in ('claude', 'codex'):
                        link = home.joinpath(*ins.TARGETS[target]) / ins.NAME
                        self.assertTrue((link / 'SKILL.md').is_file(), target)
                    self.assertEqual(rows[-1]['status'], 'already_at_source')
                finally:
                    ins.uninstall(home, ['claude', 'codex'])


@unittest.skipUnless(shutil.which('git'), 'Git not installed')
class SourceReadRegressionTests(unittest.TestCase):
    def test_missing_promisor_object_does_not_trigger_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _ = make_repo(tmp, {'a.py': BYTES})
            for key, value in (('remote.origin.url', 'file:///nonexistent-audit-fixture'),
                               ('remote.origin.promisor', 'true'),
                               ('remote.origin.partialclonefilter', 'blob:none')):
                subprocess.run(['git', '-C', str(repo), 'config', key, value], check=True, capture_output=True)
            trace = Path(tmp) / 'git-trace.log'
            # file transport is denied by run_git; no network or remote fixture is used.
            with mock.patch.dict(os.environ, {'GIT_TRACE': trace.as_posix(), 'GIT_NO_LAZY_FETCH': '0'}):
                result = s.run_git(['cat-file', '--batch'], repo / '.git', b'f' * 40 + b'\n')
            self.assertIn(b'missing', result)
            self.assertNotRegex(trace.read_text(encoding='utf-8'), r'(?:run_command:|built-in:).*\bfetch\b')


if __name__ == '__main__':
    unittest.main()
