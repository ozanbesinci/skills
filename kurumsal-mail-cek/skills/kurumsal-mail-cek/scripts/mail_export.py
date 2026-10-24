#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kurumsal Outlook maillerini salt okunur Graph erişimiyle dışa aktarır.

Kapsam: Arşiv ve tüm alt klasörleri (08_Gmail hariç), Gelen Kutusu ana klasörü,
Gönderilmiş Öğeler.
Graph tarafında yalnız GET kullanır; OAuth scope yalnız Mail.Read'dir.
"""

from __future__ import annotations

import archive_contract as contract
import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import msal
from archive_layout import ARCHIVE_ROOT, run_directory


CLIENT_ID = "04194109-2634-4285-9211-ddd7b16f8aa0"
TENANT_ID = "7070373e-a32b-47b1-a1b8-026996138087"
AUTHORITY = "https://login.microsoftonline.com/" + TENANT_ID
SCOPES = ["Mail.Read"]
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
PAGE_SIZE = 50
PACE_SECONDS = 0.30
RETRY_SECONDS = (5, 15, 45, 120)
DEFAULT_OUTPUT_ROOT = str(ARCHIVE_ROOT)
ISTANBUL_TZ = dt.timezone(dt.timedelta(hours=3), name="Europe/Istanbul")
MONTH_NAMES = {
    1: "ocak", 2: "subat", 3: "mart", 4: "nisan",
    5: "mayis", 6: "haziran", 7: "temmuz", 8: "agustos",
    9: "eylul", 10: "ekim", 11: "kasim", 12: "aralik",
}

SELECT_FIELDS = (
    "id,conversationId,conversationIndex,receivedDateTime,sentDateTime,"
    "createdDateTime,lastModifiedDateTime,isRead,isDraft,importance,flag,"
    "categories,hasAttachments,inferenceClassification,webLink"
)

MAIL_COLUMNS = [
    "sira_no", "klasor_yolu", "oge_tipi", "konu",
    "gonderen_ad", "gonderen_mail", "sender_ad", "sender_mail",
    "kime", "cc", "bcc", "yanit_adresi",
    "alinma_zamani", "gonderilme_zamani", "olusturma", "son_degisiklik",
    "govde_onizleme", "govde_dosya", "govde_tipi",
    "ek_var_mi", "ek_sayisi", "ek_adlari", "ek_klasoru",
    "okundu_mu", "taslak_mi", "onem", "bayrak_durumu", "kategoriler",
    "yanit_zinciri_mi", "boyut_byte", "cikarim_sinifi",
    "mukerrer_mi", "sifreli_mi", "mesaj_id", "konusma_id",
    "konusma_index", "internet_mesaj_id", "web_link", "basliklar_dosya",
]


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def local_now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("tarih YYYY-MM-DD olmalı") from exc


def parse_month(value: str) -> dt.date:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise argparse.ArgumentTypeError("ay YYYY-MM olmalı")
    try:
        return dt.date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("geçersiz ay: " + value) from exc


def month_last_day(month_start: dt.date) -> dt.date:
    if month_start.month == 12:
        next_month = dt.date(month_start.year + 1, 1, 1)
    else:
        next_month = dt.date(month_start.year, month_start.month + 1, 1)
    return next_month - dt.timedelta(days=1)


def monthly_run_name(month_start: dt.date) -> str:
    """Aylık arşivin kararlı, ASCII klasör adını döndürür."""
    return "{0}-{1:04d}".format(MONTH_NAMES[month_start.month], month_start.year)


def resolve_period(args: argparse.Namespace,
                   today: dt.date | None = None) -> tuple[dt.date, dt.date, str, bool]:
    """Komut satırını gerçek kapsama ve kararlı koşu adına dönüştürür.

    Aylık modda klasör her zaman takvim ayının tam adını taşır. İçinde bulunulan
    ayın gerçek kapsamı ise bugünde biter; böylece aynı klasör sonraki çalıştırmada
    artımlı olarak genişletilebilir.
    """
    if args.ay is not None:
        if args.baslangic is not None or args.bitis is not None:
            raise SystemExit("--ay ile --baslangic/--bitis birlikte kullanılamaz")
        start = args.ay
        full_end = month_last_day(start)
        today = today or dt.datetime.now().astimezone().date()
        current_start = today.replace(day=1)
        if start > current_start:
            raise SystemExit("Gelecek ay çekilemez: " + start.strftime("%Y-%m"))
        end = today if start == current_start else full_end
        run_name = monthly_run_name(start)
        return start, end, run_name, True

    if args.baslangic is None or args.bitis is None:
        raise SystemExit("--ay veya birlikte --baslangic ve --bitis gerekli")
    start = args.baslangic
    end = args.bitis
    run_name = start.strftime("%d%m%y") + "-" + end.strftime("%d%m%y")
    return start, end, run_name, False


def atomic_json(path: Path, value: object) -> None:
    contract.atomic_json(path, value)


def read_json(path: Path, default: object = None) -> object:
    if not path.is_file():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalized_name(value: str) -> str:
    value = value.replace("İ", "I").replace("ı", "i")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.casefold().strip()


def graph_segment(value: str) -> str:
    return urllib.parse.quote(value, safe="")


class TokenProvider:
    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache = msal.SerializableTokenCache()
        if self.cache_path.is_file():
            try:
                self.cache.deserialize(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                print("UYARI: MSAL token cache okunamadı; yeniden giriş istenecek.",
                      flush=True)
        self.app = msal.PublicClientApplication(
            CLIENT_ID, authority=AUTHORITY, token_cache=self.cache)
        self._token = ""
        self._expires_at = 0.0

    def _save(self) -> None:
        if not self.cache.has_state_changed:
            return
        temp = self.cache_path.with_name(self.cache_path.name + ".tmp")
        temp.write_text(self.cache.serialize(), encoding="utf-8")
        os.replace(temp, self.cache_path)

    def _accept(self, result: dict) -> str:
        token = result.get("access_token")
        if not token:
            raise RuntimeError(
                "Microsoft oturumu açılamadı: "
                + str(result.get("error_description") or result.get("error") or result)
            )
        self._token = token
        self._expires_at = time.time() + int(result.get("expires_in") or 3300)
        self._save()
        return token

    def get(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._token and time.time() < self._expires_at - 300:
            return self._token
        accounts = self.app.get_accounts()
        result = None
        if accounts:
            result = self.app.acquire_token_silent(
                SCOPES, account=accounts[0], force_refresh=force_refresh)
        if result and result.get("access_token"):
            return self._accept(result)
        flow = self.app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError("Device-code akışı başlatılamadı: " + str(flow))
        print(flow.get("message") or (
            "Microsoft girişi: {0} adresinde {1} kodunu kullanın."
            .format(flow.get("verification_uri"), flow.get("user_code"))), flush=True)
        result = self.app.acquire_token_by_device_flow(flow)
        return self._accept(result)


class GraphClient:
    def __init__(self, tokens: TokenProvider, pace: float = PACE_SECONDS) -> None:
        self.tokens = tokens
        self.pace = pace
        self.last_request = 0.0

    def _pace(self) -> None:
        wait = self.pace - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _url(path_or_url: str, params: dict | None = None) -> str:
        url = path_or_url if path_or_url.startswith("http") else GRAPH_ROOT + path_or_url
        if params:
            query = urllib.parse.urlencode(params, safe=",$'()/:\\")
            url += ("&" if "?" in url else "?") + query
        return url

    def _open(self, url: str, force_token: bool = False):
        token = self.tokens.get(force_refresh=force_token)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "User-Agent": "KilicMailExporter/1.0",
            },
            method="GET",
        )
        self._pace()
        response = urllib.request.urlopen(request, timeout=120)
        self.last_request = time.monotonic()
        return response

    def _request(self, url: str, sink: Path | None = None) -> bytes | None:
        waits = iter(RETRY_SECONDS)
        refreshed = False
        attempts = 0
        while True:
            attempts += 1
            try:
                with self._open(url, force_token=refreshed) as response:
                    if sink is None:
                        return response.read()
                    temp = sink.with_name(sink.name + ".part")
                    try:
                        with temp.open("wb") as handle:
                            while True:
                                block = response.read(1024 * 1024)
                                if not block:
                                    break
                                handle.write(block)
                            handle.flush()
                            os.fsync(handle.fileno())
                        if temp.stat().st_size == 0:
                            raise IOError("Graph 0 byte içerik döndürdü")
                        os.replace(temp, sink)
                    except Exception:
                        try:
                            temp.unlink()
                        except OSError:
                            pass
                        raise
                    return None
            except urllib.error.HTTPError as exc:
                self.last_request = time.monotonic()
                if exc.code == 401 and not refreshed:
                    refreshed = True
                    continue
                if exc.code == 429 or 500 <= exc.code <= 599:
                    try:
                        delay = next(waits)
                    except StopIteration:
                        detail = exc.read(600).decode("utf-8", "replace")
                        raise RuntimeError(
                            "Graph geçici hatası düzelmedi: HTTP {0} {1}"
                            .format(exc.code, detail)) from exc
                    retry_after = exc.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        delay = max(delay, int(retry_after))
                    print("Graph HTTP {0}; {1} saniye bekleniyor (deneme {2})."
                          .format(exc.code, delay, attempts), flush=True)
                    time.sleep(delay)
                    continue
                detail = exc.read(600).decode("utf-8", "replace")
                raise RuntimeError(
                    "Graph isteği başarısız: HTTP {0} {1}".format(exc.code, detail)
                ) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self.last_request = time.monotonic()
                try:
                    delay = next(waits)
                except StopIteration:
                    raise RuntimeError(
                        "Graph bağlantısı tekrarlara rağmen kurulamadı: "
                        + type(exc).__name__) from exc
                print("Graph bağlantı hatası; {0} saniye bekleniyor (deneme {1})."
                      .format(delay, attempts), flush=True)
                time.sleep(delay)

    def json(self, path_or_url: str, params: dict | None = None) -> dict:
        url = self._url(path_or_url, params)
        raw = self._request(url)
        try:
            value = json.loads((raw or b"").decode("utf-8"))
        except Exception as exc:
            raise RuntimeError("Graph geçersiz JSON döndürdü") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Graph JSON nesnesi bekleniyordu")
        return value

    def download(self, path_or_url: str, sink: Path) -> None:
        url = self._url(path_or_url)
        self._request(url, sink=sink)


def paged_values(graph: GraphClient, path: str,
                 params: dict | None = None) -> list[dict]:
    values: list[dict] = []
    page = graph.json(path, params=params)
    while True:
        batch = page.get("value") or []
        if not isinstance(batch, list):
            raise RuntimeError("Graph value alanı liste değil")
        values.extend(item for item in batch if isinstance(item, dict))
        next_link = page.get("@odata.nextLink")
        if not next_link:
            break
        page = graph.json(next_link)
    return values


def discover_folders(graph: GraphClient) -> list[dict]:
    archive = graph.json("/me/mailFolders/archive")
    inbox = graph.json("/me/mailFolders/inbox")
    sent = graph.json("/me/mailFolders/sentitems")
    folders: list[dict] = []

    def add_tree(folder: dict, path: str) -> None:
        folders.append({
            "id": folder["id"],
            "path": path,
            "date_field": "receivedDateTime",
        })
        children = paged_values(
            graph,
            "/me/mailFolders/{0}/childFolders".format(graph_segment(folder["id"])),
            {"$top": "100", "includeHiddenFolders": "true"},
        )
        children.sort(key=lambda item: normalized_name(str(item.get("displayName") or "")))
        for child in children:
            name = str(child.get("displayName") or "").strip()
            if normalized_name(name) == "08_gmail":
                continue
            add_tree(child, path + "\\" + name)

    archive_name = str(archive.get("displayName") or "Arşiv").strip()
    add_tree(archive, archive_name)
    inbox_name = str(inbox.get("displayName") or "Gelen Kutusu").strip()
    folders.append({
        "id": inbox["id"],
        "path": inbox_name,
        "date_field": "receivedDateTime",
    })
    sent_name = str(sent.get("displayName") or "Gönderilmiş Öğeler").strip()
    folders.append({
        "id": sent["id"],
        "path": sent_name,
        "date_field": "sentDateTime",
    })
    return folders


def message_query(folder: dict, start: dt.date, end_exclusive: dt.date,
                  skip: int, end_utc: str | None = None) -> tuple[str, dict]:
    field = folder["date_field"]
    start_iso = dt.datetime.combine(
        start, dt.time.min, tzinfo=ISTANBUL_TZ
    ).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_utc or dt.datetime.combine(
        end_exclusive, dt.time.min, tzinfo=ISTANBUL_TZ
    ).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        "/me/mailFolders/{0}/messages".format(graph_segment(folder["id"])),
        {
            "$filter": "{0} ge {1} and {0} lt {2}".format(
                field, start_iso, end_iso),
            "$orderby": field + " asc",
            "$top": str(PAGE_SIZE),
            "$skip": str(skip),
            "$select": SELECT_FIELDS,
        },
    )


def processed_ids(run_dir: Path) -> set[str]:
    result: set[str] = set()
    csv_path = run_dir / "mailler.csv"
    if csv_path.is_file():
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle, delimiter=";"):
                value = (row.get("mesaj_id") or "").strip()
                sequence = (row.get("sira_no") or "").strip()
                raw_left = bool(sequence and (run_dir / "ham" / (sequence + ".eml")).is_file())
                if value and not raw_left:
                    result.add(value)
    skipped = read_json(run_dir / "_atlanan.json", [])
    if isinstance(skipped, list):
        for row in skipped:
            if isinstance(row, dict) and row.get("mesaj_id"):
                result.add(str(row["mesaj_id"]))
    return result


def next_sequence_number(run_dir: Path, month_prefix: str,
                         pending: dict | None = None) -> int:
    used: list[int] = []

    def add(value: object) -> None:
        match = re.fullmatch(r"(\d{6})-(\d{5})(?:\.eml)?", str(value or ""))
        if not match:
            return
        if match.group(1) != month_prefix:
            raise RuntimeError(
                "Koşu klasöründe başka aya ait sıra numarası var: " + str(value))
        used.append(int(match.group(2)))

    csv_path = run_dir / "mailler.csv"
    if csv_path.is_file():
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle, delimiter=";"):
                add(row.get("sira_no"))
    skipped = read_json(run_dir / "_atlanan.json", [])
    if isinstance(skipped, list):
        for row in skipped:
            if isinstance(row, dict):
                add(row.get("sira_no"))
    if isinstance(pending, dict):
        for row in pending.values():
            if isinstance(row, dict):
                add("{0}-{1:05d}".format(month_prefix, int(row.get("sira") or 0)))
    ham = run_dir / "ham"
    if ham.is_dir():
        for path in ham.glob("*.eml"):
            add(path.name)
    return max(used, default=0) + 1


def load_pending(run_dir: Path) -> dict[str, dict]:
    value = read_json(run_dir / "_bekleyen.json", {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError("_bekleyen.json nesne değil")
    result: dict[str, dict] = {}
    for message_id, row in value.items():
        if not message_id or not isinstance(row, dict):
            raise RuntimeError("_bekleyen.json içinde geçersiz kayıt")
        if not isinstance(row.get("kayit"), dict) or int(row.get("sira") or 0) < 1:
            raise RuntimeError("_bekleyen.json içinde eksik sıra/kayıt")
        result[str(message_id)] = row
    return result


def save_pending(run_dir: Path, pending: dict[str, dict]) -> None:
    atomic_json(run_dir / "_bekleyen.json", pending)


def validate_downloads(run_dir: Path, expected: list[Path]) -> None:
    ham = run_dir / "ham"
    invalid = [p.name for p in ham.glob("*.eml")
               if not re.fullmatch(r"\d{6}-\d{5}\.eml", p.name)]
    if invalid:
        raise RuntimeError(
            "ham/ içinde hatalı ad var; parse edilmedi: " + ", ".join(invalid[:20]))
    missing = [p.name for p in expected if not p.is_file()]
    empty = [p.name for p in expected if p.is_file() and p.stat().st_size == 0]
    if missing or empty:
        raise RuntimeError(
            "Sayfa indirme doğrulaması geçmedi. Eksik={0}, 0-byte={1}"
            .format(missing[:20], empty[:20]))


def run_mail_writer(script_dir: Path, page_path: Path, run_dir: Path,
                    folder_path: str, month_prefix: str,
                    starting_sequence: int) -> dict:
    command = [
        sys.executable, str(script_dir / "mail_yaz.py"),
        "--sayfa", str(page_path),
        "--kosu", str(run_dir),
        "--klasor-yolu", folder_path,
        "--ay-onek", month_prefix,
        "--baslangic-sira", str(starting_sequence),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(
            "mail_yaz.py başarısız: " + (result.stderr or result.stdout)[-1500:])
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("mail_yaz.py sonuç döndürmedi")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("mail_yaz.py geçersiz sonuç döndürdü") from exc


def process_page(graph: GraphClient, script_dir: Path, run_dir: Path,
                 page_path: Path, records: list[dict], folder_path: str,
                 month_prefix: str, starting_sequence: int,
                 notes: list[str]) -> None:
    done = processed_ids(run_dir)
    missing: list[tuple[int, dict, Path]] = []
    for offset, record in enumerate(records):
        message_id = str(record.get("id") or "")
        if not message_id:
            notes.append("{0} sıra {1}: Graph mesaj id boş".format(
                folder_path, starting_sequence + offset))
            continue
        if message_id in done:
            continue
        eml = run_dir / "ham" / (
            "{0}-{1:05d}.eml".format(month_prefix, starting_sequence + offset))
        missing.append((offset, record, eml))

    if not missing:
        return

    for _, record, eml in missing:
        if eml.is_file() and eml.stat().st_size > 0:
            continue
        graph.download(
            "/me/messages/{0}/$value".format(graph_segment(str(record["id"]))), eml)
    validate_downloads(run_dir, [item[2] for item in missing])

    if len(missing) == len(records):
        outcome = run_mail_writer(
            script_dir, page_path, run_dir, folder_path,
            month_prefix, starting_sequence)
        if outcome.get("hata"):
            notes.extend(str(item) for item in (outcome.get("notlar") or []))
        return

    # Kesinti sayfa yazımından sonra olmuşsa yalnız eksik kayıtları işler;
    # mevcut CSV satırlarını ikinci kez yazmaz.
    for offset, record, _ in missing:
        one_path = page_path.with_name(
            "_tek-{0:05d}.json".format(starting_sequence + offset))
        atomic_json(one_path, {"value": [record]})
        try:
            outcome = run_mail_writer(
                script_dir, one_path, run_dir, folder_path,
                month_prefix, starting_sequence + offset)
            if outcome.get("hata"):
                notes.extend(str(item) for item in (outcome.get("notlar") or []))
        finally:
            try:
                one_path.unlink()
            except OSError:
                pass


def process_assigned_records(graph: GraphClient, script_dir: Path,
                             run_dir: Path, page_path: Path,
                             assignments: list[dict], folder_path: str,
                             month_prefix: str, notes: list[str]) -> None:
    if not assignments:
        return
    sequences = [int(item["sira"]) for item in assignments]
    expected_sequences = list(range(sequences[0], sequences[0] + len(sequences)))
    if sequences != expected_sequences:
        raise RuntimeError("Artımlı kayıt sıraları kesintisiz değil")

    records = [item["kayit"] for item in assignments]
    atomic_json(page_path, {"value": records})
    eml_paths: list[Path] = []
    for item in assignments:
        record = item["kayit"]
        message_id = str(record.get("id") or "")
        if not message_id:
            raise RuntimeError("Artımlı kayıtta Graph mesaj id boş")
        eml = run_dir / "ham" / (
            "{0}-{1:05d}.eml".format(month_prefix, int(item["sira"])))
        eml_paths.append(eml)
        if eml.is_file() and eml.stat().st_size > 0:
            continue
        graph.download(
            "/me/messages/{0}/$value".format(graph_segment(message_id)), eml)

    validate_downloads(run_dir, eml_paths)
    outcome = run_mail_writer(
        script_dir, page_path, run_dir, folder_path,
        month_prefix, sequences[0])
    if outcome.get("hata"):
        notes.extend(str(item) for item in (outcome.get("notlar") or []))


def retry_pending(graph: GraphClient, script_dir: Path, run_dir: Path,
                  pending: dict[str, dict], month_prefix: str,
                  notes: list[str]) -> None:
    if not pending:
        return
    # Bir kayit CSV'ye/atlananlara yazildiktan sonra, pending manifestinden
    # dusurulmeden surec kesilmis olabilir. Bu dar kesinti penceresinde ayni
    # maili yeniden indirmek ikinci CSV satiri uretir. Once yerelde gercekten
    # tamamlanmis olanlari journal'dan temizle, yalniz eksikleri yeniden isle.
    already_done = processed_ids(run_dir)
    completed_pending = [
        message_id for message_id in pending if message_id in already_done
    ]
    if completed_pending:
        for message_id in completed_pending:
            pending.pop(message_id, None)
        save_pending(run_dir, pending)
    if not pending:
        return
    print("DEVAM: {0} bekleyen kayıt yeniden işleniyor.".format(len(pending)),
          flush=True)
    ordered = sorted(pending.items(), key=lambda item: int(item[1]["sira"]))
    groups: list[list[tuple[str, dict]]] = []
    for message_id, row in ordered:
        if not groups:
            groups.append([(message_id, row)])
            continue
        previous = groups[-1][-1][1]
        same_folder = previous.get("klasor_yolu") == row.get("klasor_yolu")
        consecutive = int(previous["sira"]) + 1 == int(row["sira"])
        if same_folder and consecutive:
            groups[-1].append((message_id, row))
        else:
            groups.append([(message_id, row)])

    pending_dir = run_dir / "_gecici" / "_bekleyen"
    pending_dir.mkdir(parents=True, exist_ok=True)
    for group in groups:
        first = int(group[0][1]["sira"])
        last = int(group[-1][1]["sira"])
        page_path = pending_dir / "bekleyen-{0:05d}-{1:05d}.json".format(
            first, last)
        assignments = [
            {"sira": int(row["sira"]), "kayit": row["kayit"]}
            for _, row in group
        ]
        process_assigned_records(
            graph, script_dir, run_dir, page_path, assignments,
            str(group[0][1]["klasor_yolu"]), month_prefix, notes)
        done = processed_ids(run_dir)
        for message_id, _ in group:
            if message_id in done:
                pending.pop(message_id, None)
        save_pending(run_dir, pending)


def process_incremental_page(graph: GraphClient, script_dir: Path,
                             run_dir: Path, page_path: Path,
                             records: list[dict], folder_path: str,
                             month_prefix: str, next_sequence: int,
                             pending: dict[str, dict], notes: list[str]) -> int:
    done = processed_ids(run_dir)
    new_records: list[dict] = []
    for record in records:
        message_id = str(record.get("id") or "")
        if not message_id:
            notes.append(folder_path + ": Graph mesaj id boş")
            continue
        if message_id in done or message_id in pending:
            continue
        new_records.append(record)

    if not new_records:
        return 0

    assignments: list[dict] = []
    for offset, record in enumerate(new_records):
        sequence = next_sequence + offset
        message_id = str(record["id"])
        pending[message_id] = {
            "sira": sequence,
            "klasor_yolu": folder_path,
            "kayit": record,
        }
        assignments.append({"sira": sequence, "kayit": record})
    save_pending(run_dir, pending)

    filtered_path = page_path.with_name(
        "yeni-{0:05d}-{1:05d}.json".format(
            next_sequence, next_sequence + len(assignments) - 1))
    process_assigned_records(
        graph, script_dir, run_dir, filtered_path, assignments,
        folder_path, month_prefix, notes)
    done = processed_ids(run_dir)
    for record in new_records:
        message_id = str(record["id"])
        if message_id in done:
            pending.pop(message_id, None)
    save_pending(run_dir, pending)
    return len(assignments)


def run_control(script_dir: Path, run_dir: Path, start: dt.date,
                end: dt.date) -> dict:
    command = [
        sys.executable, str(script_dir / "kontrol.py"),
        "--kosu", str(run_dir),
        "--beklenen", str(run_dir / "_beklenen.json"),
        "--baslangic", start.isoformat(),
        "--bitis", end.isoformat(),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(
            "kontrol.py çalışmadı: " + (result.stderr or result.stdout)[-1500:])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("kontrol.py geçersiz sonuç döndürdü") from exc


def write_reports(run_dir: Path, start: dt.date, end: dt.date,
                  started_at: str, elapsed: float, control: dict,
                  notes: list[str], coverage_status: str = "OZEL_ARALIK",
                  added_messages: int = 0) -> None:
    verdict = str(control.get("hukum") or "BASARISIZ")
    counts = control.get("sayilar") or {}
    findings = control.get("bulgular") or []
    warnings = control.get("uyarilar") or []
    control_lines = ["KONTROL: " + verdict]
    control_lines.extend("- " + str(item) for item in findings)
    if not findings:
        control_lines.append("- Eksik veya tutarsız kayıt bulunmadı.")
    if warnings:
        control_lines.extend(["", "UYARILAR:"])
        control_lines.extend("- " + str(item) for item in warnings)
    control_lines.append("")
    control_lines.append(json.dumps(control, ensure_ascii=False, indent=2))
    (run_dir / "kontrol.txt").write_text(
        "\n".join(control_lines) + "\n", encoding="utf-8")

    ek_mb = float(counts.get("inen_ek_mb") or 0)
    lines = [
        "KURUMSAL MAIL DISA AKTARIM OZETI",
        "Durum: " + verdict,
        "Tarih araligi: {0} - {1}".format(start.isoformat(), end.isoformat()),
        "Kapsam durumu: " + coverage_status,
        "Bu calistirmada eklenen mail/oge: " + str(added_messages),
        "Baslangic: " + started_at,
        "Bitis: " + local_now(),
        "Sure: {:.1f} dakika".format(elapsed / 60.0),
        "Mail: " + str(counts.get("mail_satiri", 0)),
        "Kapsam disi takvim ogesi: " + str(counts.get("atlanan", 0)),
        "Indirilen ek: " + str(counts.get("inen_ek", 0)),
        "Indirilen ek hacmi: {:.3f} GB ({:.1f} MB)".format(
            ek_mb / 1024.0, ek_mb),
        "Atlanan gomulu gorsel: " + str(counts.get("gomulu_ek", 0)),
        "Atlanan gomulu gorsel hacmi: {0} MB".format(
            counts.get("gomulu_atlanan_mb", 0)),
        "Mukerrer: " + str(counts.get("mukerrer", 0)),
        "Sifreli/govdesiz .eml: " + str(counts.get("sifreli", 0)),
        "Ham .eml kalan: " + str(counts.get("ham_kalan", 0)),
        "",
        "En buyuk 5 ek:",
    ]
    largest = counts.get("en_buyuk_ekler") or []
    lines.extend("- " + str(item) for item in largest)
    if not largest:
        lines.append("- Yok")
    if notes:
        lines.extend(["", "Kosu notlari:"])
        lines.extend("- " + str(item) for item in notes[:100])
    if findings:
        lines.extend(["", "Kontrol bulgulari:"])
        lines.extend("- " + str(item) for item in findings)
    if warnings:
        lines.extend(["", "Kaynak/veri uyarilari:"])
        lines.extend("- " + str(item) for item in warnings)
    (run_dir / "ozet.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def count_only(graph: GraphClient, folders: list[dict], start: dt.date,
               end_exclusive: dt.date, end_utc: str | None = None) -> dict[str, int]:
    result: dict[str, int] = {}
    for folder in folders:
        total = 0
        page_no = 1
        while True:
            path, params = message_query(
                folder, start, end_exclusive, (page_no - 1) * PAGE_SIZE,
                end_utc=end_utc)
            page = graph.json(path, params)
            records = page.get("value") or []
            total += len(records)
            if len(records) < PAGE_SIZE:
                break
            page_no += 1
        result[folder["path"]] = total
        print("SAYIM {0}: {1}".format(folder["path"], total), flush=True)
    return result


def collect_source_records(graph: GraphClient, folders: list[dict],
                           start: dt.date, end_exclusive: dt.date,
                           end_utc: str | None = None) -> dict[str, list[dict]]:
    """Aylık kontrol için nextLink zincirini izleyerek taze kaynak anlık görüntüsü al."""
    result: dict[str, list[dict]] = {}
    for folder in folders:
        path, params = message_query(
            folder, start, end_exclusive, 0, end_utc=end_utc)
        page = graph.json(path, params)
        records: list[dict] = []
        while True:
            batch = page.get("value") or []
            if not isinstance(batch, list):
                raise RuntimeError(
                    "Kaynak kontrolünde value liste değil: " + str(folder["path"]))
            for record in batch:
                if not isinstance(record, dict) or not str(record.get("id") or ""):
                    raise RuntimeError(
                        str(folder["path"]) + ": kaynak kontrolünde mesaj id boş")
                records.append(record)
            next_link = page.get("@odata.nextLink")
            if not next_link:
                break
            page = graph.json(str(next_link))
        result[str(folder["path"])] = records
    return result


def execute(args: argparse.Namespace) -> int:
    start, end, name, monthly = resolve_period(args)
    try:
        root = run_directory(Path(args.hedef_kok), start.year, name)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    contract.source_guard(root, "graph", start.strftime("%Y%m"))
    if args.sadece_say:
        return _execute(args)
    with contract.ExportSession(root, "graph", start.strftime("%Y%m")) as session:
        result = _execute(args)
        session.finish(result)
        return result


def _execute(args: argparse.Namespace) -> int:
    start, end, run_name, monthly_mode = resolve_period(args)
    if end < start:
        raise SystemExit("--bitis, --baslangic tarihinden önce olamaz")
    end_exclusive = end + dt.timedelta(days=1)
    month_prefix = start.strftime("%Y%m")
    full_month_end = month_last_day(start) if monthly_mode else end
    query_end_utc = None
    if monthly_mode and end < full_month_end:
        query_end_utc = dt.datetime.now(dt.timezone.utc).replace(
            microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    output_root = Path(args.hedef_kok)
    try:
        run_dir = run_directory(output_root, start.year, run_name)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    script_dir = Path(__file__).resolve().parent
    for helper in ("mail_yaz.py", "kontrol.py"):
        if not (script_dir / helper).is_file():
            raise SystemExit("Zorunlu yardımcı script yok: " + helper)

    if monthly_mode and output_root.is_dir():
        legacy_prefix = start.strftime("%d%m%y") + "-"
        legacy_runs = [
            path for path in output_root.iterdir()
            if path.is_dir() and path.name.startswith(legacy_prefix)
        ]
        year_dir = output_root / str(start.year)
        if year_dir.is_dir():
            legacy_runs.extend(
                path for path in year_dir.iterdir()
                if path.is_dir() and path.name.startswith(legacy_prefix))
        if legacy_runs:
            raise SystemExit(
                "Bu ay için eski tarih kodlu/parsiyel koşu klasörü bulundu; "
                "yeni aylık arşiv açılmadı: "
                + ", ".join(str(path) for path in legacy_runs))

    cache_root = Path(os.environ.get("LOCALAPPDATA") or output_root)
    tokens = TokenProvider(cache_root / "KilicMailExporter" / "msal_cache.json")
    # Yetki gerekiyorsa hedef klasör açılmadan önce kullanıcıya giriş gösterilir.
    tokens.get()
    graph = GraphClient(tokens)

    manifest_path = run_dir / "_klasorler.json"
    existed_before = run_dir.exists()
    if run_dir.exists():
        if not monthly_mode and not args.devam:
            raise SystemExit(
                "Koşu klasörü zaten var; üzerine yazılmadı. Devam için --devam kullanın: "
                + str(run_dir))
        if monthly_mode:
            # Aylık artımlı tarama her seferinde canlı klasör ağacını yeniler.
            folders = discover_folders(graph)
            if not args.sadece_say:
                atomic_json(manifest_path, folders)
        else:
            manifest = read_json(manifest_path)
            if not isinstance(manifest, list):
                raise SystemExit(
                    "Mevcut koşuda _klasorler.json yok/bozuk; devam edilmedi")
            folders = manifest
    else:
        folders = discover_folders(graph)
        if args.sadece_say:
            counts = count_only(
                graph, folders, start, end_exclusive, end_utc=query_end_utc)
            print(json.dumps(counts, ensure_ascii=False, indent=2))
            return 0
        run_dir.mkdir(parents=True, exist_ok=False)
        for name in ("ham", "govdeler", "basliklar", "ekler",
                     "sorunlu_eml", "_gecici"):
            (run_dir / name).mkdir()
        atomic_json(manifest_path, folders)

    if args.sadece_say:
        counts = count_only(
            graph, folders, start, end_exclusive, end_utc=query_end_utc)
        print(json.dumps(counts, ensure_ascii=False, indent=2))
        return 0

    started_at = local_now()
    start_clock = time.monotonic()
    state_path = run_dir / "_durum.json"
    notes: list[str] = []
    before_ids = processed_ids(run_dir)
    state = read_json(state_path, {})
    if not isinstance(state, dict):
        state = {}
    previous_start = str(state.get("baslangic") or "")
    if monthly_mode and previous_start and previous_start != start.isoformat():
        raise SystemExit(
            "Mevcut aylık klasörün başlangıcı uyuşmuyor: " + previous_start)
    coverage_status = (
        "AY_TAMAM" if monthly_mode and end == full_month_end
        else "AY_ICI_KISMI" if monthly_mode
        else "OZEL_ARALIK"
    )
    state.update({
        "surum": 2,
        "baslangic": start.isoformat(),
        "bitis": end.isoformat(),
        "durum": "CALISIYOR",
        "guncelleme": utc_now(),
        "aylik_mod": monthly_mode,
        "ay_sonu": full_month_end.isoformat() if monthly_mode else "",
        "kapsam_durumu": coverage_status,
        "kapsam_kesim_utc": query_end_utc or "",
        "tamamlayici_tarama": bool(args.tamamlayici_tarama),
    })
    if monthly_mode and existed_before:
        notes.append(
            "Mevcut aylık arşiv yeniden sayıldı; yalnız kayıtlı olmayan mesajlar eklendi.")
    atomic_json(state_path, state)

    expected: dict[str, int] = {}
    source_ids: dict[str, list[str]] = {}
    pending = load_pending(run_dir) if monthly_mode else {}
    if monthly_mode:
        retry_pending(
            graph, script_dir, run_dir, pending, month_prefix, notes)
        sequence = next_sequence_number(run_dir, month_prefix, pending)
    else:
        sequence = 1
    for folder_index, folder in enumerate(folders, start=1):
        folder_path = str(folder["path"])
        folder_temp = run_dir / "_gecici" / "{0:03d}".format(folder_index)
        folder_temp.mkdir(parents=True, exist_ok=True)
        page_no = 1
        next_link = None
        folder_count = 0
        folder_source_ids: list[str] = []
        while True:
            page_path = folder_temp / "sayfa-{0:04d}.json".format(page_no)
            if monthly_mode and next_link:
                page = graph.json(str(next_link))
                atomic_json(page_path, page)
            elif page_path.is_file() and not monthly_mode:
                page = read_json(page_path)
                if not isinstance(page, dict):
                    raise RuntimeError("Sayfa JSON bozuk: " + str(page_path))
            else:
                path, params = message_query(
                    folder, start, end_exclusive, (page_no - 1) * PAGE_SIZE,
                    end_utc=query_end_utc)
                page = graph.json(path, params)
                atomic_json(page_path, page)
            records = page.get("value") or []
            if not isinstance(records, list):
                raise RuntimeError("Sayfa value alanı liste değil: " + str(page_path))
            if not records:
                break
            for record in records:
                message_id = str(record.get("id") or "")
                if not message_id:
                    raise RuntimeError(folder_path + ": Graph mesaj id boş")
                folder_source_ids.append(message_id)
            if monthly_mode:
                added = process_incremental_page(
                    graph, script_dir, run_dir, page_path, records, folder_path,
                    month_prefix, sequence, pending, notes)
                sequence += added
            else:
                process_page(
                    graph, script_dir, run_dir, page_path, records, folder_path,
                    month_prefix, sequence, notes)
                sequence += len(records)
            folder_count += len(records)
            state.update({
                "klasor": folder_path,
                "klasor_index": folder_index,
                "sayfa": page_no,
                "son_sira": sequence - 1,
                "guncelleme": utc_now(),
            })
            atomic_json(state_path, state)
            print("{0} | sayfa {1} | toplam sıra {2}"
                  .format(folder_path, page_no, sequence - 1), flush=True)
            if monthly_mode:
                next_link = page.get("@odata.nextLink")
                if not next_link:
                    break
            elif len(records) < PAGE_SIZE:
                break
            page_no += 1
        expected[folder_path] = folder_count
        if monthly_mode:
            source_ids[folder_path] = folder_source_ids
            atomic_json(run_dir / "_kaynak_idler.json", source_ids)
        atomic_json(run_dir / "_beklenen.json", expected)

    # İlk turda tekil hata kaldıysa bir kez daha aynı sayfaları yürüt.
    remaining_before = sequence - 1 - len(processed_ids(run_dir))
    if monthly_mode and pending:
        retry_pending(
            graph, script_dir, run_dir, pending, month_prefix, notes)
    elif not monthly_mode and remaining_before > 0:
        print("ONARIM: {0} işlenmemiş kayıt için ikinci tur.".format(
            remaining_before), flush=True)
        sequence = 1
        for folder_index, folder in enumerate(folders, start=1):
            folder_temp = run_dir / "_gecici" / "{0:03d}".format(folder_index)
            page_no = 1
            while True:
                page_path = folder_temp / "sayfa-{0:04d}.json".format(page_no)
                if not page_path.is_file():
                    break
                page = read_json(page_path, {})
                records = page.get("value") or [] if isinstance(page, dict) else []
                if not records:
                    break
                process_page(
                    graph, script_dir, run_dir, page_path, records,
                    str(folder["path"]), month_prefix, sequence, notes)
                sequence += len(records)
                if len(records) < PAGE_SIZE:
                    break
                page_no += 1

    if monthly_mode:
        # Canlı posta kutusu ilk sayfalama sırasında değişebilir. Taze bir nextLink
        # zinciriyle ikinci anlık görüntüyü al; ilk turda kaçmış kayıt varsa ekle.
        reconciliation = collect_source_records(
            graph, folders, start, end_exclusive, end_utc=query_end_utc)
        reconciled_added = 0
        check_dir = run_dir / "_gecici" / "_son_kaynak_kontrolu"
        check_dir.mkdir(parents=True, exist_ok=True)
        for folder_index, folder in enumerate(folders, start=1):
            folder_path = str(folder["path"])
            records = reconciliation.get(folder_path, [])
            page_path = check_dir / "{0:03d}.json".format(folder_index)
            added = process_incremental_page(
                graph, script_dir, run_dir, page_path, records, folder_path,
                month_prefix, sequence, pending, notes)
            sequence += added
            reconciled_added += added
            expected[folder_path] = len(records)
            source_ids[folder_path] = [str(record["id"]) for record in records]
        if reconciled_added:
            notes.append(
                "Son kaynak uzlaştırmasında {0} ek mesaj bulundu ve işlendi."
                .format(reconciled_added))
        if pending:
            retry_pending(
                graph, script_dir, run_dir, pending, month_prefix, notes)
        save_pending(run_dir, pending)
        atomic_json(run_dir / "_beklenen.json", expected)
        atomic_json(run_dir / "_kaynak_idler.json", source_ids)

    control = run_control(script_dir, run_dir, start, end)
    contract.atomic_json(run_dir / "_kontrol_sonuc.json", control)
    elapsed = time.monotonic() - start_clock
    added_messages = len(processed_ids(run_dir) - before_ids)
    write_reports(
        run_dir, start, end, started_at, elapsed, control, notes,
        coverage_status=coverage_status, added_messages=added_messages)
    state.update({
        "durum": "TAMAMLANDI" if control.get("hukum") == "GECTI" else "BASARISIZ",
        "guncelleme": utc_now(),
        "sure_saniye": round(elapsed, 1),
        "kontrol": control.get("hukum"),
        "bu_calistirmada_eklenen": added_messages,
    })
    atomic_json(state_path, state)
    print("KONTROL: " + str(control.get("hukum")), flush=True)
    print("KOSU: " + str(run_dir), flush=True)
    return 0 if control.get("hukum") == "GECTI" else 2


def previous_month(month_start: dt.date) -> dt.date:
    return (month_start - dt.timedelta(days=1)).replace(day=1)


def run_completion_scans(args: argparse.Namespace) -> int:
    if args.ay is None:
        raise SystemExit("--tamamlayici-tarama yalnız --ay ile kullanılabilir")
    target = args.ay
    output_root = Path(args.hedef_kok)
    failures: list[str] = []
    results: list[dict] = []
    month = target
    for _ in range(3):
        month = previous_month(month)
        run_name = monthly_run_name(month)
        try:
            run_dir = run_directory(output_root, month.year, run_name)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if not run_dir.is_dir():
            print("TAMAMLAYICI: arşiv yok, atlandı: " + run_name, flush=True)
            results.append({"ay": month.strftime("%Y-%m"), "durum": "ARSIV_YOK"})
            continue
        print("TAMAMLAYICI: " + month.strftime("%Y-%m") + " güncelleniyor.",
              flush=True)
        child = argparse.Namespace(
            ay=month,
            baslangic=None,
            bitis=None,
            hedef_kok=args.hedef_kok,
            devam=False,
            tamamlayici_tarama=False,
            sadece_say=False,
        )
        result = execute(child)
        child_state = read_json(run_dir / "_durum.json", {})
        results.append({
            "ay": month.strftime("%Y-%m"),
            "durum": "GECTI" if result == 0 else "BASARISIZ",
            "eklenen": (child_state.get("bu_calistirmada_eklenen", 0)
                        if isinstance(child_state, dict) else 0),
        })
        if result != 0:
            failures.append(run_name)
    target_name = monthly_run_name(target)
    try:
        target_dir = run_directory(output_root, target.year, target_name)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if target_dir.is_dir():
        atomic_json(target_dir / "_tamamlayici_sonuc.json", {
            "guncelleme": utc_now(),
            "aylar": results,
        })
    if failures:
        print("TAMAMLAYICI KONTROL BASARISIZ: " + ", ".join(failures),
              file=sys.stderr)
        return 2
    return 0


def main() -> int:
    configure_console()
    parser = argparse.ArgumentParser(
        description="Kurumsal Outlook maillerini yerel dosyalara aktarır")
    parser.add_argument(
        "--ay", type=parse_month,
        help="Takvim ayı (YYYY-MM); geçmiş ay tam, içinde bulunulan ay bugüne kadar")
    parser.add_argument("--baslangic", type=parse_date)
    parser.add_argument("--bitis", type=parse_date)
    parser.add_argument("--hedef-kok", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--devam", action="store_true",
                        help="Var olan koşu klasöründen güvenli biçimde devam et")
    parser.add_argument("--tamamlayici-tarama", action="store_true")
    parser.add_argument("--sadece-say", action="store_true")
    args = parser.parse_args()
    try:
        if args.tamamlayici_tarama and args.ay is None:
            raise SystemExit("--tamamlayici-tarama yalnız --ay ile kullanılabilir")
        result = execute(args)
        if (result == 0 and args.tamamlayici_tarama
                and not args.sadece_say):
            return run_completion_scans(args)
        return result
    except KeyboardInterrupt:
        print("Kullanıcı tarafından durduruldu; _durum.json ile devam edilebilir.",
              file=sys.stderr)
        return 130
    except Exception as exc:
        print("HATA: {0}: {1}".format(type(exc).__name__, exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
