#!/usr/bin/env python3
"""Mail parseri ve bağımsız kontrol için veri-kaybı regresyon testleri."""

from __future__ import annotations

import base64
import builtins
import csv
import datetime as dt
import email
import email.policy
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from email.message import EmailMessage, MIMEPart
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mail_yaz  # noqa: E402
import archive_contract as contract
import mail_export  # noqa: E402
import mail_export_mapi  # noqa: E402
import mail_onar  # noqa: E402
import mapi_reclassify_nonmail  # noqa: E402


def parse_bytes(raw: bytes):
    return email.message_from_bytes(raw, policy=email.policy.default)


def csv_yaz(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


class MapiDateBoundaryTests(unittest.TestCase):
    def test_pst_scope_includes_only_inbox_root_and_excludes_gmail_tree(self):
        def folder(name, children=()):
            collection = Namespace(Count=len(children),
                                   Item=lambda index: children[index - 1])
            return Namespace(Name=name, DefaultItemType=0, Folders=collection)

        gmail = folder("08_Gmail", [folder("Gmail child")])
        archive = folder("Arşiv", [folder("03_Satinalma"), gmail])
        inbox = folder("Gelen Kutusu", [folder("Inbox child")])
        sent = folder("Gönderilmiş Öğeler")
        root = folder("PST", [archive, inbox, sent, folder("Silinmiş Öğeler")])
        store = Namespace(GetRootFolder=lambda: root)

        result = mail_export_mapi.scope_folders(store)

        self.assertEqual([(path, is_sent) for _, path, is_sent in result], [
            ("Arşiv", False), ("Arşiv\\03_Satinalma", False),
            ("Gelen Kutusu", False), ("Gönderilmiş Öğeler", True)])
        root.Folders = Namespace(Count=2, Item=lambda index: [archive, sent][index - 1])
        self.assertNotIn("Gelen Kutusu", [path for _, path, _ in
                                         mail_export_mapi.scope_folders(store)])

    def test_current_month_report_preserves_source_dates_and_partial_status(self):
        now = dt.datetime.now(dt.timezone(dt.timedelta(hours=3)))
        month = now.strftime("%Y-%m")
        rows = [
            {"_folder_path": "Gelen Kutusu", "_message_class": "IPM.Note",
             "receivedDateTime": month + "-02T10:00:00+03:00"},
            {"_folder_path": "Gönderilmiş Öğeler", "_message_class": "IPM.Note",
             "sentDateTime": month + "-03T12:00:00+03:00",
             "receivedDateTime": month + "-01T00:00:00+03:00"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mail_export_mapi.write_reports(root, month,
                                          mail_export_mapi.time.time(), 2,
                                          {"hukum": "GECTI", "sayilar": {
                                              "mail_satiri": 2, "atlanan": 14}},
                                          "PST", rows, previous_mail_count=1)
            report = (root / "ozet.txt").read_text(encoding="utf-8")
        self.assertIn("Durum: AY_ICI_KISMI", report)
        self.assertIn("Bu çalıştırmada eklenen mail: 1", report)
        self.assertIn("Kaynak en erken mail: " + month + "-02T10:00:00+03:00", report)
        self.assertIn("Kaynak en geç mail: " + month + "-03T12:00:00+03:00", report)

    def test_istanbul_ay_siniri_dasl_icin_utcye_cevrilir(self):
        start = dt.datetime(2025, 8, 1)
        end = dt.datetime(2025, 9, 1)

        received = mail_export_mapi.dasl_filter(start, end, sent=False)
        sent = mail_export_mapi.dasl_filter(start, end, sent=True)

        self.assertIn("urn:schemas:httpmail:datereceived", received)
        self.assertIn("2025-07-31 21:00", received)
        self.assertIn("2025-08-31 21:00", received)
        self.assertIn("urn:schemas:httpmail:date", sent)
        self.assertIn("2025-07-31 21:00", sent)
        self.assertIn("2025-08-31 21:00", sent)

    def test_mapi_ayni_message_id_farkli_entry_id_ile_atlanmaz(self):
        rows = [
            {"id": "entry-1", "internetMessageId": "<same@example.com>"},
            {"id": "entry-2", "internetMessageId": "<same@example.com>"},
            {"id": "entry-3", "internetMessageId": "<other@example.com>"},
        ]

        missing = mail_export_mapi.missing_mapi_rows(rows, {"entry-1"})

        self.assertEqual([row["id"] for row in missing], ["entry-2", "entry-3"])

    def test_mapi_ozel_oge_desteklenmeyen_com_alanini_atlar(self):
        class RecallItem:
            @property
            def SentOn(self):
                raise RuntimeError("Böyle bir arabirim desteklenmiyor")

        self.assertIsNone(mail_export_mapi.safe_attr(RecallItem(), "SentOn"))

    def test_mapi_ole_ekinde_filename_hatasi_displayname_fallback_kullanir(self):
        class OleAttachment:
            Type = 6
            Size = 1234

            @property
            def FileName(self):
                raise RuntimeError("Outlook bu ek türünde bu eylemi gerçekleştiremez")

            DisplayName = "OLE-gorsel.bmp"

            class PropertyAccessor:
                @staticmethod
                def GetProperty(_):
                    raise RuntimeError("özellik yok")

        info = mail_export_mapi.attachment_info(OleAttachment())

        self.assertEqual(info["name"], "OLE-gorsel.bmp")
        self.assertEqual(info["size"], 1234)

    def test_mapi_buyuk_imza_adli_gorseli_atlamaz(self):
        class LargeImage:
            FileName = "image001.jpg"
            DisplayName = "image001.jpg"
            Size = 300 * 1024

            class PropertyAccessor:
                @staticmethod
                def GetProperty(_):
                    raise RuntimeError("özellik yok")

        info = mail_export_mapi.attachment_info(LargeImage())
        self.assertFalse(info["embedded"])

    def test_parser_buyuk_imza_adli_gorseli_atlamaz(self):
        msg = EmailMessage()
        msg.set_content("Merhaba")
        msg.add_related(b"x" * (300 * 1024), maintype="image", subtype="jpeg",
                        cid="<image001>", filename="image001.jpg")

        _, _, attachments, _, _, _ = mail_yaz.govde_ve_ekler(msg)
        self.assertEqual(len(attachments), 1)
        self.assertFalse(attachments[0][3])

    def test_mapi_base64_sarili_msg_ve_eml_gercek_bayta_cozulur(self):
        payloads = [
            ("ek.msg", bytes.fromhex("D0CF11E0A1B11AE1") + b"x" * 32,
             "application/vnd.ms-outlook", ".msg"),
            ("ek.eml", b"From: sender@example.com\r\nSubject: test\r\n\r\nMerhaba",
             "message/rfc822", ".eml"),
        ]
        for name, source, expected_mime, expected_suffix in payloads:
            with self.subTest(name=name):
                outer = EmailMessage()
                outer.set_content("Gövde")
                outer.make_mixed()
                part = MIMEPart()
                part.set_content(source, maintype="message", subtype="rfc822",
                                 cte="base64")
                part.add_header("Content-Disposition", "attachment", filename=name)
                outer.attach(part)

                _, _, attachments, _, _, _ = mail_yaz.govde_ve_ekler(
                    parse_bytes(outer.as_bytes()))

                self.assertEqual(len(attachments), 1)
                self.assertEqual(attachments[0][1], expected_mime)
                self.assertEqual(attachments[0][2], source)
                self.assertTrue(attachments[0][0].lower().endswith(expected_suffix))

    def test_mapi_yalniz_ipm_note_ailesini_mail_sayar(self):
        self.assertTrue(mail_export_mapi.is_mail_message_class("IPM.Note"))
        self.assertTrue(mail_export_mapi.is_mail_message_class("IPM.Note.SMIME"))
        self.assertFalse(mail_export_mapi.is_mail_message_class(
            "IPM.Outlook.Recall"))
        self.assertFalse(mail_export_mapi.is_mail_message_class(
            "IPM.Schedule.Meeting.Resp.Pos"))

    def test_mapi_mail_disi_oge_final_baslik_artifakti_uretmez(self):
        self.assertFalse(mail_export_mapi.should_copy_final_header({
            "message_class": "IPM.Schedule.Meeting.Resp.Pos",
        }))
        self.assertTrue(mail_export_mapi.should_copy_final_header({
            "message_class": "IPM.Note",
        }))

    def test_mapi_mail_disi_isareti_govde_kurulduktan_sonra_kalir(self):
        msg = EmailMessage()
        msg.set_content("Gövde")
        mail_export_mapi.mark_nonmail_content_class(
            msg, "IPM.Schedule.Meeting.Resp.Pos")

        serialized = parse_bytes(msg.as_bytes())

        self.assertEqual(
            serialized.get("Content-Class"),
            "urn:content-classes:calendarmessage",
        )

    def test_mapi_envanter_tarihinde_gonderilmis_ogede_senton_oncelikli(self):
        class Row:
            def __init__(self):
                self.values = {
                    "SentOn": dt.datetime(2025, 1, 15, 12, 0),
                    "ReceivedTime": dt.datetime(2025, 2, 1, 12, 0),
                }

            def Item(self, name):
                return self.values[name]

        self.assertEqual(
            mail_export_mapi.inventory_date(Row(), sent=True),
            dt.datetime(2025, 1, 15, 12, 0),
        )

    def test_mapi_envanter_tarihinde_gelen_ogede_receivedtime_oncelikli(self):
        class Row:
            def __init__(self):
                self.values = {
                    "SentOn": dt.datetime(2024, 12, 31, 23, 0),
                    "ReceivedTime": dt.datetime(2025, 1, 1, 2, 0),
                }

            def Item(self, name):
                return self.values[name]

        self.assertEqual(
            mail_export_mapi.inventory_date(Row(), sent=False),
            dt.datetime(2025, 1, 1, 2, 0),
        )

    def test_mapi_mail_disi_ogeyi_yedekleyerek_ayirir(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "govdeler").mkdir()
            (run / "basliklar").mkdir()
            for sequence in ("202508-00001", "202508-00002"):
                (run / "govdeler" / f"{sequence}.txt").write_text(
                    sequence, encoding="utf-8")
                (run / "basliklar" / f"{sequence}.txt").write_text(
                    sequence, encoding="utf-8")

            mail_columns = [
                "sira_no", "klasor_yolu", "konu", "govde_dosya",
                "ek_klasoru", "mesaj_id", "internet_mesaj_id",
                "basliklar_dosya",
            ]
            csv_yaz(run / "mailler.csv", mail_columns, [
                {
                    "sira_no": "202508-00001",
                    "klasor_yolu": "Arşiv",
                    "konu": "Gerçek mail",
                    "govde_dosya": "govdeler\\202508-00001.txt",
                    "ek_klasoru": "",
                    "mesaj_id": "entry-mail",
                    "internet_mesaj_id": "<mail@example.com>",
                    "basliklar_dosya": "basliklar\\202508-00001.txt",
                },
                {
                    "sira_no": "202508-00002",
                    "klasor_yolu": "Gönderilmiş Öğeler",
                    "konu": "Toplantı yanıtı",
                    "govde_dosya": "govdeler\\202508-00002.txt",
                    "ek_klasoru": "",
                    "mesaj_id": "entry-meeting",
                    "internet_mesaj_id": "<meeting@example.com>",
                    "basliklar_dosya": "basliklar\\202508-00002.txt",
                },
            ])
            csv_yaz(run / "ekler.csv", ["sira_no", "mesaj_id", "kaydedilen_yol"], [])
            (run / "_mapi_metadata.json").write_text(json.dumps([
                {"id": "entry-mail", "_message_class": "IPM.Note"},
                {
                    "id": "entry-meeting",
                    "_message_class": "IPM.Schedule.Meeting.Resp.Pos",
                    "_folder_path": "Gönderilmiş Öğeler",
                },
            ]), encoding="utf-8")
            (run / "_gorulen.json").write_text(
                json.dumps(["<mail@example.com>", "<meeting@example.com>"]),
                encoding="utf-8")
            (run / "_uyarilar.json").write_text("[]", encoding="utf-8")
            (run / "_hatalar.json").write_text("[]", encoding="utf-8")
            (run / "kontrol.txt").write_text("eski", encoding="utf-8")

            state = mapi_reclassify_nonmail.inspect_run(run, 1)
            backup = mapi_reclassify_nonmail.apply_reclassification(state)

            _, remaining = mapi_reclassify_nonmail.read_csv(run / "mailler.csv")
            self.assertEqual([row["mesaj_id"] for row in remaining], ["entry-mail"])
            skipped = json.loads((run / "_atlanan.json").read_text(encoding="utf-8"))
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0]["mesaj_id"], "entry-meeting")
            self.assertFalse((run / "govdeler" / "202508-00002.txt").exists())
            self.assertTrue(
                (backup / "ayrilan_ogeler" / "govdeler" / "202508-00002.txt").exists())
            self.assertTrue((run / "govdeler" / "202508-00001.txt").exists())
            self.assertFalse((run / "_hatalar.json").exists())
            self.assertTrue((backup / "onarim_raporu.json").exists())


class MimeDecoderTests(unittest.TestCase):
    def test_charset_yok_utf8_ve_sondaki_nul_guvenle_cozulur(self):
        metin = "e-Arşiv: çığöşü"
        payload = base64.b64encode(metin.encode("utf-8") + b"\x00" * 7)
        raw = (
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: text/plain\r\n"
            b"Content-Transfer-Encoding: base64\r\n\r\n" + payload + b"\r\n"
        )

        govde, _, _, _, _, durum = mail_yaz.govde_ve_ekler(parse_bytes(raw))

        self.assertEqual(govde, metin)
        self.assertNotIn("\x00", govde)
        self.assertNotIn("\ufffd", govde)
        self.assertEqual(durum["metin_nul_kirpildi"], 7)
        self.assertEqual(durum["kaynak_replacement"], 0)

    def test_kaynaktaki_replacement_uydurularak_duzeltilmez(self):
        metin = "Kaynak zaten \ufffd karakteri taşıyor"
        payload = base64.b64encode(metin.encode("utf-8"))
        raw = (
            b"MIME-Version: 1.0\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Transfer-Encoding: base64\r\n\r\n" + payload + b"\r\n"
        )

        govde, _, _, _, _, durum = mail_yaz.govde_ve_ekler(parse_bytes(raw))

        self.assertIn("\ufffd", govde)
        self.assertEqual(durum["kaynak_replacement"], 1)

    def test_sifir_bayt_pdf_gercek_ek_olarak_kalir(self):
        msg = EmailMessage()
        msg.set_content("Merhaba", charset="utf-8")
        msg.add_attachment(b"", maintype="application", subtype="pdf",
                           filename="kaynakta-bos.pdf")

        _, _, ekler, _, _, _ = mail_yaz.govde_ve_ekler(msg)

        self.assertEqual(len(ekler), 1)
        self.assertEqual(ekler[0][0], "kaynakta-bos.pdf")
        self.assertEqual(ekler[0][2], b"")
        self.assertFalse(ekler[0][3])


class WriterEvidenceTests(unittest.TestCase):
    def test_mapi_gomulu_metadata_icerik_indirmeden_kayda_girer(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for name in ("ham", "govdeler", "basliklar", "ekler"):
                (run / name).mkdir()
            sira = "202508-00001"
            msg = EmailMessage()
            msg["Message-ID"] = "<mapi-inline@example.test>"
            msg["Subject"] = "MAPI gömülü metadata"
            msg["From"] = "gonderen@example.test"
            msg["To"] = "alan@example.test"
            msg.set_content("Gövde", charset="utf-8")
            (run / "ham" / (sira + ".eml")).write_bytes(msg.as_bytes())
            page = run / "page.json"
            page.write_text(json.dumps({"value": [{
                "id": "mapi-1",
                "internetMessageId": "<mapi-inline@example.test>",
                "receivedDateTime": "2025-08-01T10:00:00+03:00",
                "_mapi_gomulu": [{
                    "ad": "image001.png", "tip": "image/png",
                    "boyut_byte": 4321,
                }],
            }]}), encoding="utf-8")

            sonuc = mail_yaz.sayfayi_isle(
                str(page), str(run), "Arşiv", "202508", 1)

            self.assertEqual(sonuc["hata"], 0)
            self.assertEqual(sonuc["gomulu_atlanan"], 1)
            with (run / "ekler.csv").open(
                    "r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["ek_adi"], "image001.png")
            self.assertEqual(rows[0]["boyut_byte"], "4321")
            self.assertEqual(rows[0]["gomulu_mu"], "evet")
            self.assertEqual(rows[0]["indirildi_mi"], "hayir")

    def test_bos_ek_ham_kanitla_kayda_girer(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for name in ("ham", "govdeler", "basliklar", "ekler"):
                (run / name).mkdir()

            sira = "202603-00001"
            msg = EmailMessage()
            msg["Message-ID"] = "<bos-ek@example.test>"
            msg["Subject"] = "Kaynakta boş ek"
            msg["From"] = "gonderen@example.test"
            msg["To"] = "alan@example.test"
            msg.set_content("Gövde", charset="utf-8")
            msg.add_attachment(b"", maintype="application", subtype="pdf",
                               filename="bos.pdf")
            (run / "ham" / (sira + ".eml")).write_bytes(msg.as_bytes())

            metadata = {
                "value": [{
                    "id": "graph-1",
                    "internetMessageId": "<bos-ek@example.test>",
                    "receivedDateTime": "2026-03-01T10:00:00Z",
                    "sentDateTime": "2026-03-01T09:59:00Z",
                }]
            }
            page = run / "page.json"
            page.write_text(json.dumps(metadata), encoding="utf-8")

            sonuc = mail_yaz.sayfayi_isle(
                str(page), str(run), "Arşiv", "202603", 1)

            self.assertEqual(sonuc["hata"], 0)
            self.assertFalse((run / "ham" / (sira + ".eml")).exists())
            self.assertGreater((run / "sorunlu_eml" / (sira + ".eml")).stat().st_size, 0)
            uyarilar = json.loads((run / "_uyarilar.json").read_text(encoding="utf-8"))
            bos = [u for u in uyarilar if u["tur"] == "kaynakta_bos_ek"]
            self.assertEqual(len(bos), 1)
            self.assertEqual(bos[0]["adet"], 1)
            self.assertEqual(bos[0]["ham_dosya"], "sorunlu_eml\\" + sira + ".eml")

    def test_ham_temizlik_hatasi_commit_kaydini_korur_ve_kurtarilir(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for name in ("ham", "govdeler", "basliklar", "ekler"):
                (run / name).mkdir()
            sira = "202608-00001"
            msg = EmailMessage()
            msg["Message-ID"] = "<rollback@example.test>"
            msg["Subject"] = "Rollback"
            msg["From"] = "gonderen@example.test"
            msg["To"] = "alan@example.test"
            msg.set_content("Gövde", charset="utf-8")
            raw_path = run / "ham" / (sira + ".eml")
            raw_path.write_bytes(msg.as_bytes())
            page = run / "page.json"
            page.write_text(json.dumps({"value": [{
                "id": "graph-rollback",
                "receivedDateTime": "2026-08-01T10:00:00Z",
            }]}), encoding="utf-8")
            real_unlink = Path.unlink
            def fail_raw_unlink(path, *args, **kwargs):
                if path == raw_path:
                    raise PermissionError("test")
                return real_unlink(path, *args, **kwargs)
            with mock.patch.object(Path, "unlink", new=fail_raw_unlink):
                with self.assertRaises(PermissionError):
                    mail_yaz.sayfayi_isle(str(page), str(run), "Arşiv", "202608", 1)
            self.assertTrue(raw_path.exists())
            self.assertEqual(len(contract.rows(run / "mailler.csv")), 1)
            self.assertEqual(contract.read_json(run / "_islem.json")["state"], "COMMITTED")
            contract.recover(run)
            self.assertFalse(raw_path.exists())
            self.assertEqual(len(contract.rows(run / "mailler.csv")), 1)

    def test_takvim_temizlik_hatasi_atlama_kaydini_cogaltmaz(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for name in ("ham", "govdeler", "basliklar", "ekler"):
                (run / name).mkdir()
            sira = "202608-00001"
            msg = EmailMessage()
            msg["Message-ID"] = "<calendar@example.test>"
            msg["Content-Class"] = "urn:content-classes:calendarmessage"
            msg["Subject"] = "Toplanti"
            msg.set_content("Takvim ogesi", charset="utf-8")
            msg["Content-Class"] = "urn:content-classes:calendarmessage"
            raw_path = run / "ham" / (sira + ".eml")
            raw_path.write_bytes(msg.as_bytes())
            page = run / "page.json"
            page.write_text(json.dumps({"value": [{
                "id": "graph-calendar",
                "receivedDateTime": "2026-08-01T10:00:00Z",
            }]}), encoding="utf-8")

            real_unlink = Path.unlink
            def fail_raw_unlink(path, *args, **kwargs):
                if path == raw_path:
                    raise PermissionError("test")
                return real_unlink(path, *args, **kwargs)
            with mock.patch.object(Path, "unlink", new=fail_raw_unlink):
                with self.assertRaises(PermissionError):
                    mail_yaz.sayfayi_isle(str(page), str(run), "Arşiv", "202608", 1)
            self.assertTrue(raw_path.exists())
            self.assertEqual(len(contract.read_json(run / "_atlanan.json")), 1)
            contract.recover(run)
            self.assertFalse(raw_path.exists())
            self.assertEqual(len(contract.read_json(run / "_atlanan.json")), 1)

    def test_ek_yazisi_yarida_kalirsa_kismi_dosya_geri_alinir(self):
        class HalfWriteThenFail:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.handle.close()
                return False

            def write(self, data):
                self.handle.write(data[:max(1, len(data) // 2)])
                self.handle.flush()
                raise OSError("test yarim yazma")

        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for name in ("ham", "govdeler", "basliklar", "ekler"):
                (run / name).mkdir()
            sira = "202608-00001"
            msg = EmailMessage()
            msg["Message-ID"] = "<partial-attachment@example.test>"
            msg["Subject"] = "Kismi ek"
            msg["From"] = "gonderen@example.test"
            msg["To"] = "alan@example.test"
            msg.set_content("Govde", charset="utf-8")
            msg.add_attachment(
                b"0123456789", maintype="application", subtype="pdf",
                filename="teklif.pdf")
            raw_path = run / "ham" / (sira + ".eml")
            raw_path.write_bytes(msg.as_bytes())
            page = run / "page.json"
            page.write_text(json.dumps({"value": [{
                "id": "graph-partial",
                "receivedDateTime": "2026-08-01T10:00:00Z",
            }]}), encoding="utf-8")
            real_open = builtins.open

            def selective_open(path, mode="r", *args, **kwargs):
                handle = real_open(path, mode, *args, **kwargs)
                if str(path).endswith("teklif.pdf") and mode == "wb":
                    return HalfWriteThenFail(handle)
                return handle

            with mock.patch.object(builtins, "open", side_effect=selective_open):
                sonuc = mail_yaz.sayfayi_isle(
                    str(page), str(run), "Arşiv", "202608", 1)

            self.assertEqual(sonuc["hata"], 1)
            self.assertTrue(raw_path.exists())
            self.assertFalse((run / "mailler.csv").exists())
            self.assertEqual(list((run / "govdeler").iterdir()), [])
            self.assertEqual(list((run / "basliklar").iterdir()), [])
            self.assertEqual(list((run / "ekler").iterdir()), [])


class FolderDiscoveryTests(unittest.TestCase):
    def test_gelen_kutusu_koku_kapsama_alinir(self):
        class FakeGraph:
            def __init__(self):
                self.calls = []

            def json(self, path, params=None):
                self.calls.append((path, params))
                if path == "/me/mailFolders/archive":
                    return {"id": "archive-id", "displayName": "Arşiv"}
                if path == "/me/mailFolders/inbox":
                    return {"id": "inbox-id", "displayName": "Gelen Kutusu"}
                if path == "/me/mailFolders/sentitems":
                    return {"id": "sent-id", "displayName": "Gönderilmiş Öğeler"}
                if path == "/me/mailFolders/archive-id/childFolders":
                    return {"value": []}
                raise AssertionError("Beklenmeyen Graph çağrısı: " + str(path))

        graph = FakeGraph()
        folders = mail_export.discover_folders(graph)

        self.assertEqual(
            [folder["path"] for folder in folders],
            ["Arşiv", "Gelen Kutusu", "Gönderilmiş Öğeler"],
        )
        self.assertEqual(
            [folder["date_field"] for folder in folders],
            ["receivedDateTime", "receivedDateTime", "sentDateTime"],
        )
        self.assertFalse(any(
            path == "/me/mailFolders/inbox-id/childFolders"
            for path, _ in graph.calls
        ))


class IncrementalMonthTests(unittest.TestCase):
    def args(self, **changes):
        values = {
            "ay": None, "baslangic": None, "bitis": None,
            "hedef_kok": "X", "devam": False,
            "tamamlayici_tarama": False, "sadece_say": False,
        }
        values.update(changes)
        return Namespace(**values)

    def test_current_month_uses_stable_full_month_folder(self):
        start, end, name, monthly = mail_export.resolve_period(
            self.args(ay=mail_export.parse_month("2026-08")),
            today=mail_export.parse_date("2026-08-27"),
        )
        self.assertTrue(monthly)
        self.assertEqual(start.isoformat(), "2026-08-01")
        self.assertEqual(end.isoformat(), "2026-08-27")
        self.assertEqual(name, "agustos-2026")

    def test_past_month_uses_complete_calendar_month(self):
        _, end, name, monthly = mail_export.resolve_period(
            self.args(ay=mail_export.parse_month("2026-02")),
            today=mail_export.parse_date("2026-08-27"),
        )
        self.assertTrue(monthly)
        self.assertEqual(end.isoformat(), "2026-02-28")
        self.assertEqual(name, "subat-2026")

    def test_mapi_month_uses_same_stable_folder_name(self):
        start, end = mail_export_mapi.month_bounds("2025-08")
        self.assertEqual(
            mail_export_mapi.run_dir_for(start, end, "X"),
            Path("X") / "2025" / "agustos-2025",
        )

    def test_existing_flat_month_is_reused_and_ambiguous_month_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flat = root / "agustos-2025"
            flat.mkdir()
            start, end = mail_export_mapi.month_bounds("2025-08")
            self.assertEqual(mail_export_mapi.run_dir_for(start, end, root), flat)
            (root / "2025" / "agustos-2025").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "iki konumda"):
                mail_export_mapi.run_dir_for(start, end, root)

    def test_mapi_header_temporary_copy_is_removed_after_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "_gecici" / "202508-00001.txt"
            target = Path(tmp) / "basliklar" / raw.name
            raw.parent.mkdir()
            raw.write_bytes(b"transport headers")
            mail_export_mapi.finalize_header(raw, target)
            self.assertFalse(raw.exists())
            self.assertEqual(target.read_bytes(), b"transport headers")

    def test_repair_finds_year_month_and_legacy_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026" / "ocak-2026").mkdir(parents=True)
            (root / "010825-310825").mkdir()
            self.assertEqual(
                [p.relative_to(root).as_posix() for p in mail_onar.archive_runs(root)],
                ["010825-310825", "2026/ocak-2026"],
            )
            self.assertEqual(
                mail_onar.run_dates("2026/ocak-2026"),
                (dt.date(2026, 1, 1), dt.date(2026, 1, 31)),
            )

    def test_graph_repair_does_not_treat_mapi_run_as_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapi = root / "2025" / "ocak-2025"
            mapi.mkdir(parents=True)
            (mapi / "_klasorler.json").write_text(
                json.dumps({"store_id": "pst"}), encoding="utf-8")
            result = mail_onar.discover(root, root / "_onarim")
            self.assertEqual(result["records"], [])
            self.assertEqual(result["blockers"], [])

    def test_legacy_month_folder_prevents_split_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "010826-310826").mkdir()
            with self.assertRaisesRegex(SystemExit, "eski tarih kodlu"):
                mail_export.execute(self.args(
                    ay=mail_export.parse_month("2026-08"), hedef_kok=tmp))

    def test_graph_month_boundary_uses_istanbul_midnight(self):
        folder = {"id": "folder", "date_field": "receivedDateTime"}
        _, params = mail_export.message_query(
            folder, mail_export.parse_date("2026-08-01"),
            mail_export.parse_date("2026-09-01"), 0)
        self.assertIn("2026-07-31T21:00:00Z", params["$filter"])
        self.assertIn("2026-08-31T21:00:00Z", params["$filter"])
        self.assertEqual(
            mail_yaz.zaman_bicim("2026-07-31T21:30:00Z"),
            "2026-08-01 00:30")

    def test_future_month_is_rejected(self):
        with self.assertRaises(SystemExit):
            mail_export.resolve_period(
                self.args(ay=mail_export.parse_month("2026-09")),
                today=mail_export.parse_date("2026-08-27"),
            )

    def test_incremental_page_downloads_only_missing_ids(self):
        class FakeGraph:
            def __init__(self):
                self.downloaded = []

            def download(self, endpoint, sink):
                self.downloaded.append(endpoint)
                sink.write_bytes(b"raw-eml")

        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for name in ("ham", "govdeler", "basliklar", "ekler", "_gecici"):
                (run / name).mkdir()
            with (run / "mailler.csv").open(
                    "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=["sira_no", "mesaj_id"], delimiter=";")
                writer.writeheader()
                writer.writerow({"sira_no": "202608-00001", "mesaj_id": "old"})

            records = [
                {"id": "old"}, {"id": "new-1"}, {"id": "new-2"},
            ]
            page = run / "_gecici" / "sayfa-0001.json"
            pending = {}
            graph = FakeGraph()

            def fake_writer(_script_dir, page_path, _run_dir, _folder,
                            _prefix, starting_sequence):
                value = json.loads(page_path.read_text(encoding="utf-8"))["value"]
                with (run / "mailler.csv").open(
                        "a", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(
                        handle, fieldnames=["sira_no", "mesaj_id"], delimiter=";")
                    for offset, record in enumerate(value):
                        writer.writerow({
                            "sira_no": "202608-{0:05d}".format(
                                starting_sequence + offset),
                            "mesaj_id": record["id"],
                        })
                for offset in range(len(value)):
                    (run / "ham" / "202608-{0:05d}.eml".format(
                        starting_sequence + offset)).unlink()
                return {"hata": 0, "notlar": []}

            with mock.patch.object(mail_export, "run_mail_writer",
                                   side_effect=fake_writer):
                added = mail_export.process_incremental_page(
                    graph, SCRIPTS, run, page, records, "Arşiv",
                    "202608", 2, pending, [])

            self.assertEqual(added, 2)
            self.assertEqual(len(graph.downloaded), 2)
            self.assertTrue(all("old" not in item for item in graph.downloaded))
            self.assertEqual(pending, {})
            self.assertEqual(mail_export.processed_ids(run),
                             {"old", "new-1", "new-2"})

    def test_pending_commit_sonrasi_kesintide_tekrar_yazilmaz(self):
        class FakeGraph:
            pass

        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "ham").mkdir()
            with (run / "mailler.csv").open(
                    "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=["sira_no", "mesaj_id"], delimiter=";")
                writer.writeheader()
                writer.writerow({
                    "sira_no": "202608-00001", "mesaj_id": "graph-1",
                })
            pending = {
                "graph-1": {
                    "sira": 1,
                    "klasor_yolu": "Arşiv",
                    "kayit": {"id": "graph-1"},
                }
            }
            mail_export.save_pending(run, pending)

            with mock.patch.object(
                    mail_export, "process_assigned_records") as process_mock:
                mail_export.retry_pending(
                    FakeGraph(), SCRIPTS, run, pending, "202608", [])

            process_mock.assert_not_called()
            self.assertEqual(pending, {})
            self.assertEqual(
                json.loads((run / "_bekleyen.json").read_text(encoding="utf-8")),
                {},
            )

    def test_degisken_sayfalama_son_uzlastirmada_eksigi_ekler(self):
        class DummyTokenProvider:
            def __init__(self, _path):
                pass

            def get(self):
                return "token"

        def record(number):
            return {
                "id": "graph-{0:02d}".format(number),
                "receivedDateTime": "2026-07-01T10:{0:02d}:00Z".format(
                    number % 60),
                "sentDateTime": "2026-07-01T09:{0:02d}:00Z".format(
                    number % 60),
                "hasAttachments": False,
            }

        class MovingGraphClient:
            downloads = []

            def __init__(self, _tokens):
                self.first_page_calls = 0

            def json(self, path, params=None):
                if params is not None:
                    self.first_page_calls += 1
                    if self.first_page_calls == 1:
                        return {
                            "value": [record(i) for i in range(1, 51)],
                            "@odata.nextLink": "initial-page-2",
                        }
                    return {
                        "value": [record(i) for i in range(1, 51)],
                        "@odata.nextLink": "reconcile-page-2",
                    }
                if path == "initial-page-2":
                    # Ilk zincirde posta kutusu kaydigi icin 51 gorulmedi.
                    return {"value": [record(52)]}
                if path == "reconcile-page-2":
                    return {"value": [record(51), record(52)]}
                raise AssertionError("Beklenmeyen Graph cagrisi: " + str(path))

            def download(self, endpoint, sink):
                message_id = endpoint.split("/")[-2]
                self.downloads.append(message_id)
                msg = EmailMessage()
                msg["Message-ID"] = "<{0}@example.test>".format(message_id)
                msg["Subject"] = "Sayfalama " + message_id
                msg["From"] = "gonderen@example.test"
                msg["To"] = "alan@example.test"
                msg.set_content("Govde " + message_id, charset="utf-8")
                sink.write_bytes(msg.as_bytes())

        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(
                ay=mail_export.parse_month("2026-07"), hedef_kok=tmp)
            folders = [{
                "id": "folder-1", "path": "Arşiv",
                "date_field": "receivedDateTime",
            }]
            MovingGraphClient.downloads = []
            with mock.patch.object(mail_export, "TokenProvider", DummyTokenProvider), \
                    mock.patch.object(mail_export, "GraphClient", MovingGraphClient), \
                    mock.patch.object(mail_export, "discover_folders",
                                      return_value=folders):
                self.assertEqual(mail_export.execute(args), 0)

            run = Path(tmp) / "2026" / "temmuz-2026"
            with (run / "mailler.csv").open(
                    "r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))
            ids = [row["mesaj_id"] for row in rows]
            self.assertEqual(len(ids), 52)
            self.assertEqual(len(set(ids)), 52)
            self.assertIn("graph-51", ids)
            self.assertEqual(MovingGraphClient.downloads.count("graph-52"), 1)
            self.assertIn(
                "Son kaynak uzlaştırmasında 1 ek mesaj",
                (run / "ozet.txt").read_text(encoding="utf-8"),
            )

    def test_same_month_second_run_appends_only_new_message_end_to_end(self):
        class DummyTokenProvider:
            def __init__(self, _path):
                pass

            def get(self):
                return "token"

        class FakeGraphClient:
            records = []
            downloads = []

            def __init__(self, _tokens):
                pass

            def json(self, _path, params=None):
                skip = int((params or {}).get("$skip", 0))
                return {"value": self.records[skip:skip + 50]}

            def download(self, endpoint, sink):
                message_id = endpoint.split("/")[-2]
                self.downloads.append(message_id)
                msg = EmailMessage()
                msg["Message-ID"] = "<{0}@example.test>".format(message_id)
                msg["Subject"] = "Artımlı " + message_id
                msg["From"] = "gonderen@example.test"
                msg["To"] = "alan@example.test"
                msg.set_content("Gövde " + message_id, charset="utf-8")
                sink.write_bytes(msg.as_bytes())

        def record(message_id, day):
            return {
                "id": message_id,
                "receivedDateTime": "2026-07-{0:02d}T10:00:00Z".format(day),
                "sentDateTime": "2026-07-{0:02d}T09:59:00Z".format(day),
                "hasAttachments": False,
            }

        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(
                ay=mail_export.parse_month("2026-07"), hedef_kok=tmp)
            folders = [{
                "id": "folder-1", "path": "Arşiv",
                "date_field": "receivedDateTime",
            }]
            FakeGraphClient.records = [record("graph-1", 1)]
            FakeGraphClient.downloads = []
            with mock.patch.object(mail_export, "TokenProvider", DummyTokenProvider), \
                    mock.patch.object(mail_export, "GraphClient", FakeGraphClient), \
                    mock.patch.object(mail_export, "discover_folders",
                                      return_value=folders):
                self.assertEqual(mail_export.execute(args), 0)
                FakeGraphClient.records = [record("graph-1", 1), record("graph-2", 4)]
                self.assertEqual(mail_export.execute(args), 0)

            run = Path(tmp) / "2026" / "temmuz-2026"
            with (run / "mailler.csv").open(
                    "r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=";"))
            self.assertEqual([row["mesaj_id"] for row in rows],
                             ["graph-1", "graph-2"])
            self.assertEqual(FakeGraphClient.downloads, ["graph-1", "graph-2"])
            state = json.loads((run / "_durum.json").read_text(encoding="utf-8"))
            self.assertEqual(state["bu_calistirmada_eklenen"], 1)
            self.assertEqual(state["kapsam_durumu"], "AY_TAMAM")
            self.assertIn("KONTROL: GECTI",
                          (run / "kontrol.txt").read_text(encoding="utf-8"))

    def test_completion_scan_updates_only_existing_previous_months(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("agustos-2026", "temmuz-2026", "haziran-2026"):
                (root / "2026" / name).mkdir(parents=True)
            args = self.args(
                ay=mail_export.parse_month("2026-08"),
                hedef_kok=tmp, tamamlayici_tarama=True)

            def fake_execute(child):
                run_name = mail_export.monthly_run_name(child.ay)
                mail_export.atomic_json(root / "2026" / run_name / "_durum.json", {
                    "bu_calistirmada_eklenen": 2,
                })
                return 0

            with mock.patch.object(mail_export, "execute",
                                   side_effect=fake_execute) as execute_mock:
                self.assertEqual(mail_export.run_completion_scans(args), 0)

            self.assertEqual(execute_mock.call_count, 2)
            report = json.loads(
                (root / "2026" / "agustos-2026" / "_tamamlayici_sonuc.json")
                .read_text(encoding="utf-8"))
            self.assertEqual([row["durum"] for row in report["aylar"]],
                             ["GECTI", "GECTI", "ARSIV_YOK"])


class ControllerTests(unittest.TestCase):
    def kontrol(self, run: Path) -> dict:
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "kontrol.py"), "--kosu", str(run)],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
        return json.loads(proc.stdout)

    def temel_run(self, run: Path, body: str, ek_sayisi: int = 0) -> dict:
        (run / "govdeler").mkdir()
        (run / "basliklar").mkdir()
        (run / "ham").mkdir()
        body_rel = "govdeler\\202603-00001.txt"
        (run / "govdeler" / "202603-00001.txt").write_text(body, encoding="utf-8")
        header_rel = "basliklar\\202603-00001.txt"
        (run / "basliklar" / "202603-00001.txt").write_text(
            "Message-ID: <test@example.test>\n", encoding="utf-8")
        row = dict.fromkeys(mail_yaz.MAIL_KOLONLAR, "")
        row.update({
            "sira_no": "202603-00001",
            "klasor_yolu": "Arşiv",
            "oge_tipi": "mail",
            "govde_dosya": body_rel,
            "basliklar_dosya": header_rel,
            "ek_var_mi": "evet" if ek_sayisi else "hayir",
            "ek_sayisi": str(ek_sayisi),
            "mesaj_id": "graph-1",
            "internet_mesaj_id": "<test@example.test>",
        })
        csv_yaz(run / "mailler.csv", mail_yaz.MAIL_KOLONLAR, [row])
        return row

    def test_kanitsiz_nul_govdeyi_basarisiz_sayar(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.temel_run(run, "metin\x00")

            sonuc = self.kontrol(run)

            self.assertEqual(sonuc["hukum"], "BASARISIZ")
            self.assertTrue(any("NUL karakteri" in b for b in sonuc["bulgular"]))

    def test_eksik_baslik_dosyasini_basarisiz_sayar(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.temel_run(run, "gövde")
            (run / "basliklar" / "202603-00001.txt").unlink()

            sonuc = self.kontrol(run)

            self.assertEqual(sonuc["hukum"], "BASARISIZ")
            self.assertTrue(any("baslik dosyasi diskte yok" in b
                                for b in sonuc["bulgular"]))

    def test_kanitli_kaynak_replacement_uyariyla_gecer(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.temel_run(run, "kaynak \ufffd")
            (run / "sorunlu_eml").mkdir()
            proof = EmailMessage()
            proof["Message-ID"] = contract.rows(run / "mailler.csv")[0].get("internet_mesaj_id") or ""
            proof.set_content("kaynak \ufffd", charset="utf-8")
            proof_path = run / "sorunlu_eml" / "202603-00001.eml"
            proof_path.write_bytes(proof.as_bytes())
            (run / "_uyarilar.json").write_text(json.dumps([{
                "sira_no": "202603-00001",
                "tur": "kaynak_replacement",
                "adet": 1,
                "ham_dosya": "sorunlu_eml\\202603-00001.eml",
                "ham_sha256": contract.digest(proof_path),
                "internet_mesaj_id": str(proof["Message-ID"]),
                "mesaj_id": contract.rows(run / "mailler.csv")[0]["mesaj_id"],
            }]), encoding="utf-8")

            sonuc = self.kontrol(run)

            self.assertEqual(sonuc["hukum"], "GECTI")
            self.assertEqual(sonuc["sayilar"]["kanitli_replacement_mail"], 1)
            self.assertTrue(sonuc["uyarilar"])

    def test_kanitsiz_bos_ek_basarisiz_kanitli_bos_ek_gecer(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.temel_run(run, "gövde", ek_sayisi=1)
            ek = dict.fromkeys(mail_yaz.EK_KOLONLAR, "")
            ek.update({
                "sira_no": "202603-00001",
                "mesaj_id": "graph-1",
                "ek_adi": "bos.pdf",
                "ek_tipi": "application/pdf",
                "boyut_byte": "0",
                "gomulu_mu": "hayir",
                "indirildi_mi": "hayir",
                "hata": "icerik bos",
            })
            csv_yaz(run / "ekler.csv", mail_yaz.EK_KOLONLAR, [ek])
            self.assertEqual(self.kontrol(run)["hukum"], "BASARISIZ")

            (run / "sorunlu_eml").mkdir()
            proof = EmailMessage()
            proof["Message-ID"] = contract.rows(run / "mailler.csv")[0].get("internet_mesaj_id") or ""
            proof.set_content("gövde", charset="utf-8")
            proof.add_attachment(b"", maintype="application", subtype="pdf", filename="bos.pdf")
            proof_path = run / "sorunlu_eml" / "202603-00001.eml"
            proof_path.write_bytes(proof.as_bytes())
            (run / "_uyarilar.json").write_text(json.dumps([{
                "sira_no": "202603-00001",
                "tur": "kaynakta_bos_ek",
                "adet": 1,
                "detay": "bos.pdf",
                "ham_dosya": "sorunlu_eml\\202603-00001.eml",
                "ham_sha256": contract.digest(proof_path),
                "internet_mesaj_id": str(proof["Message-ID"]),
                "mesaj_id": contract.rows(run / "mailler.csv")[0]["mesaj_id"],
            }]), encoding="utf-8")

            sonuc = self.kontrol(run)
            self.assertEqual(sonuc["hukum"], "GECTI")
            self.assertEqual(sonuc["sayilar"]["kaynakta_bos_ek"], 1)

    def test_artimli_kaynak_manifestindeki_eksik_maili_yakalar(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.temel_run(run, "gövde")
            (run / "_kaynak_idler.json").write_text(json.dumps({
                "Arşiv": ["graph-1", "graph-2"],
            }), encoding="utf-8")

            sonuc = self.kontrol(run)

            self.assertEqual(sonuc["hukum"], "BASARISIZ")
            self.assertTrue(any(
                "canli kaynak taramasinda bulunan 1 mesaj yerelde yok" in bulgu
                for bulgu in sonuc["bulgular"]
            ))

    def test_artimli_arsiv_kaynaktan_kaybolan_eski_maili_korur(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.temel_run(run, "gövde")
            (run / "_kaynak_idler.json").write_text(
                json.dumps({"Arşiv": []}), encoding="utf-8")

            sonuc = self.kontrol(run)

            self.assertEqual(sonuc["hukum"], "GECTI")
            self.assertEqual(
                sonuc["sayilar"]["kaynakta_olmayip_yerelde_korunan"], 1)

    def test_indirilen_ek_diskte_kisalirsa_basarisiz_sayar(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.temel_run(run, "gövde", ek_sayisi=1)
            (run / "ekler" / "202603-00001").mkdir(parents=True)
            attachment = run / "ekler" / "202603-00001" / "teklif.pdf"
            attachment.write_bytes(b"x")
            ek = dict.fromkeys(mail_yaz.EK_KOLONLAR, "")
            ek.update({
                "sira_no": "202603-00001",
                "mesaj_id": "graph-1",
                "ek_adi": "teklif.pdf",
                "ek_tipi": "application/pdf",
                "boyut_byte": "25",
                "gomulu_mu": "hayir",
                "indirildi_mi": "evet",
                "kaydedilen_yol": "ekler\\202603-00001\\teklif.pdf",
            })
            csv_yaz(run / "ekler.csv", mail_yaz.EK_KOLONLAR, [ek])

            sonuc = self.kontrol(run)

            self.assertEqual(sonuc["hukum"], "BASARISIZ")
            self.assertTrue(any("ek boyutu uyusmuyor" in b
                                for b in sonuc["bulgular"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
