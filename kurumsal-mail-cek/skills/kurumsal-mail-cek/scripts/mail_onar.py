#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Geçmiş kurumsal mail koşularındaki kanıtlanmış metin/ek sorunlarını onarır.

Varsayılan çalışma yalnız hazırlıktır: sorunlu kayıtları bulur, Graph'tan salt-okunur
ham EML indirir, yeni parser ile ayrık bir çalışma alanında doğrular. Mevcut aylık
koşular ancak ikinci çağrıda ``--uygula`` verilirse değiştirilir. Uygulama öncesinde
dosya hash'leri yeniden kontrol edilir ve eski dosyalar yedeklenir.

Mail gövdeleri veya ek içerikleri stdout'a basılmaz; yalnız adet ve durum yazılır.
"""

from __future__ import annotations

import archive_contract as contract
import contextlib
import argparse
import csv
import datetime as dt
import email
import email.policy
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

from archive_layout import ARCHIVE_ROOT
from mail_export import (GraphClient, MONTH_NAMES, TokenProvider, graph_segment,
                         month_last_day, run_control)
from mail_yaz import (COKLU_BIRLESTIRICI, EK_KOLONLAR, MAIL_KOLONLAR,
                      govde_ve_ekler)


DEFAULT_ROOT = ARCHIVE_ROOT
RUN_PATTERN = re.compile(r"^\d{6}-\d{6}$")
MONTH_PATTERN = re.compile(
    r"^(ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|"
    r"eylul|ekim|kasim|aralik)-(\d{4})$")
CSV_ENCODING = "utf-8-sig"
WARNING_TYPES = {
    "metin_nul_kirpildi",
    "kaynak_replacement",
    "metin_fallback",
    "metin_cozulemeyen",
    "kaynakta_bos_ek",
}


try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def now_text() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def file_signature(path: Path) -> str:
    return sha256(path) if path.is_file() else "__YOK__"


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    os.replace(temp, path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".onarim.tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def csv_read(path: Path) -> tuple[list[str], list[dict]]:
    with path.open("r", encoding=CSV_ENCODING, newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        return list(reader.fieldnames or []), list(reader)


def csv_write_atomic(path: Path, columns: list[str], rows: list[dict]) -> None:
    temp = path.with_name(path.name + ".onarim.tmp")
    with temp.open("w", encoding=CSV_ENCODING, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter=";",
                                quoting=csv.QUOTE_MINIMAL,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".onarim.tmp")
    with source.open("rb") as src, temp.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())
    os.replace(temp, target)


def safe_member(root: Path, relative: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise RuntimeError("Koşu dışına çıkan göreli yol: " + relative) from exc
    return candidate


def text_stats(path: Path) -> dict:
    nul = replacement = 0
    try:
        with path.open("r", encoding="utf-8", errors="strict") as handle:
            while True:
                part = handle.read(1024 * 1024)
                if not part:
                    break
                nul += part.count("\x00")
                replacement += part.count("\ufffd")
    except UnicodeDecodeError:
        return {"nul": 0, "replacement": 0, "decode_error": True}
    return {"nul": nul, "replacement": replacement, "decode_error": False}


def string_stats(value: str) -> dict:
    return {
        "nul": value.count("\x00"),
        "replacement": value.count("\ufffd"),
        "length": len(value),
    }


def as_positive_int(value, default=0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def archive_runs(root: Path) -> list[Path]:
    """Düz eski koşuları ve yıl klasörlerindeki aylık koşuları bulur."""
    runs = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if RUN_PATTERN.fullmatch(entry.name) or MONTH_PATTERN.fullmatch(entry.name):
            runs.append(entry)
        elif re.fullmatch(r"\d{4}", entry.name):
            runs.extend(
                child for child in entry.iterdir()
                if child.is_dir() and (
                    RUN_PATTERN.fullmatch(child.name)
                    or (MONTH_PATTERN.fullmatch(child.name)
                        and child.name.endswith("-" + entry.name))))
    return sorted(runs)


def discover(root: Path, work: Path) -> dict:
    records: list[dict] = []
    blockers: list[str] = []
    run_signatures: dict[str, dict] = {}

    for run in archive_runs(root):
        run_key = run.relative_to(root).as_posix()
        folder_manifest = run / "_klasorler.json"
        if folder_manifest.is_file():
            source = json.loads(folder_manifest.read_text(encoding="utf-8"))
            if isinstance(source, dict) and "store_id" in source:
                continue  # Bu onarım Graph kimlikleri içindir; MAPI/PST ayrı kalır.
        mail_csv = run / "mailler.csv"
        if not mail_csv.is_file():
            blockers.append(run_key + ": mailler.csv yok")
            continue
        mail_columns, mail_rows = csv_read(mail_csv)
        if mail_columns != MAIL_KOLONLAR:
            blockers.append(run_key + ": mailler.csv şeması beklenenden farklı")
            continue
        by_sequence = {(row.get("sira_no") or "").strip(): row
                       for row in mail_rows}
        found: dict[str, dict] = {}

        for sequence, row in by_sequence.items():
            relative = (row.get("govde_dosya") or "").strip()
            if not relative or Path(relative).suffix.lower() != ".txt":
                continue
            body_path = safe_member(run, relative)
            if not body_path.is_file():
                continue
            stats = text_stats(body_path)
            if stats["nul"] or stats["replacement"] or stats["decode_error"]:
                found[sequence] = {
                    "run": run_key,
                    "sequence": sequence,
                    "graph_id": (row.get("mesaj_id") or "").strip(),
                    "internet_message_id": (
                        row.get("internet_mesaj_id") or "").strip(),
                    "body_relative": relative,
                    "old_body_stats": stats,
                    "old_body_sha256": sha256(body_path),
                    "empty_attachment_names": [],
                }

        attachment_csv = run / "ekler.csv"
        real_rows_by_sequence: dict[str, list[dict]] = {}
        if attachment_csv.is_file():
            attachment_columns, attachment_rows = csv_read(attachment_csv)
            if attachment_columns != EK_KOLONLAR:
                blockers.append(run_key + ": ekler.csv şeması beklenenden farklı")
                attachment_rows = []
            for attachment in attachment_rows:
                if (attachment.get("gomulu_mu") or "").strip() == "evet":
                    continue
                sequence = (attachment.get("sira_no") or "").strip()
                real_rows_by_sequence.setdefault(sequence, []).append(attachment)
                if (attachment.get("indirildi_mi") or "").strip() == "evet":
                    continue
                size = as_positive_int(attachment.get("boyut_byte"), 0)
                error = (attachment.get("hata") or "").strip()
                if size != 0 or error != "icerik bos":
                    blockers.append(
                        "{0}/{1}: kanıtsız indirilemeyen gerçek ek ({2})".format(
                            run_key, sequence,
                            (attachment.get("ek_adi") or "")[:80]))
                    continue
                row = by_sequence.get(sequence)
                if row is None:
                    blockers.append(
                        "{0}/{1}: ek satırının mail satırı yok".format(
                            run_key, sequence))
                    continue
                entry = found.setdefault(sequence, {
                    "run": run_key,
                    "sequence": sequence,
                    "graph_id": (row.get("mesaj_id") or "").strip(),
                    "internet_message_id": (
                        row.get("internet_mesaj_id") or "").strip(),
                    "body_relative": "",
                    "old_body_stats": {},
                    "old_body_sha256": "",
                    "empty_attachment_names": [],
                })
                entry["empty_attachment_names"].append(
                    (attachment.get("ek_adi") or "").strip())

        for sequence, entry in sorted(found.items()):
            row = by_sequence.get(sequence) or {}
            if not entry["graph_id"]:
                blockers.append(
                        "{0}/{1}: Graph mesaj kimliği yok".format(run_key, sequence))
            if entry["empty_attachment_names"]:
                expected_count = as_positive_int(row.get("ek_sayisi"), 0)
                csv_real_count = len(real_rows_by_sequence.get(sequence, []))
                if expected_count != csv_real_count:
                    blockers.append(
                        "{0}/{1}: mail ek_sayisi {2}, gerçek ek satırı {3}".format(
                            run_key, sequence, expected_count, csv_real_count))
                entry["expected_real_attachment_count"] = expected_count
            records.append(entry)

        run_signatures[run_key] = {
            "mailler.csv": file_signature(mail_csv),
            "_uyarilar.json": file_signature(run / "_uyarilar.json"),
        }

    result = {
        "version": 1,
        "created_at": now_text(),
        "root": str(root),
        "work": str(work),
        "status": "DISCOVERED",
        "records": records,
        "blockers": blockers,
        "run_signatures": run_signatures,
        "counts": {
            "affected_messages": len(records),
            "body_messages": sum(1 for item in records if item["body_relative"]),
            "old_nul": sum(item.get("old_body_stats", {}).get("nul", 0)
                           for item in records),
            "old_replacement": sum(
                item.get("old_body_stats", {}).get("replacement", 0)
                for item in records),
            "empty_attachment_rows": sum(
                len(item["empty_attachment_names"]) for item in records),
        },
    }
    atomic_json(work / "manifest.json", result)
    return result


def warning_records(entry: dict, text_state: dict,
                    empty_names: list[str]) -> list[dict]:
    sequence = entry["sequence"]
    graph_id = entry["graph_id"]
    raw_relative = os.path.join("sorunlu_eml", sequence + ".eml")
    records = []

    def add(kind: str, count: int, detail: str = "") -> None:
        if count:
            records.append({
                "sira_no": sequence,
                "mesaj_id": graph_id,
                "tur": kind,
                "adet": count,
                "detay": detail,
                "ham_dosya": raw_relative,
            })

    add("metin_nul_kirpildi", text_state["metin_nul_kirpildi"])
    add("kaynak_replacement", text_state["kaynak_replacement"])
    add("metin_fallback", text_state["metin_fallback"],
        ",".join(text_state["fallback_kodlamalar"]))
    add("metin_cozulemeyen", text_state["metin_cozulemeyen"])
    add("kaynakta_bos_ek", len(empty_names),
        COKLU_BIRLESTIRICI.join(empty_names))
    return records


def prepare(root: Path, work: Path, manifest: dict) -> dict:
    if manifest["blockers"]:
        manifest["status"] = "BLOCKED"
        atomic_json(work / "manifest.json", manifest)
        return manifest

    raw_root = work / "eml"
    body_root = work / "govdeler"
    raw_root.mkdir(parents=True, exist_ok=True)
    body_root.mkdir(parents=True, exist_ok=True)

    cache_root = Path(os.environ.get("LOCALAPPDATA") or root)
    graph = GraphClient(
        TokenProvider(cache_root / "KilicMailExporter" / "msal_cache.json"))
    total = len(manifest["records"])
    failures: list[str] = []

    for index, entry in enumerate(manifest["records"], start=1):
        run_name = entry["run"]
        sequence = entry["sequence"]
        raw_path = raw_root / run_name / (sequence + ".eml")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if not raw_path.is_file() or raw_path.stat().st_size == 0:
                graph.download(
                    "/me/messages/{0}/$value".format(
                        graph_segment(entry["graph_id"])),
                    raw_path,
                )
            entry["raw_sha256"] = sha256(raw_path)
            entry["raw_bytes"] = raw_path.stat().st_size

            with raw_path.open("rb") as handle:
                msg = email.message_from_binary_file(
                    handle, policy=email.policy.default)
            expected_mid = entry["internet_message_id"]
            actual_mid = (msg.get("Message-ID") or "").strip()
            if expected_mid and actual_mid and expected_mid != actual_mid:
                raise RuntimeError("Message-ID uyuşmuyor")

            body, body_type, attachments, _, _, text_state = govde_ve_ekler(msg)
            new_stats = string_stats(body)
            if entry["body_relative"]:
                if not body.strip():
                    raise RuntimeError("yeni gövde boş")
                if new_stats["nul"]:
                    raise RuntimeError("yeni gövdede NUL kaldı")
                if (new_stats["replacement"]
                        > text_state["kaynak_replacement"]):
                    raise RuntimeError("kaynakla açıklanamayan U+FFFD oluştu")
                staged_body = body_root / run_name / (sequence + ".txt")
                staged_body.parent.mkdir(parents=True, exist_ok=True)
                staged_body.write_text(body, encoding="utf-8")
                entry["staged_body"] = str(staged_body.relative_to(work))
                entry["staged_body_sha256"] = sha256(staged_body)
                entry["new_body_stats"] = new_stats
                entry["new_body_type"] = body_type
                entry["new_body_preview"] = re.sub(r"\s+", " ", body)[:255]

            real_attachments = [item for item in attachments if not item[3]]
            empty_names = [item[0] for item in real_attachments if not item[2]]
            expected_empty = entry["empty_attachment_names"]
            if expected_empty:
                if Counter(empty_names) != Counter(expected_empty):
                    raise RuntimeError(
                        "0 byte ek adedi/adları ham EML ile uyuşmuyor")
                expected_real = entry.get("expected_real_attachment_count", 0)
                if len(real_attachments) != expected_real:
                    raise RuntimeError(
                        "ham EML gerçek ek sayısı CSV ile uyuşmuyor")
            entry["verified_empty_attachment_names"] = empty_names
            entry["warnings"] = warning_records(entry, text_state, empty_names)
            entry["prepared"] = True
        except Exception as exc:
            entry["prepared"] = False
            entry["prepare_error"] = type(exc).__name__ + ": " + str(exc)
            failures.append("{0}/{1}: {2}".format(
                run_name, sequence, entry["prepare_error"]))

        if index == 1 or index % 100 == 0 or index == total:
            print("HAZIRLIK {0}/{1} | hata {2}".format(
                index, total, len(failures)), flush=True)
            atomic_json(work / "manifest.json", manifest)

    manifest["prepare_failures"] = failures
    manifest["prepared_at"] = now_text()
    manifest["status"] = "READY" if not failures else "BLOCKED"
    manifest["counts"]["new_nul"] = sum(
        item.get("new_body_stats", {}).get("nul", 0)
        for item in manifest["records"])
    manifest["counts"]["new_replacement"] = sum(
        item.get("new_body_stats", {}).get("replacement", 0)
        for item in manifest["records"])
    manifest["counts"]["source_warning_records"] = sum(
        len(item.get("warnings", [])) for item in manifest["records"])
    atomic_json(work / "manifest.json", manifest)
    return manifest


def verify_unchanged(root: Path, work: Path, manifest: dict) -> list[str]:
    failures = []
    for run_name, signatures in manifest["run_signatures"].items():
        if not any(item["run"] == run_name for item in manifest["records"]):
            continue
        run = root / run_name
        for relative, expected in signatures.items():
            actual = file_signature(run / relative)
            if actual != expected:
                failures.append(
                    "{0}/{1}: hazırlıktan sonra değişmiş".format(
                        run_name, relative))
    for item in manifest["records"]:
        if item["body_relative"]:
            path = safe_member(root / item["run"], item["body_relative"])
            if file_signature(path) != item["old_body_sha256"]:
                failures.append(
                    "{0}/{1}: gövde hazırlıktan sonra değişmiş".format(
                        item["run"], item["sequence"]))
        raw_path = work / "eml" / item["run"] / (item["sequence"] + ".eml")
        if file_signature(raw_path) != item.get("raw_sha256"):
            failures.append(
                "{0}/{1}: hazırlanan ham EML değişmiş".format(
                    item["run"], item["sequence"]))
        if item["body_relative"]:
            staged = work / item["staged_body"]
            if file_signature(staged) != item.get("staged_body_sha256"):
                failures.append(
                    "{0}/{1}: hazırlanan gövde değişmiş".format(
                        item["run"], item["sequence"]))
    return failures


def backup_file(source: Path, target: Path) -> None:
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def apply_repair(root: Path, work: Path, manifest: dict) -> dict:
    with contextlib.ExitStack() as stack:
        for name in sorted({item["run"] for item in manifest["records"]}):
            run = root / name
            stack.enter_context(contract.lock(contract.export_lock_path(run)))
            contract.source_guard(run, "graph")
        return _apply_repair(root, work, manifest)


def _apply_repair(root: Path, work: Path, manifest: dict) -> dict:
    if manifest.get("status") != "READY":
        raise RuntimeError("Manifest READY değil; mevcut durum: "
                           + str(manifest.get("status")))
    changes = verify_unchanged(root, work, manifest)
    if changes:
        raise RuntimeError("Uygulama durduruldu:\n- " + "\n- ".join(changes))

    backup_root = work / "yedek"
    if backup_root.exists():
        raise RuntimeError("Yedek klasörü zaten var; körlemesine üzerine yazılmadı: "
                           + str(backup_root))

    affected_by_run: dict[str, list[dict]] = {}
    for item in manifest["records"]:
        affected_by_run.setdefault(item["run"], []).append(item)

    # Tüm yedekler tamamlanmadan aylık koşulara dokunma.
    for run_name, items in affected_by_run.items():
        run = root / run_name
        target = backup_root / run_name
        for name in ("mailler.csv", "_uyarilar.json", "kontrol.txt", "ozet.txt", "_aktarim.json"):
            backup_file(run / name, target / name)
        for item in items:
            backup_file(run / "_kayitlar" / (item["sequence"] + ".json"),
                        target / "_kayitlar" / (item["sequence"] + ".json"))
            if item["body_relative"]:
                backup_file(safe_member(run, item["body_relative"]),
                            safe_member(target, item["body_relative"]))

    for run_index, (run_name, items) in enumerate(
            sorted(affected_by_run.items()), start=1):
        run = root / run_name
        contract.invalidate(run, "ONARIM_SURUYOR")
        columns, rows = csv_read(run / "mailler.csv")
        row_index = {(row.get("sira_no") or "").strip(): row for row in rows}

        warning_path = run / "_uyarilar.json"
        existing_warnings = []
        if warning_path.is_file():
            existing_warnings = json.loads(warning_path.read_text(encoding="utf-8"))
            if not isinstance(existing_warnings, list):
                raise RuntimeError(run_name + ": _uyarilar.json liste değil")

        replacement_keys = {
            (item["sequence"], kind)
            for item in items for kind in WARNING_TYPES
        }
        merged_warnings = [
            warning for warning in existing_warnings
            if ((warning.get("sira_no"), warning.get("tur"))
                not in replacement_keys)
        ]

        for item in items:
            sequence = item["sequence"]
            raw_source = work / "eml" / run_name / (sequence + ".eml")
            atomic_copy(raw_source, run / "sorunlu_eml" / (sequence + ".eml"))
            if item["body_relative"]:
                staged_body = work / item["staged_body"]
                atomic_copy(staged_body, safe_member(run, item["body_relative"]))
                row = row_index.get(sequence)
                if row is None:
                    raise RuntimeError(run_name + "/" + sequence
                                       + ": mailler.csv satırı yok")
                row["govde_onizleme"] = item["new_body_preview"]
                row["govde_tipi"] = item["new_body_type"]
            raw_msg = email.message_from_bytes(raw_source.read_bytes(), policy=email.policy.default)
            for warning in item.get("warnings", []):
                warning["ham_sha256"] = contract.digest(raw_source)
                warning["internet_mesaj_id"] = (raw_msg.get("Message-ID") or "").strip()
                warning["mesaj_id"] = row_index[sequence].get("mesaj_id", "")
            merged_warnings.extend(item.get("warnings", []))

        csv_write_atomic(run / "mailler.csv", columns, rows)
        atomic_json(warning_path, merged_warnings)
        index = contract.record_index(run)
        for item in items:
            raw = work / "eml" / run_name / (item["sequence"] + ".eml")
            row = row_index[item["sequence"]]
            contract.record_receipt(run, item["sequence"], row.get("mesaj_id", ""), raw, index)
        print("UYGULANDI {0}/{1} | {2} | {3} mesaj".format(
            run_index, len(affected_by_run), run_name, len(items)), flush=True)

    manifest["status"] = "APPLIED"
    manifest["applied_at"] = now_text()
    manifest["backup_root"] = str(backup_root)
    atomic_json(work / "manifest.json", manifest)
    return manifest


def run_dates(run_name: str) -> tuple[dt.date, dt.date]:
    name = Path(run_name).name
    monthly = MONTH_PATTERN.fullmatch(name)
    if monthly:
        month_name, year_text = monthly.groups()
        month = next((number for number, label in MONTH_NAMES.items()
                      if label == month_name), None)
        if month is None:
            raise ValueError("Bilinmeyen ay klasörü: " + name)
        start = dt.date(int(year_text), month, 1)
        return start, month_last_day(start)
    start_text, end_text = name.split("-", 1)
    return (dt.datetime.strptime(start_text, "%d%m%y").date(),
            dt.datetime.strptime(end_text, "%d%m%y").date())


def control_report(control: dict) -> str:
    verdict = str(control.get("hukum") or "BASARISIZ")
    findings = control.get("bulgular") or []
    warnings = control.get("uyarilar") or []
    lines = ["KONTROL: " + verdict]
    lines.extend("- " + str(item) for item in findings)
    if not findings:
        lines.append("- Eksik veya tutarsız kayıt bulunmadı.")
    if warnings:
        lines.extend(["", "UYARILAR:"])
        lines.extend("- " + str(item) for item in warnings)
    lines.extend(["", json.dumps(control, ensure_ascii=False, indent=2)])
    return "\n".join(lines) + "\n"


def repair_summary_section(control: dict, affected: int) -> str:
    warnings = control.get("uyarilar") or []
    counts = control.get("sayilar") or {}
    lines = [
        "MAIL PARSER ONARIM DOGRULAMASI",
        "Durum: " + str(control.get("hukum") or "BASARISIZ"),
        "Onarilan/kanitlanan mesaj: " + str(affected),
        "NUL kalan govde: " + str(counts.get("govde_nul", 0)),
        "Kanitli kaynak U+FFFD maili: "
        + str(counts.get("kanitli_replacement_mail", 0)),
        "Kaynakta 0 byte gercek ek: "
        + str(counts.get("kaynakta_bos_ek", 0)),
        "Ham kanit: sorunlu_eml/",
    ]
    if warnings:
        lines.extend(["", "Kaynak/veri uyarilari:"])
        lines.extend("- " + str(item) for item in warnings)
    return "\n".join(lines) + "\n"


def refresh_reports(root: Path, work: Path, manifest: dict) -> dict:
    if manifest.get("status") != "APPLIED":
        raise RuntimeError("Rapor yenileme için manifest APPLIED olmalı")

    script_dir = Path(__file__).resolve().parent
    affected_by_run: dict[str, int] = {}
    for item in manifest["records"]:
        affected_by_run[item["run"]] = affected_by_run.get(item["run"], 0) + 1

    # Önce yedi koşunun tamamını doğrula. Tek başarısızlıkta hiçbir rapora yazma.
    controls: dict[str, dict] = {}
    failures = []
    for run_name in sorted(affected_by_run):
        start, end = run_dates(run_name)
        control = run_control(script_dir, root / run_name, start, end)
        controls[run_name] = control
        if control.get("hukum") != "GECTI":
            failures.append(run_name + ": "
                            + "; ".join(control.get("bulgular") or []))
        print("DOGRULANDI {0} | {1}".format(
            run_name, control.get("hukum")), flush=True)
    if failures:
        raise RuntimeError("Raporlar yenilenmedi:\n- "
                           + "\n- ".join(failures))

    marker = "\nMAIL PARSER ONARIM DOGRULAMASI\n"
    for run_name in sorted(controls):
        run = root / run_name
        control = controls[run_name]
        atomic_text(run / "kontrol.txt", control_report(control))

        summary_path = run / "ozet.txt"
        original = (summary_path.read_text(encoding="utf-8")
                    if summary_path.is_file() else "")
        base = original.split(marker, 1)[0].rstrip()
        section = repair_summary_section(
            control, affected_by_run[run_name]).rstrip()
        refreshed = ((base + marker + section + "\n") if base
                     else (section + "\n"))
        atomic_text(summary_path, refreshed)
        start, end = run_dates(run_name)
        with contract.ExportSession(run, "graph", start.strftime("%Y%m")) as session:
            fresh_control = run_control(script_dir, run, start, end)
            contract.atomic_json(run / "_kontrol_sonuc.json", fresh_control)
            atomic_text(run / "kontrol.txt", control_report(fresh_control))
            session.finish(0 if fresh_control.get("hukum") == "GECTI" else 2)
            if fresh_control.get("hukum") != "GECTI":
                raise RuntimeError("Onarım sonrası güncel kontrol başarısız: " + run_name)

    manifest["reports_refreshed_at"] = now_text()
    manifest["report_verdicts"] = {
        run: control.get("hukum") for run, control in controls.items()
    }
    atomic_json(work / "manifest.json", manifest)
    return manifest


def print_summary(manifest: dict) -> None:
    counts = manifest.get("counts") or {}
    print(json.dumps({
        "status": manifest.get("status"),
        "etkilenen_mesaj": counts.get("affected_messages", 0),
        "govde_mesaji": counts.get("body_messages", 0),
        "eski_nul": counts.get("old_nul", 0),
        "eski_replacement": counts.get("old_replacement", 0),
        "bos_ek_satiri": counts.get("empty_attachment_rows", 0),
        "yeni_nul": counts.get("new_nul"),
        "yeni_replacement": counts.get("new_replacement"),
        "engel": len(manifest.get("blockers") or [])
                 + len(manifest.get("prepare_failures") or []),
    }, ensure_ascii=False, indent=2), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Geçmiş mail koşularını kanıtlı ve geri alınabilir onarır")
    parser.add_argument("--kok", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--calisma", type=Path,
                        help="Onarım çalışma/yedek klasörü")
    parser.add_argument("--yalniz-kesfet", action="store_true")
    parser.add_argument("--uygula", action="store_true")
    parser.add_argument("--raporlari-yenile", action="store_true")
    args = parser.parse_args()

    root = args.kok.resolve()
    if not root.is_dir():
        raise SystemExit("Mail kökü yok: " + str(root))
    work = (args.calisma or (root / "_onarim" / "mail-parser-20260827")).resolve()
    try:
        work.relative_to(root)
    except ValueError as exc:
        raise SystemExit("Çalışma klasörü mail kökü altında olmalı") from exc
    work.mkdir(parents=True, exist_ok=True)

    manifest_path = work / "manifest.json"
    if args.uygula and args.raporlari_yenile:
        raise SystemExit("--uygula ve --raporlari-yenile birlikte kullanılamaz")
    if args.raporlari_yenile:
        if not manifest_path.is_file():
            raise SystemExit("Uygulanmış manifest yok: " + str(manifest_path))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = refresh_reports(root, work, manifest)
    elif args.uygula:
        if not manifest_path.is_file():
            raise SystemExit("Hazır manifest yok: " + str(manifest_path))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = apply_repair(root, work, manifest)
    else:
        if (manifest_path.is_file()
                and json.loads(manifest_path.read_text(encoding="utf-8"))
                .get("status") == "APPLIED"):
            raise SystemExit("Bu çalışma zaten uygulanmış; yeni çalışma klasörü seçin")
        manifest = discover(root, work)
        if not args.yalniz_kesfet:
            manifest = prepare(root, work, manifest)
    print_summary(manifest)
    return 0 if manifest.get("status") not in ("BLOCKED",) else 2


if __name__ == "__main__":
    raise SystemExit(main())
