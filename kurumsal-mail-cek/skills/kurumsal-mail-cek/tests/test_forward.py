import contextlib
import csv
import hashlib
import io
import json
import sys
import tempfile
import subprocess
from argparse import Namespace
from email.message import EmailMessage
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo
import datetime as dt

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mail_export
import mail_yaz


class DummyTokenProvider:
    def __init__(self, _path):
        pass

    def get(self):
        return "token"


def args(root, month="2026-08", completion=False):
    return Namespace(
        ay=mail_export.parse_month(month),
        baslangic=None,
        bitis=None,
        hedef_kok=str(root),
        devam=False,
        tamamlayici_tarama=completion,
        sadece_say=False,
    )


def graph_record(message_id, when, attachment=False):
    return {
        "id": message_id,
        "receivedDateTime": when,
        "sentDateTime": when,
        "createdDateTime": when,
        "lastModifiedDateTime": when,
        "hasAttachments": attachment,
    }


def eml_bytes(message_id, internet_id=None, attachment=None):
    msg = EmailMessage()
    msg["Message-ID"] = internet_id or f"<{message_id}@example.test>"
    msg["Subject"] = "Forward test " + message_id
    msg["From"] = "gonderen@example.test"
    msg["To"] = "alan@example.test"
    msg.set_content("Gövde " + message_id, charset="utf-8")
    if attachment:
        msg.add_attachment(
            attachment[1], maintype="application", subtype="octet-stream",
            filename=attachment[0])
    return msg.as_bytes()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_quiet(function, *f_args, **f_kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return function(*f_args, **f_kwargs)


def attachment_preservation_and_new_only():
    class FakeGraph:
        records = []
        payloads = {}
        downloads = []

        def __init__(self, _tokens):
            pass

        def json(self, _path, params=None):
            skip = int((params or {}).get("$skip", 0))
            return {"value": self.records[skip:skip + 50]}

        def download(self, endpoint, sink):
            message_id = endpoint.split("/")[-2]
            self.downloads.append(message_id)
            sink.write_bytes(self.payloads[message_id])

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folders = [{"id": "f1", "path": "Arşiv", "date_field": "receivedDateTime"}]
        old = graph_record("old", "2026-08-01T10:00:00Z", True)
        new = graph_record("new", "2026-08-04T10:00:00Z", True)
        FakeGraph.payloads = {
            "old": eml_bytes("old", attachment=("eski.bin", b"ESKI-EK-123")),
            "new": eml_bytes("new", attachment=("yeni.bin", b"YENI-EK-456")),
        }
        FakeGraph.records = [old]
        FakeGraph.downloads = []
        patches = (
            mock.patch.object(mail_export, "TokenProvider", DummyTokenProvider),
            mock.patch.object(mail_export, "GraphClient", FakeGraph),
            mock.patch.object(mail_export, "discover_folders", return_value=folders),
        )
        with patches[0], patches[1], patches[2]:
            first = run_quiet(mail_export.execute, args(root))
            run = root / "2026" / "agustos-2026"
            old_attachment = next((run / "ekler" / "202608-00001").iterdir())
            before_hash = sha(old_attachment)
            before_mtime = old_attachment.stat().st_mtime_ns
            FakeGraph.records = [old, new]
            second = run_quiet(mail_export.execute, args(root))
            after_hash = sha(old_attachment)
            after_mtime = old_attachment.stat().st_mtime_ns

        with (run / "mailler.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter=";"))
        control = (run / "kontrol.txt").read_text(encoding="utf-8")
        state = json.loads((run / "_durum.json").read_text(encoding="utf-8"))
        ok = (
            first == 0 and second == 0
            and [row["mesaj_id"] for row in rows] == ["old", "new"]
            and FakeGraph.downloads == ["old", "new"]
            and before_hash == after_hash
            and before_mtime == after_mtime
            and state.get("bu_calistirmada_eklenen") == 1
            and "KONTROL: GECTI" in control
        )
        return {
            "ok": ok,
            "rows": [row["mesaj_id"] for row in rows],
            "downloads": FakeGraph.downloads,
            "old_attachment_unchanged": before_hash == after_hash and before_mtime == after_mtime,
            "added_second_run": state.get("bu_calistirmada_eklenen"),
            "control_passed": "KONTROL: GECTI" in control,
        }


def timezone_boundary_scope():
    folder = {"id": "f1", "path": "Arşiv", "date_field": "receivedDateTime"}
    _, params = mail_export.message_query(
        folder, dt.date(2026, 8, 1), dt.date(2026, 9, 1), 0)
    utc_start = params["$filter"].split(" ge ", 1)[1].split(" and ", 1)[0]
    utc_end = params["$filter"].rsplit(" lt ", 1)[1]
    istanbul = ZoneInfo("Europe/Istanbul")
    cases = {
        "local_august_first_0030": dt.datetime(2026, 7, 31, 21, 30, tzinfo=dt.timezone.utc),
        "local_september_first_0030": dt.datetime(2026, 8, 31, 21, 30, tzinfo=dt.timezone.utc),
    }
    computed = {}
    for name, instant in cases.items():
        local_month_is_august = instant.astimezone(istanbul).month == 8
        query_includes = (
            dt.datetime.fromisoformat(utc_start.replace("Z", "+00:00")) <= instant
            < dt.datetime.fromisoformat(utc_end.replace("Z", "+00:00"))
        )
        computed[name] = {
            "utc": instant.isoformat(),
            "istanbul": instant.astimezone(istanbul).isoformat(),
            "expected_august": local_month_is_august,
            "query_includes": query_includes,
        }
    mismatch = any(v["expected_august"] != v["query_includes"] for v in computed.values())
    return {"bug_reproduced": mismatch, "filter": params["$filter"], "cases": computed}


def failed_record_is_not_automatically_repaired():
    class FakeGraph:
        records = [graph_record("broken", "2026-08-02T10:00:00Z")]
        payload = eml_bytes("broken")
        downloads = []

        def __init__(self, _tokens):
            pass

        def json(self, _path, params=None):
            skip = int((params or {}).get("$skip", 0))
            return {"value": self.records[skip:skip + 50]}

        def download(self, endpoint, sink):
            self.downloads.append(endpoint.split("/")[-2])
            sink.write_bytes(self.payload)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folders = [{"id": "f1", "path": "Arşiv", "date_field": "receivedDateTime"}]
        injected = {"calls": 0}

        def transient_header_failure(_script_dir, page_path, run_dir, folder,
                                     prefix, starting_sequence):
            injected["calls"] += 1
            real_open = open

            def fail_header(path, mode="r", *open_args, **open_kwargs):
                if (injected["calls"] == 1 and "w" in mode
                        and "basliklar" in str(path)):
                    raise OSError("sentetik gecici header write failure")
                return real_open(path, mode, *open_args, **open_kwargs)

            with mock.patch("builtins.open", side_effect=fail_header):
                return mail_yaz.sayfayi_isle(
                    str(page_path), str(run_dir), folder, prefix, starting_sequence)
        base_patches = (
            mock.patch.object(mail_export, "TokenProvider", DummyTokenProvider),
            mock.patch.object(mail_export, "GraphClient", FakeGraph),
            mock.patch.object(mail_export, "discover_folders", return_value=folders),
        )
        with base_patches[0], base_patches[1], base_patches[2]:
            with mock.patch.object(mail_export, "run_mail_writer", side_effect=transient_header_failure):
                first = run_quiet(mail_export.execute, args(root))
            run = root / "2026" / "agustos-2026"
            pending_after_first = json.loads((run / "_bekleyen.json").read_text(encoding="utf-8"))
            second = run_quiet(mail_export.execute, args(root))
            pending_after_second = json.loads((run / "_bekleyen.json").read_text(encoding="utf-8"))
            second_control = (run / "kontrol.txt").read_text(encoding="utf-8")

        fixed = (
            first == 0 and second == 0
            and pending_after_first == {} and pending_after_second == {}
            and FakeGraph.downloads == ["broken"]
            and "KONTROL: GECTI" in second_control
        )
        return {
            "fixed": fixed,
            "first_exit": first,
            "second_exit": second,
            "writer_calls_first_run": injected["calls"],
            "pending_after_first": pending_after_first,
            "pending_after_second": pending_after_second,
            "downloads": FakeGraph.downloads,
            "second_control_passed": "KONTROL: GECTI" in second_control,
        }


def moved_message_default_id_duplicates():
    class FakeGraph:
        records = []
        internet_id = "<same-message@example.test>"
        downloads = []

        def __init__(self, _tokens):
            pass

        def json(self, _path, params=None):
            skip = int((params or {}).get("$skip", 0))
            return {"value": self.records[skip:skip + 50]}

        def download(self, endpoint, sink):
            graph_id = endpoint.split("/")[-2]
            self.downloads.append(graph_id)
            sink.write_bytes(eml_bytes(graph_id, internet_id=self.internet_id))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folders = [{"id": "f1", "path": "Arşiv", "date_field": "receivedDateTime"}]
        patches = (
            mock.patch.object(mail_export, "TokenProvider", DummyTokenProvider),
            mock.patch.object(mail_export, "GraphClient", FakeGraph),
            mock.patch.object(mail_export, "discover_folders", return_value=folders),
        )
        with patches[0], patches[1], patches[2]:
            FakeGraph.records = [graph_record("rest-id-before-move", "2026-08-02T10:00:00Z")]
            first = run_quiet(mail_export.execute, args(root))
            FakeGraph.records = [graph_record("rest-id-after-move", "2026-08-02T10:00:00Z")]
            second = run_quiet(mail_export.execute, args(root))
        run = root / "2026" / "agustos-2026"
        with (run / "mailler.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter=";"))
        return {
            "risk_reproduced": first == 0 and second == 0 and len(rows) == 2,
            "graph_ids": [r["mesaj_id"] for r in rows],
            "internet_ids": [r["internet_mesaj_id"] for r in rows],
            "duplicate_flags": [r["mukerrer_mi"] for r in rows],
            "downloads": FakeGraph.downloads,
        }


def live_paging_shift_can_pass_control_with_omission():
    class FakeGraph:
        records = [
            graph_record(f"old-{i:03d}", f"2026-08-02T10:{i % 60:02d}:00Z")
            for i in range(1, 101)
        ]
        inserted = False
        chain = 0
        downloads = []

        def __init__(self, _tokens):
            pass

        def json(self, _path, params=None):
            if str(_path).startswith("next://"):
                _, chain_text, skip_text = str(_path).split("/")[-3:]
                chain = int(chain_text)
                skip = int(skip_text)
            else:
                type(self).chain += 1
                chain = type(self).chain
                skip = int((params or {}).get("$skip", 0))
            page = {"value": self.records[skip:skip + 50]}
            if chain == 1 and skip == 0 and not self.inserted:
                self.inserted = True
                self.records.insert(
                    0, graph_record("late-insert", "2026-08-01T00:00:01Z"))
            if skip + 50 < len(self.records):
                page["@odata.nextLink"] = f"next://chain/{chain}/{skip + 50}"
            return page

        def download(self, endpoint, sink):
            graph_id = endpoint.split("/")[-2]
            self.downloads.append(graph_id)
            sink.write_bytes(eml_bytes(graph_id))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folders = [{"id": "f1", "path": "Arşiv", "date_field": "receivedDateTime"}]
        patches = (
            mock.patch.object(mail_export, "TokenProvider", DummyTokenProvider),
            mock.patch.object(mail_export, "GraphClient", FakeGraph),
            mock.patch.object(mail_export, "discover_folders", return_value=folders),
        )
        with patches[0], patches[1], patches[2]:
            result = run_quiet(mail_export.execute, args(root))
        run = root / "2026" / "agustos-2026"
        with (run / "mailler.csv").open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter=";"))
        source = json.loads((run / "_kaynak_idler.json").read_text(encoding="utf-8"))
        local_ids = {row["mesaj_id"] for row in rows}
        control = (run / "kontrol.txt").read_text(encoding="utf-8")
        return {
            "fixed": (
                result == 0 and "KONTROL: GECTI" in control
                and "late-insert" in local_ids and len(local_ids) == 101
            ),
            "exit": result,
            "control_passed": "KONTROL: GECTI" in control,
            "live_source_total_after_insert": len(FakeGraph.records),
            "local_unique_ids": len(local_ids),
            "late_insert_archived": "late-insert" in local_ids,
            "source_manifest_rows": len(source["Arşiv"]),
            "source_manifest_unique": len(set(source["Arşiv"])),
        }


def local_boundary_message_is_rejected_by_controller():
    class FakeGraph:
        records = [graph_record("august-local", "2026-07-31T21:30:00Z")]

        def __init__(self, _tokens):
            pass

        def json(self, _path, params=None):
            skip = int((params or {}).get("$skip", 0))
            return {"value": self.records[skip:skip + 50]}

        def download(self, endpoint, sink):
            sink.write_bytes(eml_bytes("august-local"))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folders = [{"id": "f1", "path": "Arşiv", "date_field": "receivedDateTime"}]
        patches = (
            mock.patch.object(mail_export, "TokenProvider", DummyTokenProvider),
            mock.patch.object(mail_export, "GraphClient", FakeGraph),
            mock.patch.object(mail_export, "discover_folders", return_value=folders),
        )
        with patches[0], patches[1], patches[2]:
            result = run_quiet(mail_export.execute, args(root))
        run = root / "2026" / "agustos-2026"
        control = (run / "kontrol.txt").read_text(encoding="utf-8")
        return {
            "bug_reproduced": result == 2 and "tarih araligi disinda" in control,
            "exit": result,
            "local_time": "2026-08-01T00:30:00+03:00",
            "stored_graph_time": "2026-07-31T21:30:00Z",
            "control_failed": "KONTROL: BASARISIZ" in control,
        }


def header_write_failure_is_silent_data_loss():
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp)
        for name in ("ham", "govdeler", "basliklar", "ekler", "sorunlu_eml"):
            (run / name).mkdir()
        record = graph_record("header-loss", "2026-08-02T10:00:00Z")
        page = run / "page.json"
        page.write_text(json.dumps({"value": [record]}), encoding="utf-8")
        raw = run / "ham" / "202608-00001.eml"
        raw.write_bytes(eml_bytes("header-loss"))
        real_open = open

        def fail_header(path, mode="r", *open_args, **open_kwargs):
            if "w" in mode and "basliklar" in str(path):
                raise OSError("sentetik header write failure")
            return real_open(path, mode, *open_args, **open_kwargs)

        with mock.patch("builtins.open", side_effect=fail_header):
            outcome = mail_yaz.sayfayi_isle(
                str(page), str(run), "Arşiv", "202608", 1)
        proc = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "kontrol.py"), "--kosu", str(run)],
            check=True, capture_output=True, text=True, encoding="utf-8")
        control = json.loads(proc.stdout)
        csv_exists = (run / "mailler.csv").is_file()
        return {
            "fixed": (
                outcome["hata"] == 1 and control["hukum"] == "BASARISIZ"
                and raw.exists() and not csv_exists
            ),
            "writer_hata": outcome["hata"],
            "writer_notes": outcome["notlar"],
            "raw_deleted": not raw.exists(),
            "csv_exists": csv_exists,
            "control": control["hukum"],
        }


def truncated_existing_attachment_still_passes_control():
    class FakeGraph:
        records = [graph_record("old-attachment", "2026-08-02T10:00:00Z", True)]
        downloads = []

        def __init__(self, _tokens):
            pass

        def json(self, _path, params=None):
            skip = int((params or {}).get("$skip", 0))
            return {"value": self.records[skip:skip + 50]}

        def download(self, endpoint, sink):
            graph_id = endpoint.split("/")[-2]
            self.downloads.append(graph_id)
            sink.write_bytes(eml_bytes(
                graph_id, attachment=("korunacak.bin", b"ORIGINAL-ATTACHMENT-BYTES")))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folders = [{"id": "f1", "path": "Arşiv", "date_field": "receivedDateTime"}]
        patches = (
            mock.patch.object(mail_export, "TokenProvider", DummyTokenProvider),
            mock.patch.object(mail_export, "GraphClient", FakeGraph),
            mock.patch.object(mail_export, "discover_folders", return_value=folders),
        )
        with patches[0], patches[1], patches[2]:
            first = run_quiet(mail_export.execute, args(root))
            run = root / "2026" / "agustos-2026"
            attachment = next((run / "ekler" / "202608-00001").iterdir())
            original_size = attachment.stat().st_size
            attachment.write_bytes(b"X")
            second = run_quiet(mail_export.execute, args(root))
        control = (run / "kontrol.txt").read_text(encoding="utf-8")
        return {
            "fixed": (
                first == 0 and second == 2 and attachment.stat().st_size == 1
                and "KONTROL: BASARISIZ" in control
            ),
            "original_size": original_size,
            "actual_size_after_corruption": attachment.stat().st_size,
            "downloads": FakeGraph.downloads,
            "second_control_passed": "KONTROL: GECTI" in control,
        }


import unittest


class ForwardTests(unittest.TestCase):
    def test_attachment_preservation(self):
        self.assertTrue(attachment_preservation_and_new_only()["ok"])

    def test_timezone_boundary(self):
        self.assertFalse(timezone_boundary_scope()["bug_reproduced"])

    def test_record_retry(self):
        self.assertTrue(failed_record_is_not_automatically_repaired()["fixed"])

    def test_different_source_ids_preserved(self):
        result = moved_message_default_id_duplicates()
        self.assertEqual(len(result["graph_ids"]), 2)
        self.assertEqual(result["duplicate_flags"], ["hayir", "evet"])

    def test_live_paging_reconciliation(self):
        self.assertTrue(live_paging_shift_can_pass_control_with_omission()["fixed"])

    def test_local_boundary_control(self):
        result = local_boundary_message_is_rejected_by_controller()
        self.assertFalse(result["bug_reproduced"])
        self.assertEqual(result["exit"], 0)

    def test_header_failure_retains_raw(self):
        self.assertTrue(header_write_failure_is_silent_data_loss()["fixed"])

    def test_truncated_attachment_rejected(self):
        self.assertTrue(truncated_existing_attachment_still_passes_control()["fixed"])


if __name__ == "__main__":
    unittest.main()
