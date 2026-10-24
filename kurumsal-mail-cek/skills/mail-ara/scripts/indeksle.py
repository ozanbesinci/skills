"""Mail arşivini yerel arama indeksine yazar (artımlı).

    python indeksle.py --durum            # hangi ay indekste, kaç mail
    python indeksle.py --ay 2026-09       # tek ay (yeni çekilen ay için)
    python indeksle.py --tumu             # arşivdeki bütün aylar; değişmeyen mail atlanır
    python indeksle.py --ay 2026-08 --yeniden   # o ayı baştan yaz

Mail düzeyinde artımlıdır: yeni gövde eklenir, boyutu/zamanı değişen gövde (onarım)
yeniden yazılır, arşivden kalkan gövde indeksten de düşer. Arşive hiçbir şey yazmaz.
"""
import aktarim
import hashlib
import json
import argparse
import csv
import email
import email.policy
import functools
import html as htmlmod
import os
import re
import sys
import time
from datetime import datetime
from email.parser import HeaderParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ortak  # noqa: E402

ortak.utf8_cikti()
KILIT = ortak.KOK / "index" / "indeksle.kilit"


def html_metin(html):
    html = re.sub(r"(?is)<(style|script|head)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    return htmlmod.unescape(html)


def eml_govde(yol):
    """Düz metne çevrilememiş mailler gövde klasöründe ham .eml olarak durur (%2)."""
    msg = email.message_from_bytes(yol.read_bytes(), policy=email.policy.default)
    parca = msg.get_body(preferencelist=("plain", "html"))
    if parca is None:
        return msg, ""
    try:
        metin = parca.get_content()
    except Exception:
        metin = (parca.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
    if parca.get_content_type() == "text/html":
        metin = html_metin(metin)
    return msg, metin


def csv_ust_veri(ay_klasoru):
    """Ayın mailler.csv'si (kurumsal-mail-cek ürünü): sira_no → satır. Yoksa boş."""
    yol = ay_klasoru / "mailler.csv"
    if not yol.exists():
        return {}
    with yol.open(encoding="utf-8-sig", newline="") as f:
        return {r["sira_no"]: r for r in csv.DictReader(f, delimiter=";")}


def csv_kisi(ad, adres):
    ad, adres = (ad or "").strip(), (adres or "").strip().strip('"')
    # İç göndericide adres X.500 biçimindedir (/O=EXCHANGELABS/...); yalnız ad anlamlı.
    return f"{ad} <{adres}>" if "@" in adres else ad


def mail_oku(govde, basliklar, parser, csv_rows=None):
    mail_id = govde.name.split("_", 1)[0]
    b = basliklar / f"{mail_id}.txt"
    bas = {}
    if b.exists():
        # PST/MAPI yoluyla gelen aylarda (2024-01 → 2025-08) başlık satırları arasında boş satır
        # var; ayrıştırıcı ilk boş satırı başlık sonu sayıp yalnız ilk Received'ı alıyordu.
        # Dosyada gövde yok, bu yüzden bütün boş satırları atmak güvenli.
        satirlar = b.read_text(encoding="utf-8", errors="replace").splitlines()
        bas = parser.parsestr("\n".join(s for s in satirlar if s.strip()) + "\n\n")
    if govde.suffix == ".eml":
        msg, ham = eml_govde(govde)
        bas = bas or msg
    else:
        ham = govde.read_text(encoding="utf-8", errors="replace")
    kimden = ortak.baslik_coz(bas.get("From"))
    kime = ortak.baslik_coz(bas.get("To"))
    cc = ortak.baslik_coz(bas.get("CC"))
    konu = ortak.baslik_coz(bas.get("Subject"))
    tarih, tarih_int = ortak.tarih_coz(bas.get("Date"))
    if not tarih_int or not kimden:
        # Gönderilmiş Öğeler'de sunucu başlığı oluşmaz ("MAPI transport başlığı yok");
        # aynı mailin üst verisi ayın mailler.csv dosyasında eksiksiz durur (v1.0.2).
        r = (csv_rows if csv_rows is not None else csv_ust_veri(basliklar.parent)).get(mail_id)
        if r:
            kimden = kimden or csv_kisi(r.get("gonderen_ad"), r.get("gonderen_mail"))
            kime = kime or (r.get("kime") or "").replace(" | ", ", ")
            cc = cc or (r.get("cc") or "").replace(" | ", ", ")
            konu = konu or (r.get("konu") or "").strip()
            zaman = (r.get("gonderilme_zamani") or r.get("alinma_zamani") or "").strip()
            if not tarih_int and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", zaman):
                tarih, tarih_int = zaman, int(zaman[:10].replace("-", ""))
    metin = ortak.temizle(ham)
    return dict(mail_id=mail_id, tarih=tarih, tarih_int=tarih_int, kimden=kimden, kime=kime,
                cc=cc, konu=konu, metin=metin)


def ay_indeksle(ay, db, kol, gomucu, yeniden=False):
    klasor = ortak.ay_klasoru(ay)
    aktarim.stage(ortak.KOK, ortak.ARSIV, ay, "govde")
    generation = aktarim.ensure_generation(ortak.KOK, "govde")
    journal = ortak.KOK / "index" / ("govde-islem-" + ay + ".json")
    old_journal = aktarim.contract.read_json(journal, {})
    govdeler, basliklar = klasor / "govdeler", klasor / "basliklar"
    diskte = {}
    # .eml önce, .txt sonra: aynı kimlikte ikisi birden varsa düz metin kazanır.
    for g in sorted(govdeler.iterdir(), key=lambda p: p.suffix != ".eml"):
        if g.is_file() and g.suffix in (".txt", ".eml"):
            st = g.stat()
            diskte[g.name.split("_", 1)[0]] = (g, st.st_size, st.st_mtime)

    kayitli = {r[0]: (r[1], r[2], r[3], r[4], r[5]) for r in
               db.execute("SELECT mail_id, boyut, mtime, parca, tarih_int, kimden FROM mail WHERE ay=?", (ay,))}
    metadata = csv_ust_veri(klasor)
    fingerprints = {}
    for mail_id, (path, _, _) in diskte.items():
        header = basliklar / (mail_id + ".txt")
        fingerprints[mail_id] = hashlib.sha256((aktarim.contract.digest(path) +
            (aktarim.contract.digest(header) if header.exists() else "") +
            json.dumps(metadata.get(mail_id, {}), sort_keys=True, ensure_ascii=False) + generation).encode()).hexdigest()
    old_fingerprints = dict(db.execute("SELECT mail_id, fingerprint FROM mail_fingerprint"))
    if yeniden:
        degisen = set(diskte)
    else:
        # Tarihi okunamamış kayıt da yeniden denenir (başlık ayrıştırma düzeltmesi, v1.0.1).
        degisen = {m for m, (_, boyut, mt) in diskte.items()
                   if m not in kayitli or kayitli[m][0] != boyut or abs(kayitli[m][1] - mt) > 1
                   or not kayitli[m][3] or not kayitli[m][4]
                   or old_fingerprints.get(m) != fingerprints[m]}
    degisen |= set(old_journal.get("changed", [])) & set(diskte)
    silinecek = (set(kayitli) - set(diskte)) | (degisen & set(kayitli))

    planned = set(old_journal.get("vectors", []))
    planned.update(f"{m}#{n}" for m in silinecek for n in range(kayitli[m][2] or 1))
    planned.update(f"{m}#{n}" for m in degisen for n in range(max(1,
        len(ortak.parcala(mail_oku(diskte[m][0], basliklar, HeaderParser(), metadata)["metin"])))))
    aktarim.contract.atomic_json(journal, dict(changed=sorted(degisen), vectors=sorted(planned)))
    if planned:
        for i in range(0, len(planned), 5000):
            kol.delete(ids=sorted(planned)[i:i+5000])
    if silinecek:
        eski_parcalar = [f"{m}#{n}" for m in silinecek for n in range(kayitli[m][2] or 1)]
        for i in range(0, len(eski_parcalar), 5000):
            kol.delete(ids=eski_parcalar[i: i + 5000])
        db.executemany("DELETE FROM mail WHERE mail_id=?", [(m,) for m in silinecek])
        db.executemany("DELETE FROM mail_fts WHERE mail_id=?", [(m,) for m in silinecek])

    if not degisen:
        count, chunks = db.execute("SELECT COUNT(*), COALESCE(SUM(parca),0) FROM mail WHERE ay=?", (ay,)).fetchone()
        db.execute("INSERT OR REPLACE INTO ay_durum VALUES (?,?,?,?,?)",
                   (ay, count, chunks, datetime.now().isoformat(), ortak.MODEL_ADI))
        db.executemany("DELETE FROM mail_fingerprint WHERE mail_id=?", [(m,) for m in silinecek])
        db.commit()
        verify_month(ay, db, kol, diskte)
        journal.unlink(missing_ok=True)
        aktarim.stage(ortak.KOK, ortak.ARSIV, ay, "govde", True, dict(generation=generation, mail=count, parca=chunks))
        print(f"{ay}: değişiklik yok ({len(diskte)} mail)")
        return 0

    parser = HeaderParser()
    mailler, parcalar = [], []
    for m in sorted(degisen):
        g, boyut, mt = diskte[m]
        k = mail_oku(g, basliklar, parser, metadata)
        k.update(ay=ay, dosya=str(g), boyut=boyut, mtime=mt)
        bolumler = ortak.parcala(k["metin"]) if k["metin"] else [""]
        k["parca"] = len(bolumler)
        mailler.append(k)
        for n, p in enumerate(bolumler):
            parcalar.append((f"{m}#{n}", m, k["tarih_int"],
                             f"Konu: {k['konu']}\nKimden: {k['kimden']}\n{p}"))

    t0 = time.time()
    v2 = ortak.v2_var()

    def ilerleme(yapilan, toplam):
        if yapilan % 1024 < 32 or yapilan == toplam:
            gecen = time.time() - t0
            kalan = gecen / yapilan * (toplam - yapilan)
            print(f"  {ay}: {yapilan}/{toplam} parça, kalan ~{kalan / 60:.0f} dk", flush=True)

    vektorler = gomucu.gom([p[3] for p in parcalar], "passage: ", ilerleme=ilerleme)
    for i in range(0, len(parcalar), 2000):
        dilim = parcalar[i: i + 2000]
        kw = dict(ids=[p[0] for p in dilim],
                  embeddings=vektorler[i: i + 2000].tolist(),
                  metadatas=[{"mail_id": p[1], "ay": ay, "tarih_int": p[2]} for p in dilim])
        if not v2:
            # v1 metni Chroma'ya da yazıyordu; v2'de metin yalnız mail.sqlite/FTS5'te durur.
            kw["documents"] = [p[3] for p in dilim]
        kol.upsert(**kw)

    db.executemany(
        "INSERT OR REPLACE INTO mail VALUES (:mail_id,:ay,:tarih,:tarih_int,:kimden,:kime,:cc,"
        ":konu,:dosya,:boyut,:mtime,:parca,:metin,:kimden_k,:kisiler_k)",
        [dict(k, kimden_k=ortak.katla(k["kimden"]),
              kisiler_k=ortak.katla(" ".join((k["kimden"], k["kime"], k["cc"])))) for k in mailler])
    db.executemany(
        "INSERT INTO mail_fts(mail_id, konu, kisiler, metin) VALUES (?,?,?,?)",
        [(k["mail_id"], ortak.katla(k["konu"]),
          ortak.katla(" ".join((k["kimden"], k["kime"], k["cc"]))), ortak.katla(k["metin"]))
         for k in mailler])
    toplam_mail, toplam_parca = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(parca),0) FROM mail WHERE ay=?", (ay,)).fetchone()
    db.execute("INSERT OR REPLACE INTO ay_durum VALUES (?,?,?,?,?)",
               (ay, toplam_mail, toplam_parca, datetime.now().strftime("%Y-%m-%d %H:%M"),
                ortak.MODEL_ADI))
    db.executemany("DELETE FROM mail_fingerprint WHERE mail_id=?", [(m,) for m in silinecek])
    db.executemany("INSERT OR REPLACE INTO mail_fingerprint VALUES (?,?)", [(m, fingerprints[m]) for m in degisen])
    db.commit()
    verify_month(ay, db, kol, diskte)
    journal.unlink(missing_ok=True)
    aktarim.stage(ortak.KOK, ortak.ARSIV, ay, "govde", True,
                  dict(generation=generation, mail=toplam_mail, parca=toplam_parca))
    print(f"{ay}: {len(mailler)} mail yazıldı, {len(silinecek - degisen)} düştü, "
          f"{len(parcalar)} parça, {time.time() - t0:.0f} sn")
    return len(mailler)


def verify_month(ay, db, kol, diskte):
    actual = {r[0]: r[1] for r in db.execute("SELECT mail_id, parca FROM mail WHERE ay=?", (ay,))}
    if set(actual) != set(diskte):
        raise ValueError("SQLite/arşiv mail kimlikleri eşit değil")
    expected = {f"{m}#{n}" for m, count in actual.items() for n in range(count or 1)}
    vectors = set(kol.get(where={"ay": ay}, include=[])["ids"])
    if vectors != expected:
        raise ValueError("Gövde SQLite/Chroma parça kimlikleri eşit değil")
    fts = {r[0] for r in db.execute("SELECT mail_id FROM mail_fts WHERE mail_id IN (SELECT mail_id FROM mail WHERE ay=?)", (ay,))}
    if fts != set(actual):
        raise ValueError("Gövde FTS/SQLite kimlikleri eşit değil")


def uyanik_tut():
    """Süreç yaşadıkça Windows boşta uykusunu ertele; ayar değiştirmez, süreçle biter."""
    if os.name == "nt":
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def durum(db):
    satirlar = {r[0]: r for r in db.execute("SELECT * FROM ay_durum ORDER BY ay")}
    print(f"{'ay':8} {'mail':>7} {'parça':>7}  indekslenme")
    for ay in ortak.arsiv_aylari():
        r = satirlar.get(ay)
        print(f"{ay:8} {r[1]:>7} {r[2]:>7}  {r[3]}" if r else f"{ay:8} {'—':>7} {'—':>7}  indekste yok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ay", action="append", default=[], help="YYYY-AA, tekrar edilebilir")
    ap.add_argument("--tumu", action="store_true")
    ap.add_argument("--yeniden", action="store_true")
    ap.add_argument("--durum", action="store_true")
    a = ap.parse_args()

    db = ortak.db_ac()
    if a.durum or not (a.ay or a.tumu):
        durum(db)
        return

    ortak.kilit_al(KILIT)
    uyanik_tut()
    try:
        # En yeni ay önce: uzun ilk kurulumda güncel aylar erken aranabilir olur.
        aylar = sorted(ortak.arsiv_aylari(), reverse=True) if a.tumu else a.ay
        kol, gomucu = ortak.koleksiyon(), ortak.Gomucu()
        t0 = time.time()
        toplam = sum(ay_indeksle(ay, db, kol, gomucu, a.yeniden) for ay in aylar)
        print(f"Bitti: {toplam} mail yazıldı, {len(aylar)} ay, {(time.time() - t0) / 60:.1f} dk")
    finally:
        db.close()
        KILIT.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
