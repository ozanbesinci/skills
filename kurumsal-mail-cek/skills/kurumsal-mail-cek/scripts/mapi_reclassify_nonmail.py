#!/usr/bin/env python3
"""MAPI MessageClass bilgisine göre mail dışı öğeleri yedekli biçimde ayırır.

Varsayılan çalışma salt okunur ön kontroldür. Değişiklik için --apply gerekir.
"""

from __future__ import annotations

import archive_contract as contract
import argparse
import csv
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


MAIL_PREFIX = "ipm.note"
BACKUP_FILES = (
    "mailler.csv",
    "ekler.csv",
    "_atlanan.json",
    "_gorulen.json",
    "_uyarilar.json",
    "_hatalar.json",
    "kontrol.txt",
    "ozet.txt",
)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if not reader.fieldnames:
            raise RuntimeError(f"CSV başlığı bulunamadı: {path}")
        return list(reader.fieldnames), list(reader)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
                delimiter=";",
                lineterminator="\n",
                extrasaction="raise",
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def safe_artifact(run_dir: Path, relative_value: str) -> Path | None:
    value = (relative_value or "").strip()
    if not value:
        return None
    candidate = (run_dir / Path(value.replace("\\", os.sep))).resolve()
    try:
        candidate.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Çekim klasörü dışındaki yola izin verilmez: {value}") from exc
    return candidate


def prune_nested(paths: set[Path]) -> list[Path]:
    ordered = sorted(paths, key=lambda item: (len(item.parts), str(item).lower()))
    result: list[Path] = []
    for path in ordered:
        if any(parent == path or parent in path.parents for parent in result):
            continue
        result.append(path)
    return result


def inspect_run(run_dir: Path, expected_count: int) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    metadata = load_json(run_dir / "_mapi_metadata.json", [])
    if not isinstance(metadata, list):
        raise RuntimeError("_mapi_metadata.json liste biçiminde değil")

    nonmail: dict[str, dict[str, Any]] = {}
    for item in metadata:
        message_id = str(item.get("id", "")).strip()
        message_class = str(item.get("_message_class", "")).strip()
        if not message_id or message_class.lower().startswith(MAIL_PREFIX):
            continue
        if message_id in nonmail:
            raise RuntimeError(f"Metadata içinde yinelenen mail dışı ID: {message_id}")
        nonmail[message_id] = item

    if len(nonmail) != expected_count:
        raise RuntimeError(
            f"Mail dışı kaynak öğesi {len(nonmail)}; beklenen {expected_count}. İşlem durduruldu."
        )

    mail_fields, mail_rows = read_csv(run_dir / "mailler.csv")
    attachment_fields, attachment_rows = read_csv(run_dir / "ekler.csv")
    selected = [row for row in mail_rows if row.get("mesaj_id", "") in nonmail]
    if len(selected) != expected_count:
        raise RuntimeError(
            f"CSV'de eşleşen mail dışı öğe {len(selected)}; beklenen {expected_count}. İşlem durduruldu."
        )
    selected_ids = [row.get("mesaj_id", "") for row in selected]
    if len(set(selected_ids)) != expected_count:
        raise RuntimeError("CSV'de mail dışı ID tekrar ediyor; işlem durduruldu")

    sequence_numbers = {row.get("sira_no", "") for row in selected}
    selected_attachments = [
        row for row in attachment_rows if row.get("sira_no", "") in sequence_numbers
    ]

    artifact_candidates: set[Path] = set()
    body_found = 0
    header_found = 0
    attachment_dirs_found = 0
    for row in selected:
        for field, counter_name in (
            ("govde_dosya", "body"),
            ("basliklar_dosya", "header"),
            ("ek_klasoru", "attachment_dir"),
        ):
            path = safe_artifact(run_dir, row.get(field, ""))
            if path is None or not path.exists():
                continue
            artifact_candidates.add(path)
            if counter_name == "body":
                body_found += 1
            elif counter_name == "header":
                header_found += 1
            else:
                attachment_dirs_found += 1
    for row in selected_attachments:
        path = safe_artifact(run_dir, row.get("kaydedilen_yol", ""))
        if path is not None and path.exists():
            artifact_candidates.add(path)

    return {
        "run_dir": run_dir,
        "metadata": metadata,
        "nonmail": nonmail,
        "mail_fields": mail_fields,
        "mail_rows": mail_rows,
        "attachment_fields": attachment_fields,
        "attachment_rows": attachment_rows,
        "selected": selected,
        "selected_ids": set(selected_ids),
        "sequence_numbers": sequence_numbers,
        "selected_attachments": selected_attachments,
        "artifacts": prune_nested(artifact_candidates),
        "body_found": body_found,
        "header_found": header_found,
        "attachment_dirs_found": attachment_dirs_found,
    }


def apply_reclassification(state: dict[str, Any]) -> Path:
    run = state["run_dir"]
    with contract.lock(contract.export_lock_path(run)):
        # İnceleme ile yazma arasında değişiklik olmuşsa mevcut durumu yeniden değerlendir.
        fresh = inspect_run(run, len(state["selected"]))
        if fresh["selected"] != state["selected"] or fresh["mail_rows"] != state["mail_rows"]:
            raise ValueError("Ön kontrolden sonra arşiv değişti")
        return _apply_reclassification(fresh)


def _apply_reclassification(state: dict[str, Any]) -> Path:
    run_dir: Path = state["run_dir"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = run_dir / "_onarim_yedek" / f"{stamp}-mapi-mail-disi"
    if backup_dir.exists():
        raise RuntimeError(f"Yedek klasörü zaten var: {backup_dir}")
    backup_dir.mkdir(parents=True)

    original_dir = backup_dir / "degisen_dosyalar"
    original_dir.mkdir()
    for name in BACKUP_FILES:
        source = run_dir / name
        if source.exists():
            shutil.copy2(source, original_dir / name)

    contract.invalidate(run_dir, "YENIDEN_DOGRULAMA_GEREKLI")
    selected_ids: set[str] = state["selected_ids"]
    sequence_numbers: set[str] = state["sequence_numbers"]
    kept_mail_rows = [
        row for row in state["mail_rows"] if row.get("mesaj_id", "") not in selected_ids
    ]
    kept_attachment_rows = [
        row
        for row in state["attachment_rows"]
        if row.get("sira_no", "") not in sequence_numbers
    ]

    existing_skipped = load_json(run_dir / "_atlanan.json", [])
    if not isinstance(existing_skipped, list):
        raise RuntimeError("_atlanan.json liste biçiminde değil")
    skipped_by_id = {
        str(item.get("mesaj_id", "")): item
        for item in existing_skipped
        if str(item.get("mesaj_id", "")).strip()
    }
    for row in state["selected"]:
        message_id = row["mesaj_id"]
        meta = state["nonmail"][message_id]
        skipped_by_id[message_id] = {
            "sira_no": row.get("sira_no", ""),
            "klasor_yolu": row.get("klasor_yolu", meta.get("_folder_path", "")),
            "mesaj_id": message_id,
            "neden": "mail dışı Outlook öğesi",
            "message_class": meta.get("_message_class", ""),
        }
    skipped_rows = sorted(
        skipped_by_id.values(), key=lambda item: (str(item.get("sira_no", "")), str(item.get("mesaj_id", "")))
    )

    warnings = load_json(run_dir / "_uyarilar.json", [])
    if not isinstance(warnings, list):
        raise RuntimeError("_uyarilar.json liste biçiminde değil")
    kept_warnings = [
        item for item in warnings if str(item.get("sira_no", "")) not in sequence_numbers
    ]
    seen_internet_ids = sorted(
        {
            row.get("internet_mesaj_id", "").strip()
            for row in kept_mail_rows
            if row.get("internet_mesaj_id", "").strip()
        }
    )

    atomic_write_csv(run_dir / "mailler.csv", state["mail_fields"], kept_mail_rows)
    atomic_write_csv(
        run_dir / "ekler.csv", state["attachment_fields"], kept_attachment_rows
    )
    atomic_write_json(run_dir / "_atlanan.json", skipped_rows)
    atomic_write_json(run_dir / "_uyarilar.json", kept_warnings)
    atomic_write_json(run_dir / "_gorulen.json", seen_internet_ids)

    artifacts_dir = backup_dir / "ayrilan_ogeler"
    moved: list[str] = []
    for source in state["artifacts"]:
        if not source.exists():
            continue
        relative = source.relative_to(run_dir)
        destination = artifacts_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        moved.append(str(relative))

    index = contract.record_index(run_dir)
    for row in state["selected"]:
        seq = row["sira_no"]
        receipt = run_dir / "_kayitlar" / (seq + ".json")
        if receipt.exists():
            target = original_dir / "_kayitlar" / receipt.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(receipt, target)
        contract.record_receipt(run_dir, seq, row["mesaj_id"], None, index)
    for stale_name in ("_hatalar.json", "kontrol.txt", "ozet.txt"):
        stale = run_dir / stale_name
        if stale.exists():
            stale.unlink()

    report = {
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "reason": "MAPI MessageClass ile mail dışı Outlook öğelerini ayırma",
        "mail_rows_before": len(state["mail_rows"]),
        "mail_rows_after": len(kept_mail_rows),
        "reclassified_count": len(state["selected"]),
        "attachment_rows_removed": len(state["selected_attachments"]),
        "artifacts_moved": moved,
        "items": [
            {
                "sira_no": row.get("sira_no", ""),
                "mesaj_id": row.get("mesaj_id", ""),
                "klasor_yolu": row.get("klasor_yolu", ""),
                "konu": row.get("konu", ""),
                "message_class": state["nonmail"][row["mesaj_id"]].get(
                    "_message_class", ""
                ),
            }
            for row in state["selected"]
        ],
    }
    atomic_write_json(backup_dir / "onarim_raporu.json", report)
    return backup_dir


def print_summary(state: dict[str, Any], backup_dir: Path | None = None) -> None:
    class_counts: dict[str, int] = {}
    for meta in state["nonmail"].values():
        message_class = str(meta.get("_message_class", "")) or "(boş)"
        class_counts[message_class] = class_counts.get(message_class, 0) + 1
    print(f"Mail dışı kaynak öğesi: {len(state['nonmail'])}")
    print(f"CSV eşleşmesi: {len(state['selected'])}")
    print(f"Ayrılacak ek satırı: {len(state['selected_attachments'])}")
    print(f"Bulunan gövde dosyası: {state['body_found']}")
    print(f"Bulunan başlık dosyası: {state['header_found']}")
    print(f"Bulunan ek klasörü: {state['attachment_dirs_found']}")
    print("MessageClass: " + ", ".join(f"{key}={value}" for key, value in sorted(class_counts.items())))
    if backup_dir is None:
        print("ÖN KONTROL GEÇTİ — değişiklik yapılmadı. Uygulamak için --apply kullanın.")
    else:
        print(f"ONARIM UYGULANDI — yedek: {backup_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Ay çekim klasörü")
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="Ön kontrol sonrası değişiklikleri uygula")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        raise SystemExit(f"Çekim klasörü bulunamadı: {run_dir}")
    state = inspect_run(run_dir, args.expected_count)
    backup_dir = apply_reclassification(state) if args.apply else None
    print_summary(state, backup_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
