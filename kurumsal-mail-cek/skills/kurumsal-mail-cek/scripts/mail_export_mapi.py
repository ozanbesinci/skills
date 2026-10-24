#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Çevrimiçi Arşiv'i veya yerel PST'yi klasik Outlook/MAPI üzerinden dışa aktarır.

Graph In-Place Archive posta kutusunu göstermez. Bu araç yalnız adı
"Çevrimiçi Arşiv - ..." olan Exchange store'unu okur; birincil posta kutusuna
uygulanmaz. GetTable ile metadata'yı hızlı toplar, içerikleri tek süreçte açar
ve mevcut mail_yaz.py doğrulama/yazma hattını kullanır.

Kullanım:
  python mail_export_mapi.py --ay 2025-08
  python mail_export_mapi.py --ay 2025-08 --sadece-say
  python mail_export_mapi.py --ay 2025-08 --pst D:\\AI-BACKUP\\pst\\agustos-2025.pst
"""

import archive_contract as contract
import argparse
import base64
import csv
import datetime as dt
import email
import email.encoders
import email.policy
import filecmp
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from email.headerregistry import Address
from email.message import EmailMessage, MIMEPart
from email.parser import Parser
from email.utils import format_datetime, formataddr
from pathlib import Path

import pythoncom
import pywintypes
import win32com.client
from archive_layout import ARCHIVE_ROOT, run_directory

from mail_yaz import (CSV_AYIRICI, CSV_KODLAMA, COKLU_BIRLESTIRICI,
                      GOMULU_BOYUT_SINIRI, IMZA_DESEN, MAIL_KOLONLAR,
                      ascii_slug, cakismasiz, dosya_adi_temizle,
                      html_to_metin, sayfayi_isle, yol_sinirla)


OUT_ROOT = ARCHIVE_ROOT

STORE_PREFIX = "Çevrimiçi Arşiv - "
ARCHIVE_NAME = "Arşiv"
SENT_NAME = "Gönderilmiş Öğeler"
INBOX_NAME = "Gelen Kutusu"
EXCLUDED_ARCHIVE_CHILD = "08_Gmail"
PAGE_SIZE = 25
ISTANBUL_UTC_OFFSET = dt.timedelta(hours=3)
MONTH_NAMES = {
    1: "ocak", 2: "subat", 3: "mart", 4: "nisan",
    5: "mayis", 6: "haziran", 7: "temmuz", 8: "agustos",
    9: "eylul", 10: "ekim", 11: "kasim", 12: "aralik",
}

PROP = "http://schemas.microsoft.com/mapi/proptag/"
PR_SENDER_SMTP = PROP + "0x5D01001F"
PR_SENT_REP_SMTP = PROP + "0x5D02001F"
PR_DISPLAY_TO = PROP + "0x0E04001F"
PR_DISPLAY_CC = PROP + "0x0E03001F"
PR_INTERNET_MESSAGE_ID = PROP + "0x1035001F"
PR_HASATTACH = PROP + "0x0E1B000B"
PR_MESSAGE_FLAGS = PROP + "0x0E070003"
PR_TRANSPORT_HEADERS = PROP + "0x007D001F"
PR_SMTP_ADDRESS = PROP + "0x39FE001E"
PR_ATTACH_MIME_TAG = PROP + "0x370E001F"
PR_ATTACH_CONTENT_ID = PROP + "0x3712001F"
PR_ATTACH_CONTENT_DISPOSITION = PROP + "0x3716001F"
PR_ATTACHMENT_HIDDEN = PROP + "0x7FFE000B"

TABLE_COLUMNS = [
    "EntryID", "Subject", "SenderName", "MessageClass", "ReceivedTime", "SentOn", "Size", "Importance",
    "CreationTime", "LastModificationTime", PR_SENDER_SMTP,
    PR_SENT_REP_SMTP, PR_DISPLAY_TO, PR_DISPLAY_CC,
    PR_INTERNET_MESSAGE_ID, PR_HASATTACH, PR_MESSAGE_FLAGS,
]


def console_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def atomic_json(path, value):
    contract.atomic_json(path, value)


def month_bounds(value):
    match = re.fullmatch(r"(\d{4})-(\d{2})", value or "")
    if not match:
        raise ValueError("--ay YYYY-MM biçiminde olmalı")
    year, month = map(int, match.groups())
    start = dt.datetime(year, month, 1)
    if month == 12:
        end = dt.datetime(year + 1, 1, 1)
    else:
        end = dt.datetime(year, month + 1, 1)
    return start, end


def run_dir_for(start, end, root):
    del end  # Aylık koşu adı tarih aralığından değil ay kimliğinden türetilir.
    name = MONTH_NAMES[start.month] + "-" + str(start.year)
    return run_directory(root, start.year, name)


def norm_text(value):
    if value is None:
        return ""
    return str(value).replace("\x00", "").strip()


def iso_value(value):
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%dT%H:%M:%S+03:00")
    return norm_text(value)


def safe_prop(obj, name, default=""):
    try:
        value = obj.PropertyAccessor.GetProperty(name)
        return default if value is None else value
    except Exception:
        return default


def safe_attr(obj, name, default=None):
    """Özel Outlook öğe sınıflarında desteklenmeyen COM alanını güvenle atla."""
    if obj is None:
        return default
    try:
        value = getattr(obj, name)
        return default if value is None else value
    except Exception:
        return default


def is_mail_message_class(value):
    """Skill kapsamındaki Outlook mail sınıfları yalnız IPM.Note* ailesidir."""
    return norm_text(value).lower().startswith("ipm.note")


def mark_nonmail_content_class(message, message_class):
    """Mail dışı MAPI öğesini writer'ın kapsam dışı kapısına işaretle."""
    if message_class and not is_mail_message_class(message_class):
        message["Content-Class"] = "urn:content-classes:calendarmessage"


def row_value(row, name, default=""):
    try:
        value = row.Item(name)
        return default if value is None else value
    except Exception:
        return default


def find_direct(folder, name):
    for child in folder_children(folder):
        if norm_text(child.Name) == name:
            return child
    return None


def folder_children(folder):
    """COM koleksiyonunu indisle gez.

    Outlook bazı derin Çevrimiçi Arşiv klasörlerini IEnumVARIANT gezintisinde
    sessizce atlayabiliyor. Count/Item yolu aynı klasörleri eksiksiz döndürüyor.
    """
    collection = folder.Folders
    return [collection.Item(index)
            for index in range(1, int(collection.Count) + 1)]


def archive_store(namespace):
    matches = []
    for store in namespace.Stores:
        display = norm_text(store.DisplayName)
        if display.startswith(STORE_PREFIX):
            matches.append(store)
    if len(matches) != 1:
        raise RuntimeError(
            "Çevrimiçi Arşiv store sayısı 1 olmalı; bulunan: {0}".format(
                [norm_text(x.DisplayName) for x in matches]))
    return matches[0]


def normalized_path(value):
    return os.path.normcase(os.path.abspath(os.path.normpath(str(value))))


def pst_store(namespace, pst_path, use_attached=False):
    """PST store'unu ve bu çağrıda bağlanıp bağlanmadığını döndür.

    Çağıran, kaynak PST yerine önceden oluşturulmuş bir çalışma kopyası
    vermelidir. Store ana akışın ``finally`` bloğunda profilden ayrılır.
    ``use_attached`` yalnız Ozan'ın açık talimatıyla doğrudan, zaten bağlı PST'yi
    kullanmak içindir; bu durumda store profilden ayrılmaz.
    """
    path = Path(pst_path).resolve()
    if not path.is_file():
        raise FileNotFoundError("PST bulunamadı: " + str(path))
    if path.suffix.lower() != ".pst":
        raise ValueError("--pst bir .pst dosyası olmalı: " + str(path))

    target = normalized_path(path)
    for store in namespace.Stores:
        file_path = norm_text(getattr(store, "FilePath", ""))
        if file_path and normalized_path(file_path) == target:
            if use_attached:
                return store, False
            raise RuntimeError("PST zaten Outlook'a bağlı: " + str(path))

    namespace.AddStoreEx(str(path), 3)  # olStoreUnicode
    deadline = time.time() + 15
    while time.time() < deadline:
        for store in namespace.Stores:
            file_path = norm_text(getattr(store, "FilePath", ""))
            if file_path and normalized_path(file_path) == target:
                return store, True
        time.sleep(0.25)
    raise RuntimeError("Bağlanan PST Outlook store listesinde bulunamadı: " + str(path))


def scope_folders(store):
    root = store.GetRootFolder()
    archive = find_direct(root, ARCHIVE_NAME)
    sent = find_direct(root, SENT_NAME)
    inbox = find_direct(root, INBOX_NAME)
    if archive is None or sent is None:
        raise RuntimeError("Çevrimiçi Arşiv içinde Arşiv/Gönderilmiş Öğeler bulunamadı")

    result = []

    def walk(folder, path):
        if getattr(folder, "DefaultItemType", -1) == 0:
            result.append((folder, path, False))
        for child in folder_children(folder):
            child_name = norm_text(child.Name)
            if path == ARCHIVE_NAME and child_name == EXCLUDED_ARCHIVE_CHILD:
                continue
            walk(child, path + "\\" + child_name)

    walk(archive, ARCHIVE_NAME)
    if inbox is not None and getattr(inbox, "DefaultItemType", -1) == 0:
        result.append((inbox, INBOX_NAME, False))
    result.append((sent, SENT_NAME, True))
    return result


def inventory_folders(store):
    """PST'deki bütün klasörleri kapsam filtresi uygulamadan döndür."""
    root = store.GetRootFolder()
    result = []

    def walk(folder, path):
        result.append((folder, path))
        for child in folder_children(folder):
            child_name = norm_text(child.Name) or "(adsiz)"
            child_path = child_name if not path else path + "\\" + child_name
            walk(child, child_path)

    for child in folder_children(root):
        walk(child, norm_text(child.Name) or "(adsiz)")
    return result


def inventory_date(row, sent):
    primary = row_value(row, "SentOn" if sent else "ReceivedTime")
    fallback = row_value(row, "ReceivedTime" if sent else "SentOn")
    return primary or fallback


def full_pst_inventory(store, start, end):
    """Tam PST sadakat kapısı için klasör/sınıf/tarih envanteri üret."""
    folders = []
    class_counts = {}
    total_items = 0
    total_mail = 0
    undated_mail = 0
    outside_month = 0
    earliest = None
    latest = None

    for folder, path in inventory_folders(store):
        # pywin32 bazı özel klasörlerde COM optional parametresi için ``None``
        # gönderince E_INVALIDARG döndürüyor. Boş DASL dizesi bütün öğeleri seçer.
        table = folder.GetTable("", 0)
        table.Columns.RemoveAll()
        active = []
        for column in ("MessageClass", "ReceivedTime", "SentOn"):
            try:
                table.Columns.Add(column)
                active.append(column)
            except pywintypes.com_error:
                pass
        if "MessageClass" not in active:
            raise RuntimeError(path + ": envanter MessageClass kolonunu vermedi")

        folder_items = 0
        folder_mail = 0
        folder_other = 0
        folder_undated = 0
        folder_outside = 0
        folder_earliest = None
        folder_latest = None
        sent = path == SENT_NAME or path.startswith(SENT_NAME + "\\")
        while not table.EndOfTable:
            row = table.GetNextRow()
            folder_items += 1
            total_items += 1
            message_class = norm_text(row_value(row, "MessageClass")) or "(bos)"
            class_counts[message_class] = class_counts.get(message_class, 0) + 1
            if not is_mail_message_class(message_class):
                folder_other += 1
                continue

            folder_mail += 1
            total_mail += 1
            value = inventory_date(row, sent)
            if not value or not hasattr(value, "replace"):
                folder_undated += 1
                undated_mail += 1
                continue
            value = value.replace(tzinfo=None)
            folder_earliest = value if folder_earliest is None else min(folder_earliest, value)
            folder_latest = value if folder_latest is None else max(folder_latest, value)
            earliest = value if earliest is None else min(earliest, value)
            latest = value if latest is None else max(latest, value)
            if value < start or value >= end:
                folder_outside += 1
                outside_month += 1

        folders.append({
            "klasor_yolu": path,
            "toplam_oge": folder_items,
            "mail": folder_mail,
            "mail_disi": folder_other,
            "tarihsiz_mail": folder_undated,
            "ay_disi_mail": folder_outside,
            "en_erken": iso_value(folder_earliest),
            "en_gec": iso_value(folder_latest),
        })

    return {
        "klasor_sayisi": len(folders),
        "toplam_oge": total_items,
        "mail": total_mail,
        "mail_disi": total_items - total_mail,
        "tarihsiz_mail": undated_mail,
        "ay_disi_mail": outside_month,
        "en_erken": iso_value(earliest),
        "en_gec": iso_value(latest),
        "siniflar": dict(sorted(class_counts.items())),
        "klasorler": folders,
        "gecti": undated_mail == 0 and outside_month == 0,
    }


def dasl_filter(start, end, sent):
    # Outlook Object Model'de SentOn'un DASL karşılığı ``date`` alanıdır.
    # ``datesent`` hata vermeden sıfır satır döndürür; bu sessiz eksikliktir.
    # DASL tarih dizelerini UTC yorumlar. Ay sınırları İstanbul yerel saatiyle
    # verildiği için +03:00'ten UTC'ye çevrilmezse ayın ilk üç saati sessizce
    # dışarıda kalır ve sonraki ayın ilk üç saati içeri sızar.
    field = "urn:schemas:httpmail:date" if sent else "urn:schemas:httpmail:datereceived"
    utc_start = start - ISTANBUL_UTC_OFFSET
    utc_end = end - ISTANBUL_UTC_OFFSET
    return ('@SQL="{0}" >= \'{1}\' AND "{0}" < \'{2}\''.format(
        field, utc_start.strftime("%Y-%m-%d %H:%M"),
        utc_end.strftime("%Y-%m-%d %H:%M")))


def table_metadata(folder, path, start, end, sent):
    table = folder.GetTable(dasl_filter(start, end, sent), 0)
    table.Columns.RemoveAll()
    active_columns = []
    for column in TABLE_COLUMNS:
        try:
            table.Columns.Add(column)
            active_columns.append(column)
        except pywintypes.com_error:
            # Zorunlu alanlar aşağıda ayrıca doğrulanır; bazı Outlook
            # sürümleri standart zaman kolonlarından birini vermeyebilir.
            pass
    for required in ("EntryID", "ReceivedTime" if not sent else "SentOn"):
        if required not in active_columns:
            raise RuntimeError(path + ": GetTable zorunlu kolonu vermedi: " + required)

    rows = []
    while not table.EndOfTable:
        row = table.GetNextRow()
        flags = int(row_value(row, PR_MESSAGE_FLAGS, 0) or 0)
        importance = int(row_value(row, "Importance", 1) or 1)
        rows.append({
            "id": norm_text(row_value(row, "EntryID")),
            "_folder_path": path,
            "_source_size": int(row_value(row, "Size", 0) or 0),
            "subject": norm_text(row_value(row, "Subject")),
            "_message_class": norm_text(row_value(row, "MessageClass")),
            "_sender_name": norm_text(row_value(row, "SenderName")),
            "receivedDateTime": iso_value(row_value(row, "ReceivedTime")),
            "sentDateTime": iso_value(row_value(row, "SentOn")),
            "createdDateTime": iso_value(row_value(row, "CreationTime")),
            "lastModifiedDateTime": iso_value(row_value(row, "LastModificationTime")),
            "isRead": bool(flags & 0x1),
            "isDraft": bool(flags & 0x8),
            "importance": {0: "low", 1: "normal", 2: "high"}.get(importance, "normal"),
            "hasAttachments": bool(row_value(row, PR_HASATTACH, False)),
            "internetMessageId": norm_text(row_value(row, PR_INTERNET_MESSAGE_ID)),
            "_sender_smtp": norm_text(row_value(row, PR_SENDER_SMTP)),
            "_sent_rep_smtp": norm_text(row_value(row, PR_SENT_REP_SMTP)),
            "_display_to": norm_text(row_value(row, PR_DISPLAY_TO)),
            "_display_cc": norm_text(row_value(row, PR_DISPLAY_CC)),
        })
    rows.sort(key=lambda x: (x.get("sentDateTime") if sent else x.get("receivedDateTime"),
                             x.get("id")))
    return rows


def read_existing(run_dir):
    ids, mids, max_seq = set(), set(), 0
    csv_path = run_dir / "mailler.csv"
    if csv_path.exists():
        with csv_path.open("r", encoding=CSV_KODLAMA, newline="") as handle:
            for row in csv.DictReader(handle, delimiter=CSV_AYIRICI):
                if row.get("mesaj_id"):
                    ids.add(row["mesaj_id"].strip())
                if row.get("internet_mesaj_id"):
                    mids.add(row["internet_mesaj_id"].strip())
                match = re.fullmatch(r"\d{6}-(\d{5})", row.get("sira_no", ""))
                if match:
                    max_seq = max(max_seq, int(match.group(1)))
    skipped_path = run_dir / "_atlanan.json"
    if skipped_path.exists():
        for row in json.loads(skipped_path.read_text(encoding="utf-8")):
            if row.get("mesaj_id"):
                ids.add(row["mesaj_id"].strip())
            match = re.fullmatch(r"\d{6}-(\d{5})", row.get("sira_no", ""))
            if match:
                max_seq = max(max_seq, int(match.group(1)))
    return ids, mids, max_seq


def missing_mapi_rows(rows, existing_ids):
    """Yalnız aynı PST EntryID'si yereldeyse öğeyi tamamlanmış say.

    Internet Message-ID tekil değildir: aynı mail farklı klasörlerde ayrı kopya
    olabilir; Outlook recall öğeleri de özgün mailin Message-ID'sini yeniden
    kullanabilir. Bu nedenle Message-ID üzerinden atlamak gerçek kayıt kaybıdır.
    """
    return [row for row in rows if row.get("id") not in existing_ids]


def recipient_smtp(recipient):
    try:
        entry = recipient.AddressEntry
        smtp = norm_text(safe_prop(entry, PR_SMTP_ADDRESS))
        if smtp:
            return smtp
        if norm_text(entry.Type).upper() == "EX":
            user = entry.GetExchangeUser()
            if user is not None:
                smtp = norm_text(user.PrimarySmtpAddress)
                if smtp:
                    return smtp
        return norm_text(entry.Address)
    except Exception:
        try:
            return norm_text(recipient.Address)
        except Exception:
            return ""


def recipient_headers(item):
    groups = {1: [], 2: [], 3: []}
    try:
        for recipient in item.Recipients:
            name = norm_text(recipient.Name)
            smtp = recipient_smtp(recipient)
            value = formataddr((name, smtp)) if smtp else name
            if value:
                groups.setdefault(int(recipient.Type), []).append(value)
    except Exception:
        pass
    fallback = {1: norm_text(getattr(item, "To", "")),
                2: norm_text(getattr(item, "CC", "")),
                3: norm_text(getattr(item, "BCC", ""))}
    return {key: ", ".join(groups.get(key) or ([fallback[key]] if fallback[key] else []))
            for key in (1, 2, 3)}


def original_headers(item):
    return norm_text(safe_prop(item, PR_TRANSPORT_HEADERS))


def header_from_transport(raw, name):
    if not raw:
        return ""
    try:
        parsed = Parser(policy=email.policy.default).parsestr(raw + "\n\n")
        return norm_text(parsed.get(name, ""))
    except Exception:
        return ""


def attachment_info(attachment):
    # OLE eklerde Outlook ``FileName`` erişimine aralıklı olarak hata verir;
    # aynı ekin ``DisplayName`` alanı ve SaveAsFile yolu çalışır. Bir özellik
    # hatası bütün maili kaybettirmesin, ama ek payload'ını yine tam kaydet.
    raw_name = (norm_text(safe_attr(attachment, "FileName", ""))
                or norm_text(safe_attr(attachment, "DisplayName", ""))
                or "ek")
    name = dosya_adi_temizle(raw_name)
    size = int(getattr(attachment, "Size", 0) or 0)
    mime = norm_text(safe_prop(attachment, PR_ATTACH_MIME_TAG))
    if "/" not in mime:
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    disposition = norm_text(safe_prop(
        attachment, PR_ATTACH_CONTENT_DISPOSITION)).lower()
    content_id = norm_text(safe_prop(attachment, PR_ATTACH_CONTENT_ID))
    hidden = bool(safe_prop(attachment, PR_ATTACHMENT_HIDDEN, False))
    if disposition not in ("inline", "attachment"):
        disposition = "inline" if (hidden or content_id) else "attachment"
    embedded = False
    if disposition == "attachment":
        embedded = False
    elif (mime.startswith("image/") and size < GOMULU_BOYUT_SINIRI
          and (disposition == "inline" or content_id)):
        embedded = True
    return {
        "name": name, "size": size, "mime": mime,
        "disposition": disposition, "content_id": content_id,
        "embedded": embedded,
    }


def attachment_bytes(attachment, temp_dir, name):
    path = Path(cakismasiz(yol_sinirla(str(temp_dir), name)))
    attachment.SaveAsFile(str(path))
    data = path.read_bytes()
    try:
        path.unlink()
    except OSError:
        pass
    return name, data


def add_attachments(message, attachments, temp_dir, meta):
    source_embedded = []
    for attachment in attachments:
        info = attachment_info(attachment)
        if PROCESS.skip_embedded_payload and info["embedded"]:
            source_embedded.append({
                "ad": info["name"], "tip": info["mime"],
                "boyut_byte": info["size"],
            })
            continue
        name, data = attachment_bytes(attachment, temp_dir, info["name"])
        mime = info["mime"]
        maintype, subtype = mime.split("/", 1)
        disposition = info["disposition"]
        content_id = info["content_id"]

        part = MIMEPart()
        part.set_content(data, maintype=maintype, subtype=subtype,
                         cte="base64")
        part.add_header("Content-Disposition", disposition, filename=name)
        if content_id:
            part["Content-ID"] = "<" + content_id.strip("<>") + ">"
        message.attach(part)
    if source_embedded:
        meta["_mapi_gomulu"] = source_embedded


def build_eml(namespace, store_id, meta, eml_path, raw_header_path, temp_dir):
    item = namespace.GetItemFromID(meta["id"], store_id)
    local_item = None
    prefetch = None
    if PROCESS.prefetch_msg:
        # Çevrimiçi Arşiv öğesi yerel OST'de değildir. SaveAs(olMSGUnicode)
        # bütün öğeyi tek sunucu çağrısıyla getirir. Bundan sonraki gövde ve ek
        # okumalarını çevrimiçi nesneden değil bu yerel MSG'den yapmak gerekir;
        # aksi halde her imza görseli ayrı Exchange/MAPI çağrısı üretir.
        prefetch = Path(temp_dir) / ("_prefetch_" +
                                    base64.urlsafe_b64encode(
                                        meta["id"].encode("utf-8"))[:24]
                                    .decode("ascii") + ".msg")
        if prefetch.exists():
            prefetch.unlink()
        item.SaveAs(str(prefetch), 9)
        local_item = namespace.OpenSharedItem(str(prefetch))
        item = local_item
    raw_headers = original_headers(item)
    raw_header_path.write_text(raw_headers or "MAPI transport başlığı yok\n",
                               encoding="utf-8")

    msg = EmailMessage(policy=email.policy.SMTP)
    sender_smtp = norm_text(safe_prop(item, PR_SENDER_SMTP)) or meta.get("_sender_smtp", "")
    sender_name = meta.get("_sender_name", "")
    if not sender_smtp:
        sender_smtp = norm_text(safe_attr(item, "SenderEmailAddress", ""))
    original_from = header_from_transport(raw_headers, "From")
    msg["From"] = (original_from or
                   (formataddr((sender_name, sender_smtp))
                    if sender_smtp else sender_name))
    # Recipient koleksiyonunu öğe öğe Resolve etmek her alıcı için ayrı
    # Exchange çağrısı yapıyor ve koşuyu ~10 kat yavaşlatıyor. Transport
    # başlığı tam adresleri zaten taşır; yoksa GetTable display alanına düş.
    original_to = header_from_transport(raw_headers, "To")
    original_cc = header_from_transport(raw_headers, "Cc")
    original_bcc = header_from_transport(raw_headers, "Bcc")
    fallback_to = meta.get("_display_to", "").replace(";", ",")
    fallback_cc = meta.get("_display_cc", "").replace(";", ",")
    if original_to or fallback_to:
        msg["To"] = original_to or fallback_to
    if original_cc or fallback_cc:
        msg["Cc"] = original_cc or fallback_cc
    if original_bcc:
        msg["Bcc"] = original_bcc
    msg["Subject"] = meta.get("subject", "")

    sent_on = safe_attr(item, "SentOn", None)
    if sent_on:
        try:
            msg["Date"] = format_datetime(sent_on)
        except Exception:
            pass
    mid = (norm_text(safe_prop(item, PR_INTERNET_MESSAGE_ID))
           or meta.get("internetMessageId", ""))
    if mid:
        msg["Message-ID"] = mid
        meta["internetMessageId"] = mid
    for header in ("Reply-To", "In-Reply-To", "References"):
        value = header_from_transport(raw_headers, header)
        if value:
            msg[header] = value

    message_class = (norm_text(safe_attr(item, "MessageClass", ""))
                     or norm_text(meta.get("_message_class", "")))
    body_values, body_errors = {}, []
    for field in ("Body", "HTMLBody"):
        try:
            body_values[field] = norm_text(getattr(item, field))
        except Exception as exc:
            body_errors.append(field + ": " + type(exc).__name__)
    body, html_body = body_values.get("Body", ""), body_values.get("HTMLBody", "")
    if body_errors and not (body or html_body):
        raise RuntimeError("MAPI gövdesi okunamadı: " + ", ".join(body_errors))
    meta["_mapi_body_fallback"] = body_errors
    if not body and html_body:
        body = html_to_metin(html_body)
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    attachments = item.Attachments
    attachment_count = int(attachments.Count)
    if attachment_count < 0 or (meta.get("hasAttachments") and attachment_count == 0):
        raise RuntimeError("MAPI ek sayısı kaynak metadata ile uyuşmuyor")
    if attachment_count:
        msg.make_mixed()
        materialized = list(attachments)
        if len(materialized) != attachment_count:
            raise RuntimeError("MAPI ek koleksiyonu eksik okundu")
        add_attachments(msg, materialized, temp_dir, meta)
    # ``set_content`` mevcut Content-* başlıklarını temizler. Bu işaret gövde
    # kurulduktan sonra eklenmezse toplantı yanıtları mail CSV'sine karışır.
    mark_nonmail_content_class(msg, message_class)

    meta.update({
        "receivedDateTime": iso_value(safe_attr(item, "ReceivedTime", None))
                            or meta.get("receivedDateTime", ""),
        "sentDateTime": iso_value(safe_attr(item, "SentOn", None))
                        or meta.get("sentDateTime", ""),
        "createdDateTime": iso_value(safe_attr(item, "CreationTime", None))
                           or meta.get("createdDateTime", ""),
        "lastModifiedDateTime": iso_value(safe_attr(
            item, "LastModificationTime", None))
                                or meta.get("lastModifiedDateTime", ""),
        "isRead": not bool(safe_attr(item, "UnRead", False)),
        "categories": [x.strip() for x in norm_text(
            safe_attr(item, "Categories", "")).split(",") if x.strip()],
        "conversationId": norm_text(safe_attr(item, "ConversationID", "")),
        "_message_class": message_class,
    })
    eml_bytes = msg.as_bytes()
    # Bazı eski kurumsal mailler kaynakta iki '@' taşıyan bozuk Message-ID
    # içeriyor. email paketi EML'yi yazarken bu başlığı geçerli biçime
    # normalize eder. Writer'ın sıra/EML güvenlik kontrolü, kaynaktaki bozuk
    # ham değeri değil diske gerçekten yazılan kimliği karşılaştırmalıdır.
    serialized = email.message_from_bytes(
        eml_bytes, policy=email.policy.default)
    serialized_mid = norm_text(serialized.get("Message-ID", ""))
    if serialized_mid:
        meta["internetMessageId"] = serialized_mid
    meta["_mapi_transport_headers"] = raw_headers or "MAPI transport başlığı yok\n"
    contract.atomic_bytes(eml_path, eml_bytes)
    if local_item is not None:
        try:
            local_item.Close(1)  # olDiscard
        except Exception:
            pass
    if prefetch is not None:
        try:
            prefetch.unlink()
        except OSError:
            pass


def completed_sequences(run_dir):
    result = set()
    csv_path = run_dir / "mailler.csv"
    if csv_path.exists():
        with csv_path.open("r", encoding=CSV_KODLAMA, newline="") as handle:
            result.update(row.get("sira_no", "") for row in
                          csv.DictReader(handle, delimiter=CSV_AYIRICI))
    skipped = run_dir / "_atlanan.json"
    if skipped.exists():
        result.update(row.get("sira_no", "") for row in
                      json.loads(skipped.read_text(encoding="utf-8")))
    return result


def should_copy_final_header(entry):
    """Yalnız gerçek maillerin transport başlığını final alana taşı."""
    return is_mail_message_class(entry.get("message_class", ""))


def finalize_header(raw, target):
    """Doğrulanmış üretim kopyasından sonra geçici tekrarı kaldır."""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(raw, target)
    if not filecmp.cmp(raw, target, shallow=False):
        raise RuntimeError("MAPI başlık kopyası doğrulanamadı: " + str(target))
    raw.unlink()


def process_page(run_dir, prefix, folder_path, entries, start_seq, temp_dir):
    page_dir = run_dir / "_gecici"
    headers_dir = page_dir / "mapi-basliklar"
    page_dir.mkdir(parents=True, exist_ok=True)
    headers_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "ham").mkdir(parents=True, exist_ok=True)

    built = []
    assigned = []
    for meta in entries:
        seq = start_seq + len(built)
        sira = "{0}-{1:05d}".format(prefix, seq)
        eml_path = run_dir / "ham" / (sira + ".eml")
        raw_path = headers_dir / (sira + ".txt")
        reservation = {"sira_no": sira, "id": meta.get("id"),
                       "klasor_yolu": folder_path, "message_class": meta.get("_message_class", "")}
        PROCESS.pending = [r for r in PROCESS.pending if r["sira_no"] != sira]
        PROCESS.pending.append(reservation)
        atomic_json(run_dir / "_bekleyen.json", PROCESS.pending)
        error = None
        error_trace = ""
        for attempt in range(2):
            try:
                build_eml(PROCESS.namespace, PROCESS.store_id, meta,
                          eml_path, raw_path, temp_dir)
                error = None
                break
            except Exception as exc:
                error = "{0}: {1}".format(type(exc).__name__, exc)
                error_trace = traceback.format_exc()
                if attempt == 0:
                    time.sleep(2)
        if error:
            PROCESS.errors.append({"id": meta.get("id"), "klasor": folder_path,
                                   "hata": error,
                                   "iz": error_trace})
            atomic_json(run_dir / "_hatalar.json", PROCESS.errors)
            raise RuntimeError("MAPI öğesi okunamadı; aynı sıra bekliyor: " + sira)
        built.append(meta)
        assigned.append({"sira_no": sira, "id": meta.get("id"),
                         "klasor_yolu": folder_path,
                         "message_class": meta.get("_message_class", "")})

    if not built:
        return 0, 0
    page_path = page_dir / ("mapi-page-{0:05d}.json".format(start_seq))
    atomic_json(page_path, {"value": built})
    atomic_json(run_dir / "_bekleyen.json", PROCESS.pending)
    result = sayfayi_isle(str(page_path), str(run_dir), folder_path,
                          prefix, start_seq)

    done = completed_sequences(run_dir)
    PROCESS.pending = [x for x in PROCESS.pending if x["sira_no"] not in done]
    atomic_json(run_dir / "_bekleyen.json", PROCESS.pending)
    if result.get("hata"):
        raise RuntimeError("mail_yaz doğrulaması geçmedi: " +
                           json.dumps(result, ensure_ascii=False))
    return len(built), int(result.get("atlanan", 0))


class PROCESS:
    namespace = None
    store_id = ""
    pending = []
    errors = []
    prefetch_msg = False
    skip_embedded_payload = False


def write_reports(run_dir, month, start_time, added, control, source_label,
                  source_rows=None, previous_mail_count=0):
    numbers = control.get("sayilar", {})
    today = dt.datetime.now(dt.timezone(ISTANBUL_UTC_OFFSET))
    status = ("AY_ICI_KISMI" if month == today.strftime("%Y-%m")
              else "KAYNAK_KAPSAMI_TAMAMLANDI")
    source_dates = [
        row.get("sentDateTime" if row.get("_folder_path") == SENT_NAME
                else "receivedDateTime")
        for row in (source_rows or [])
        if is_mail_message_class(row.get("_message_class"))
    ]
    source_dates = [value for value in source_dates if value]
    lines = [
        "MAPI aylık dışa aktarımı",
        "Ay: " + month,
        "Durum: " + status,
        "Bu çalıştırmada eklenen mail: {0}".format(
            int(numbers.get("mail_satiri", 0)) - previous_mail_count),
        "Bu çalıştırmada işlenen öğe: {0}".format(added),
        "Toplam mail: {0}".format(numbers.get("mail_satiri", 0)),
        "Kapsam dışı takvim öğesi: {0}".format(numbers.get("atlanan", 0)),
        "İndirilen gerçek ek: {0}".format(numbers.get("inen_ek", 0)),
        "Toplam ek boyutu GB: {0:.3f}".format(
            float(numbers.get("inen_ek_mb", 0)) / 1024.0),
        "Atlanan gömülü görsel: {0}".format(numbers.get("gomulu_ek", 0)),
        "Süre dakika: {0:.1f}".format((time.time() - start_time) / 60.0),
        "Kaynak: " + source_label + " (salt okunur niyetle)",
    ]
    if source_dates:
        lines.extend(["Kaynak en erken mail: " + min(source_dates),
                      "Kaynak en geç mail: " + max(source_dates)])
    (run_dir / "ozet.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    control_lines = ["KONTROL: " + control.get("hukum", "BASARISIZ"),
                     json.dumps(control, ensure_ascii=False, indent=2)]
    (run_dir / "kontrol.txt").write_text("\n".join(control_lines) + "\n",
                                          encoding="utf-8")


def run_control(run_dir, start, end):
    script = Path(__file__).with_name("kontrol.py")
    cmd = [sys.executable, str(script), "--kosu", str(run_dir),
           "--beklenen", str(run_dir / "_beklenen.json"),
           "--baslangic", start.strftime("%Y-%m-%d"),
           "--bitis", (end.date() - dt.timedelta(days=1)).isoformat()]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True,
                               encoding="utf-8")
    result = json.loads(completed.stdout)
    contract.atomic_json(run_dir / "_kontrol_sonuc.json", result)
    return result


def _main():
    console_utf8()
    parser = argparse.ArgumentParser(
        description="Çevrimiçi Arşiv'i Outlook/MAPI ile salt okunur dışa aktar")
    parser.add_argument("--ay", required=True, help="YYYY-MM")
    parser.add_argument("--sadece-say", action="store_true")
    parser.add_argument("--tam-pst-envanter", action="store_true",
                        help="Kapsam filtresiz tam PST sınıf/tarih envanteri; "
                             "çıktı yazmadan sadakat kapısını uygula")
    parser.add_argument("--smoke-test", action="store_true",
                        help="Tek gerçek öğeyi geçici alanda uçtan uca doğrula")
    parser.add_argument("--msg-onbellek", action="store_true",
                        help="Öğeyi önce geçici MSG ile tek çağrıda önbelleğe al")
    parser.add_argument("--gomulu-metadata", action="store_true",
                        help="Küçük gömülü görsellerin yalnız metadata'sını al")
    parser.add_argument("--pst",
                        help="Kaynak olarak geçici çalışma PST kopyasını kullan")
    parser.add_argument("--bagli-pst-kullan", action="store_true",
                        help="--pst zaten Outlook'a bağlıysa doğrudan kullan; "
                             "iş bitince profilden ayırma (yalnız Ozan açıkça isterse)")
    parser.add_argument("--cikti-koku", default=str(OUT_ROOT))
    args = parser.parse_args()

    start, end = month_bounds(args.ay)
    try:
        run_dir = run_dir_for(start, end, args.cikti_koku)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    prefix = start.strftime("%Y%m")
    started = time.time()
    PROCESS.errors = []
    source_proof = None
    if args.pst:
        if args.bagli_pst_kullan:
            raise ValueError("Kaynak PST doğrudan bağlanamaz; çalışma kopyası zorunlu")
        copy, source_proof = contract.prepare_pst(args.pst, args.cikti_koku)
        args.pst = str(copy)
    attached_root = None
    namespace = None
    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        if args.pst:
            store, attached_here = pst_store(
                namespace, args.pst, use_attached=args.bagli_pst_kullan)
            if attached_here:
                attached_root = store.GetRootFolder()
            source_label = ("Outlook MAPI / bağlı yerel PST" if
                            args.bagli_pst_kullan else
                            "Outlook MAPI / yerel PST")
        else:
            store = archive_store(namespace)
            source_label = "Outlook MAPI / Çevrimiçi Arşiv"
        PROCESS.namespace = namespace
        PROCESS.store_id = norm_text(store.StoreID)
        PROCESS.prefetch_msg = args.msg_onbellek
        PROCESS.skip_embedded_payload = args.gomulu_metadata
        if args.tam_pst_envanter:
            if not args.pst:
                raise ValueError("--tam-pst-envanter yalnız --pst ile kullanılabilir")
            inventory = full_pst_inventory(store, start, end)
            print("ENVANTER: " + json.dumps(inventory, ensure_ascii=False), flush=True)
            print("TAM_PST_KAPISI: " + ("GECTI" if inventory["gecti"] else "BASARISIZ"),
                  flush=True)
            return 0 if inventory["gecti"] else 2
        if args.pst:
            inventory = full_pst_inventory(store, start, end)
            if not inventory["gecti"]:
                raise ValueError("Tam PST sınıf/tarih kapısı başarısız")
            if not (args.sadece_say or args.smoke_test):
                run_dir.mkdir(parents=True, exist_ok=True)
                atomic_json(run_dir / "_pst_kanit.json", dict(source_proof, inventory=inventory))
        folders = scope_folders(store)

        all_rows = []
        expected = {}
        source_ids = {}
        folder_manifest = []
        for folder, path, is_sent in folders:
            rows = table_metadata(folder, path, start, end, is_sent)
            expected[path] = len(rows)
            source_ids[path] = [row["id"] for row in rows]
            folder_manifest.append({"klasor_yolu": path,
                                    "entry_id": norm_text(folder.EntryID),
                                    "adet": len(rows), "sent": is_sent})
            all_rows.extend(rows)
            print("SAYIM {0}: {1}".format(path, len(rows)), flush=True)

        total = sum(expected.values())
        print("TOPLAM: {0}".format(total), flush=True)
        class_counts = {}
        for row in all_rows:
            message_class = row.get("_message_class") or "(bos)"
            class_counts[message_class] = class_counts.get(message_class, 0) + 1
        for message_class, count in sorted(class_counts.items()):
            print("SINIF {0}: {1}".format(message_class, count), flush=True)
        if args.sadece_say:
            return 0
        if args.smoke_test:
            candidates = [row for row in all_rows if row.get("hasAttachments")]
            sample = (candidates or all_rows)[0]
            with tempfile.TemporaryDirectory(prefix="mapi-mail-smoke-") as tmp:
                smoke = Path(tmp)
                for name in ("ham", "govdeler", "basliklar", "ekler",
                             "_gecici"):
                    (smoke / name).mkdir(exist_ok=True)
                sira = prefix + "-00001"
                raw_path = smoke / "_gecici" / (sira + ".headers.txt")
                build_started = time.time()
                build_eml(namespace, PROCESS.store_id, sample,
                          smoke / "ham" / (sira + ".eml"), raw_path,
                          smoke / "_gecici")
                build_seconds = time.time() - build_started
                page = smoke / "_gecici" / "page.json"
                atomic_json(page, {"value": [sample]})
                result = sayfayi_isle(str(page), str(smoke),
                                      sample["_folder_path"], prefix, 1)
                if result.get("hata") or not (result.get("islenen")
                                               or result.get("atlanan")):
                    raise RuntimeError("MAPI smoke test geçmedi: " +
                                       json.dumps(result, ensure_ascii=False))
                print("SMOKE_TEST: GECTI — ek={0}, gomulu={1}, "
                      "atlanan={2}, build_saniye={3:.2f}".format(
                          result.get("ek", 0),
                          result.get("gomulu_atlanan", 0),
                          result.get("atlanan", 0), build_seconds), flush=True)
            return 0

        run_dir.mkdir(parents=True, exist_ok=True)
        for name in ("ham", "govdeler", "basliklar", "ekler", "_gecici"):
            (run_dir / name).mkdir(exist_ok=True)
        atomic_json(run_dir / "_beklenen.json", expected)
        atomic_json(run_dir / "_kaynak_idler.json", source_ids)
        atomic_json(run_dir / "_klasorler.json", {
            "store": norm_text(store.DisplayName), "store_id": PROCESS.store_id,
            "kaynak": source_label, "ay": args.ay,
            "klasorler": folder_manifest})
        atomic_json(run_dir / "_mapi_metadata.json", all_rows)

        previous_mail_count = 0
        if (run_dir / "mailler.csv").is_file():
            with (run_dir / "mailler.csv").open(
                    encoding=CSV_KODLAMA, newline="") as handle:
                previous_mail_count = sum(1 for _ in csv.DictReader(
                    handle, delimiter=CSV_AYIRICI))
        existing_ids, _, max_seq = read_existing(run_dir)
        PROCESS.pending = contract.validate_pending(run_dir, "mapi", prefix)
        if PROCESS.pending:
            # Kesinti sayfa işlenirken olduysa sıra numaraları çoktan tahsis
            # edilmiştir. Önce bu kayıtları aynı numarayla tek tek tamamla;
            # yeni numara üretmek sessiz boşluk veya mükerrer yaratır.
            metadata_by_id = {row["id"]: row for row in all_rows}
            unique_pending = {}
            for record in PROCESS.pending:
                unique_pending[record.get("sira_no", "")] = record
            PROCESS.pending = list(unique_pending.values())
            resume_temp = run_dir / "_gecici" / "mapi-ek-gecici"
            resume_temp.mkdir(parents=True, exist_ok=True)
            for record in sorted(list(PROCESS.pending),
                                 key=lambda x: x.get("sira_no", "")):
                if contract.receipt_valid(run_dir, record["sira_no"], record["id"]):
                    PROCESS.pending = [x for x in PROCESS.pending if x["sira_no"] != record["sira_no"]]
                    atomic_json(run_dir / "_bekleyen.json", PROCESS.pending)
                    continue
                meta = metadata_by_id.get(record.get("id", ""))
                if meta is None:
                    raise RuntimeError(
                        "Bekleyen MAPI kaydı canlı metadata'da bulunamadı: "
                        + json.dumps(record, ensure_ascii=False))
                match = re.fullmatch(r"\d{6}-(\d{5})",
                                     record.get("sira_no", ""))
                if not match:
                    raise RuntimeError("Bekleyen sıra numarası geçersiz: " +
                                       json.dumps(record, ensure_ascii=False))
                PROCESS.pending = [x for x in PROCESS.pending
                                   if x.get("sira_no") != record.get("sira_no")]
                count, _ = process_page(
                    run_dir, prefix, record.get("klasor_yolu")
                    or meta["_folder_path"], [meta], int(match.group(1)),
                    resume_temp)
                if count != 1:
                    raise RuntimeError("Bekleyen MAPI kaydı tamamlanamadı: " +
                                       record.get("sira_no", ""))
            existing_ids, _, max_seq = read_existing(run_dir)

        todo_by_folder = []
        for _, path, _ in folders:
            rows = [row for row in all_rows if row["_folder_path"] == path]
            todo = missing_mapi_rows(rows, existing_ids)
            if todo:
                todo_by_folder.append((path, todo))

        todo_count = sum(len(rows) for _, rows in todo_by_folder)
        print("EKSİK/YENİ: {0}".format(todo_count), flush=True)
        added = 0
        next_seq = max_seq + 1
        temp_root = run_dir / "_gecici" / "mapi-ek-gecici"
        temp_root.mkdir(parents=True, exist_ok=True)
        for folder_path, rows in todo_by_folder:
            for offset in range(0, len(rows), PAGE_SIZE):
                page = rows[offset:offset + PAGE_SIZE]
                count, _ = process_page(run_dir, prefix, folder_path, page,
                                        next_seq, temp_root)
                next_seq += count
                added += count
                atomic_json(run_dir / "_durum.json", {
                    "kaynak": source_label, "ay": args.ay,
                    "klasor": folder_path, "eklenen": added,
                    "hedef": todo_count, "son_sira": next_seq - 1,
                    "guncellendi": dt.datetime.now().isoformat(timespec="seconds")})
                print("İLERLEME: {0}/{1} — {2}".format(
                    added, todo_count, folder_path), flush=True)

        if PROCESS.errors:
            atomic_json(run_dir / "_hatalar.json", PROCESS.errors)
            raise RuntimeError("{0} MAPI öğesi iki denemede açılamadı".format(
                len(PROCESS.errors)))
        if temp_root.exists():
            try:
                temp_root.rmdir()
            except OSError:
                pass
        control = run_control(run_dir, start, end)
        write_reports(run_dir, args.ay, started, added, control, source_label,
                      source_rows=all_rows, previous_mail_count=previous_mail_count)
        print("KONTROL: " + control.get("hukum", "BASARISIZ"), flush=True)
        print("SONUC: " + json.dumps({"eklenen": added,
                                      "sayilar": control.get("sayilar", {})},
                                     ensure_ascii=False), flush=True)
        return 0 if control.get("hukum") == "GECTI" else 2
    finally:
        if attached_root is not None and namespace is not None:
            try:
                namespace.RemoveStore(attached_root)
            except Exception as exc:
                print("UYARI: geçici PST store'u ayrılamadı: {0}".format(exc),
                      file=sys.stderr, flush=True)
        pythoncom.CoUninitialize()
        if source_proof and contract.digest(source_proof["source"]) != source_proof["sha256"]:
            raise RuntimeError("Kaynak PST çalışma sırasında değişti; teslim iptal")


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--ay")
    ap.add_argument("--cikti-koku", default=str(OUT_ROOT))
    args, rest = ap.parse_known_args()
    if not args.ay or any(x in rest for x in ("--sadece-say", "--tam-pst-envanter", "--smoke-test", "--help", "-h")):
        return _main()
    start, end = month_bounds(args.ay)
    root = run_dir_for(start, end, args.cikti_koku)
    with contract.ExportSession(root, "mapi", start.strftime("%Y%m")) as session:
        result = _main()
        session.finish(result)
        return result


if __name__ == "__main__":
    raise SystemExit(main())
