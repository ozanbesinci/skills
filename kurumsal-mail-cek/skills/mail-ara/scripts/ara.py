"""Mail arşivinde hibrit arama: anlamsal (Chroma) + kelime (SQLite FTS5) + kişi/tarih süzgeci.

    python ara.py "gördes ges arazi tapu sorunu"
    python ara.py "konteyner teklifi" --bas 2026-08-01 --bit 2026-08-31
    python ara.py "ödeme blokajı" --kimden burak --adet 25
    python ara.py --kimden "burak yılmaz" --bas 2026-08-01 --listele   # soru yok: tarih sırasıyla liste
    python ara.py --tam 202608-05596 202608-05597                       # mailin temiz metni + dosya yolu
    python ara.py "..." --mod kelime | anlam                            # tek yöntem

    python ara.py "teklif birim fiyat" --mod ek                         # yalnız eklerin içinde
    python ara.py "..." --eksiz                                         # ekleri katma

Kişi süzgeçleri katlanmış metinde arar ('yilmaz' = 'Yılmaz'). Sonuç satırındaki
[A] anlamsal, [K] kelime, [E] ek (PDF/Excel/Word metni) eşleşmesidir; harfler birleşebilir.
"""
import argparse
import os
import re
import sqlite3
import sys
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ortak  # noqa: E402

ortak.utf8_cikti()

DURAK = set("""ve veya ile bir bu su o ne mi mu mı mü icin olan gibi da de ki hangi nedir nasil
neden kim kimin ne zaman hakkinda konusunda ilgili var mi yok ama fakat daha en cok her hep son
durum durumu asama asamada""".split())
RRF_K = 60
KOK_UZ = int(os.environ.get("MAIL_KOK_UZ", 5))   # 5 harf kökü; 71 soruda kelime ilk5 44→49 (2026-10-14)
KELIME_AGIRLIK = float(os.environ.get("MAIL_KELIME_AGIRLIK", 1))
ANLAM_AGIRLIK = float(os.environ.get("MAIL_ANLAM_AGIRLIK", 0.5))   # kişi hibrit MRR 0,67→0,73
EK_AGIRLIK = float(os.environ.get("MAIL_EK_AGIRLIK", 0.1))  # 71 soruda ilk5 43→51, kişi kapsamı 8/9 korunur
IN_SINIRI = 30000   # Chroma $in → SQLite değişkeni; 33 binde "too many SQL variables" (1.5.9)


def tarih_int(s):
    return int(s.replace("-", "")) if s else None


def suzgec_sql(a):
    kosul, deger = [], []
    if a.kimden:
        kosul.append("m.kimden_k LIKE ?")
        deger.append(f"%{ortak.katla(a.kimden)}%")
    if a.kisi:
        kosul.append("m.kisiler_k LIKE ?")
        deger.append(f"%{ortak.katla(a.kisi)}%")
    if a.bas:
        kosul.append("m.tarih_int >= ?")
        deger.append(tarih_int(a.bas))
    if a.bit:
        kosul.append("m.tarih_int <= ?")
        deger.append(tarih_int(a.bit))
    return kosul, deger


def fts_sorgu(soru):
    terimler = [t for t in re.findall(r"\w+", ortak.katla(soru)) if len(t) > 1 and t not in DURAK]
    # Türkçe ekler için önek eşleşmesi: 'konteyner*' → konteynerin, konteynerler
    return " OR ".join(f'"{t[:KOK_UZ] if KOK_UZ else t}"*' if len(t) >= 4 else f'"{t}"'
                       for t in terimler)


def kelime_ara(db, soru, a, sinir):
    fts = fts_sorgu(soru)
    if not fts:
        return []
    kosul, deger = suzgec_sql(a)
    where = " AND ".join(["mail_fts MATCH ?"] + kosul)
    rows = db.execute(
        f"SELECT f.mail_id FROM mail_fts f JOIN mail m ON m.mail_id = f.mail_id "
        f"WHERE {where} ORDER BY bm25(mail_fts, 0, 4.0, 1.0, 1.0) LIMIT ?",
        [fts] + deger + [sinir]).fetchall()
    return [r[0] for r in rows]


def anlam_ara(db, soru, a, sinir):
    kol = ortak.koleksiyon()
    v = ortak.Gomucu().gom([soru], "query: ")[0].tolist()
    tarih = []
    if a.bas:
        tarih.append({"tarih_int": {"$gte": tarih_int(a.bas)}})
    if a.bit:
        tarih.append({"tarih_int": {"$lte": tarih_int(a.bit)}})
    izinli = None
    if a.kimden or a.kisi:
        kosul, deger = suzgec_sql(a)
        izinli = sorted({r[0] for r in db.execute(
            f"SELECT m.mail_id FROM mail m WHERE {' AND '.join(kosul)}", deger)})
        if not izinli:
            return []
        if len(izinli) <= IN_SINIRI:
            # Kişi süzgeci Chroma'nın içinde: önce süzüp sonra sıralar. Sonradan süzme,
            # seyrek bir kişide ilk N parçanın çoğunu atıyordu (ölçüm: 30 mailde 4 → 30).
            tarih.append({"mail_id": {"$in": izinli}})
    where = tarih[0] if len(tarih) == 1 else ({"$and": tarih} if tarih else None)
    ici_suzuldu = izinli is not None and len(izinli) <= IN_SINIRI
    carpan = 3 if izinli is None or ici_suzuldu else 15
    n = min(kol.count(), sinir * carpan)
    if n == 0:
        return []
    sonuc = kol.query(query_embeddings=[v], n_results=n, where=where, include=["metadatas"])
    sirali = []
    for meta in sonuc["metadatas"][0]:
        if meta["mail_id"] not in sirali:
            sirali.append(meta["mail_id"])
    if izinli is not None and not ici_suzuldu:
        # SQLite değişken sınırı (~32 bin) aşıldı: geniş havuzdan sonradan süz.
        kume = set(izinli)
        sirali = [m for m in sirali if m in kume]
    return sirali[:sinir]


EK_DB = ortak.KOK / "index" / "ekler.sqlite"
EK_ARAMA_DB = ortak.KOK / "index" / "ek_arama.sqlite"


def _ek_izinli(db, a):
    """Kişi/tarih süzgecine uyan mail eklerinin içerik kimlikleri; None = süzgeç yok."""
    kosul, deger = suzgec_sql(a)
    if not kosul:
        return None
    mailler = [r[0] for r in db.execute(
        f"SELECT m.mail_id FROM mail m WHERE {' AND '.join(kosul)}", deger)]
    izinli = set()
    with closing(sqlite3.connect(f"file:{EK_DB}?mode=ro", uri=True, timeout=30)) as kaynak:
        for i in range(0, len(mailler), 900):
            dilim = mailler[i:i + 900]
            yerler = ','.join('?' for _ in dilim)
            izinli.update(r[0] for r in kaynak.execute(
                f"SELECT DISTINCT ozet FROM ek WHERE mail_id IN ({yerler}) AND durum='ok'", dilim))
    return sorted(izinli)


def _eki_maile(db, ozetler, a, sinir):
    """Sıralı ek içerik özetlerini (SHA-1) o eki taşıyan maillere çevirir; kişi/tarih süzgeci uygulanır."""
    kosul, deger = suzgec_sql(a)
    sirali, ad = [], {}
    where = " AND ".join(["m.mail_id=?"] + kosul)
    with closing(sqlite3.connect(f"file:{EK_DB}?mode=ro", uri=True, timeout=30)) as kaynak:
        for o in ozetler:
            for m, eki, dosya in kaynak.execute("SELECT mail_id, ad, dosya FROM ek WHERE ozet=? ORDER BY mail_id DESC", (o,)):
                if m in ad or not db.execute(f"SELECT 1 FROM mail m WHERE {where}", [m] + deger).fetchone():
                    continue
                sirali.append(m)
                ad[m] = {"ad": eki, "dosya": dosya, "ozet": o}
                if len(sirali) >= sinir:
                    return sirali, ad
    return sirali[:sinir], ad


def ek_kelime_ara(db, soru, a, sinir):
    """Eklerin (PDF/Excel/Word metni) Türkçe kelime araması → mail listesi + ek adı."""
    fts = fts_sorgu(soru)
    if not fts or not EK_ARAMA_DB.exists():
        return [], {}
    izinli = _ek_izinli(db, a)
    if izinli == []:
        return [], {}
    where, deger = "ek_fts MATCH ?", [fts]
    if izinli is not None and len(izinli) <= IN_SINIRI:
        where += f" AND ozet IN ({','.join('?' for _ in izinli)})"
        deger += izinli
    with closing(sqlite3.connect(f"file:{EK_ARAMA_DB}?mode=ro", uri=True, timeout=30)) as ek:
        ozetler = [r[0] for r in ek.execute(
            f"SELECT ozet FROM ek_fts WHERE {where} ORDER BY bm25(ek_fts, 0, 2.0, 1.0) LIMIT ?",
            deger + [sinir * 3])]
    return _eki_maile(db, ozetler, a, sinir)


def ek_anlam_ara(db, soru, a, sinir):
    if not EK_ARAMA_DB.exists() or not ortak.v2_var():
        return [], {}
    import chromadb
    try:
        kol = chromadb.PersistentClient(path=str(ortak.CHROMA_V2)).get_collection(
            "ekler", embedding_function=ortak.e5_ef())
    except chromadb.errors.NotFoundError:
        return [], {}
    n = min(kol.count(), sinir * 3)
    if n <= 0:
        return [], {}
    izinli = _ek_izinli(db, a)
    if izinli == []:
        return [], {}
    where = {"ozet": {"$in": izinli}} if izinli is not None and len(izinli) <= IN_SINIRI else None
    r = kol.query(query_texts=[soru], n_results=n, where=where, include=["metadatas"])
    ozetler = []
    for meta in r["metadatas"][0]:
        if meta["ozet"] not in ozetler:
            ozetler.append(meta["ozet"])
    return _eki_maile(db, ozetler, a, sinir)


def ozet(metin, soru, uzunluk=260):
    """Sorunun ilk geçtiği yerin çevresinden kısa alıntı; yoksa baştan."""
    tek = metin.replace("\n", " ")
    katli = ortak.katla(tek)
    for t in re.findall(r"\w{4,}", ortak.katla(soru or "")):
        i = katli.find(t)
        if i >= 0:
            bas = max(0, i - 80)
            return ("…" if bas else "") + tek[bas: bas + uzunluk]
    return tek[:uzunluk]


def yaz(db, ids, kaynak, soru, puan=None, ek_ad=None):
    for sira, m in enumerate(ids, 1):
        r = db.execute("SELECT tarih, kimden, konu, metin, dosya FROM mail WHERE mail_id=?",
                       (m,)).fetchone()
        if not r:
            continue
        etiket = "".join(k for k in "AKE" if m in kaynak.get(k, ()))
        p = f" {puan[m]:.4f}" if puan else ""
        print(f"{sira:>3}. [{etiket or '-':3}]{p} {m}  {r[0]}  {r[1][:45]}")
        print(f"     Konu: {r[2][:110]}")
        if ek_ad and m in ek_ad:
            ek = ek_ad[m]
            print(f"     Ek: {ek['ad']}")
            with closing(sqlite3.connect(f"file:{EK_DB}?mode=ro", uri=True, timeout=30)) as e:
                metin = e.execute("SELECT metin FROM icerik WHERE ozet=?", (ek["ozet"],)).fetchone()
            if metin:
                print(f"     Ek alıntısı: {ozet(metin[0], soru)}")
            print(f"     Ek dosyası: {ek['dosya']}")
        print(f"     {ozet(r[3], soru)}")
        print(f"     {r[4]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("soru", nargs="?", default="")
    ap.add_argument("--kimden", help="gönderende geçen ad/adres parçası")
    ap.add_argument("--kisi", help="kimden/kime/bilgi alanlarından herhangi birinde geçen")
    ap.add_argument("--bas", help="YYYY-AA-GG (dahil)")
    ap.add_argument("--bit", help="YYYY-AA-GG (dahil)")
    ap.add_argument("--adet", type=int, default=15)
    ap.add_argument("--mod", choices=["hibrit", "anlam", "kelime", "ek"], default="hibrit",
                    help="ek: yalnız ek (PDF/Excel/Word) içeriğinde ara")
    ap.add_argument("--eksiz", action="store_true", help="ekleri aramaya katma")
    ap.add_argument("--listele", action="store_true", help="soru olmadan süzgece uyan mailleri sırala")
    ap.add_argument("--tam", nargs="+", metavar="MAIL_ID", help="mailin temiz metnini bas")
    a = ap.parse_args()

    if not ortak.DB_YOLU.exists():
        sys.exit("İndeks yok. Önce: python indeksle.py --tumu")
    db = ortak.db_ac()

    if a.tam:
        for m in a.tam:
            r = db.execute("SELECT tarih, kimden, kime, cc, konu, dosya, metin FROM mail "
                           "WHERE mail_id=?", (m,)).fetchone()
            if not r:
                print(f"=== {m}: indekste yok")
                continue
            print(f"=== {m} | {r[0]}\nKimden: {r[1]}\nKime: {r[2]}\nBilgi: {r[3]}\n"
                  f"Konu: {r[4]}\nDosya: {r[5]}\n\n{r[6]}\n")
        return

    if a.listele or not a.soru:
        kosul, deger = suzgec_sql(a)
        if not kosul:
            sys.exit("Soru ya da en az bir süzgeç (--kimden/--kisi/--bas/--bit) gerekli.")
        rows = db.execute(f"SELECT m.mail_id FROM mail m WHERE {' AND '.join(kosul)} "
                          f"ORDER BY m.tarih_int, m.tarih", deger).fetchall()
        print(f"{len(rows)} mail süzgece uyuyor" + (f", ilk {a.adet}" if len(rows) > a.adet else ""))
        yaz(db, [r[0] for r in rows[: a.adet]], {}, "")
        return

    havuz = max(a.adet * 4, 60)
    kaynak, kollar, ek_ad = {}, [], {}
    if a.mod in ("hibrit", "kelime"):
        kaynak["K"] = kelime_ara(db, a.soru, a, havuz)
        kollar.append((KELIME_AGIRLIK, kaynak["K"]))
    if a.mod in ("hibrit", "anlam"):
        kaynak["A"] = anlam_ara(db, a.soru, a, havuz)
        kollar.append((ANLAM_AGIRLIK, kaynak["A"]))
    if not a.eksiz and a.mod in ("hibrit", "kelime", "ek"):
        ek_k, ad1 = ek_kelime_ara(db, a.soru, a, havuz)
        kollar.append((EK_AGIRLIK * KELIME_AGIRLIK, ek_k))
        ek_ad.update(ad1)
        ek_a = []
        if a.mod in ("hibrit", "ek"):
            ek_a, ad2 = ek_anlam_ara(db, a.soru, a, havuz)
            kollar.append((EK_AGIRLIK * ANLAM_AGIRLIK, ek_a))
            for m, v in ad2.items():
                ek_ad.setdefault(m, v)
        kaynak["E"] = list(dict.fromkeys(ek_k + ek_a))

    puan = {}
    for agirlik, liste in kollar:
        for sira, m in enumerate(liste):
            puan[m] = puan.get(m, 0) + agirlik / (RRF_K + sira + 1)
    ids = sorted(puan, key=puan.get, reverse=True)[: a.adet]
    print(f"{len(puan)} aday (kelime {len(kaynak.get('K', []))}, anlam {len(kaynak.get('A', []))}, "
          f"ek {len(kaynak.get('E', []))}); ilk {len(ids)}:")
    yaz(db, ids, {k: set(v) for k, v in kaynak.items()}, a.soru, puan, ek_ad)


if __name__ == "__main__":
    main()
