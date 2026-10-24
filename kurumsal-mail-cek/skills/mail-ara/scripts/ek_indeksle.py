"""Ek metinlerini aranabilir yapar: index\\ek_arama.sqlite (FTS5) + Chroma v2 "ekler" koleksiyonu.

    python ek_indeksle.py           # ekler.sqlite'taki yeni içerikleri ekle (artımlı)
    python ek_indeksle.py --durum

Kaynak: ek_cikar.py'nin ürettiği index\\ekler.sqlite (salt okunur açılır). mail-ara'nın sanal
ortamıyla koşar. Mail indeksiyle aynı kilidi (index\\indeksle.kilit) kullanır: Chroma yerel modda
aynı klasöre iki süreçten yazılmamalı.
Kelime indeksine içeriğin tamamı (en çok 60.000 karakter) girer; anlamsal indekse yalnız her
içeriğin ilk ANLAM_PARCA parçası (CPU süresi sınırlı kalsın; kelime araması daha güçlü çıktı).
"""
import aktarim
import argparse
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ortak  # noqa: E402

ortak.utf8_cikti()
EK_DB = ortak.KOK / "index" / "ekler.sqlite"
ARAMA_DB = ortak.KOK / "index" / "ek_arama.sqlite"
KILIT = ortak.KOK / "index" / "indeksle.kilit"
ANLAM_PARCA = 2
SEMA = """
CREATE TABLE IF NOT EXISTS yapildi(ozet TEXT PRIMARY KEY, parca INTEGER);
CREATE VIRTUAL TABLE IF NOT EXISTS ek_fts USING fts5(ozet UNINDEXED, ad, metin, tokenize='unicode61');
"""


def arama_db():
    ARAMA_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ARAMA_DB, timeout=60)
    db.executescript(SEMA)
    return db


def ek_koleksiyon():
    import chromadb
    if not ortak.v2_var():
        sys.exit("Ek indeksi v2 koleksiyon düzenini ister (index\\chroma_v2).")
    kol = chromadb.PersistentClient(path=str(ortak.CHROMA_V2)).get_or_create_collection(
        "ekler", embedding_function=ortak.e5_ef(), metadata={"hnsw:space": "cosine", "model": ortak.MODEL_ADI})
    return kol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--durum", action="store_true")
    ap.add_argument("--is-parcacigi", type=int, help="ONNX CPU iş parçacığı sayısı (pozitif)")
    a = ap.parse_args()
    if a.is_parcacigi is not None and a.is_parcacigi < 1:
        ap.error("--is-parcacigi pozitif olmalı")
    db = arama_db()
    kaynak = sqlite3.connect(f"{EK_DB.as_uri()}?mode=ro", uri=True, timeout=60)
    if a.durum:
        n = db.execute("SELECT COUNT(*), COALESCE(SUM(parca),0) FROM yapildi").fetchone()
        toplam = kaynak.execute("SELECT COUNT(*) FROM icerik WHERE durum='ok'").fetchone()[0]
        print(f"indekslenen içerik {n[0]} / metinli içerik {toplam}; anlamsal parça {n[1]}")
        return
    ortak.kilit_al(KILIT)
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    try:
        months = [r[0] for r in kaynak.execute("SELECT ay FROM ay_durum")]
        for ay in months:
            state = aktarim.contract.read_json(ortak.KOK / "index" / "aktarim" / (ay + ".json"), {})
            source = aktarim.require_month(ortak.ARSIV, ay)
            if state.get("source") != dict(run_id=source["run_id"], fingerprint=source["fingerprint"]) or state.get("stages", {}).get("ek_cikar", {}).get("durum") != "GECTI":
                raise ValueError("Güncel ek çıkarma aşaması yok: " + ay)
            aktarim.stage(ortak.KOK, ortak.ARSIV, ay, "ek_indeks")
        generation = aktarim.ensure_generation(ortak.KOK, "ek_indeks")
        yapildi = {r[0] for r in db.execute("SELECT ozet FROM yapildi")}
        adlar, mailler = {}, {}
        for ozet, ad, mail_id in kaynak.execute("SELECT ozet, ad, mail_id FROM ek ORDER BY ozet, ad"):
            adlar.setdefault(ozet, set()).add(ad)
            mailler.setdefault(ozet, set()).add(mail_id)
        source_contents = {o: m for o, m in kaynak.execute("SELECT ozet, metin FROM icerik WHERE durum='ok'") if o in adlar}
        adlar = {o: '\n'.join(sorted(ad)) for o, ad in adlar.items()}
        kol = ek_koleksiyon()
        # Aynı ek yeni bir mailde veya yeni dosya adıyla tekrar gelebilir.
        # İçerik hash'i sabit olsa da mail listesi ve ad alanı güncellenmelidir.
        eski_adlar = dict(db.execute("SELECT ozet, ad FROM ek_fts"))
        degisen = {o for o in yapildi if o in adlar and eski_adlar.get(o) != ortak.katla(adlar[o])}
        for offset in range(0, kol.count(), 5000):
            for meta in kol.get(offset=offset, limit=5000, include=["metadatas"])["metadatas"]:
                o = meta["ozet"]
                if o in yapildi and o in mailler and meta.get("mail_ids") != sorted(mailler[o]):
                    degisen.add(o)
        expected = {f"{o}#{n}" for o, text in source_contents.items() for n, _ in enumerate(ortak.parcala(text)[:ANLAM_PARCA])}
        vector_ids = set(kol.get(include=[])["ids"])
        missing = expected - vector_ids
        degisen.update(v.rsplit("#", 1)[0] for v in missing)
        stale_hashes = yapildi - set(source_contents)
        stale_vectors = vector_ids - expected
        for offset in range(0, len(stale_vectors), 5000):
            kol.delete(ids=sorted(stale_vectors)[offset:offset+5000])
        db.executemany("DELETE FROM yapildi WHERE ozet=?", [(o,) for o in stale_hashes])
        db.executemany("DELETE FROM ek_fts WHERE ozet=?", [(o,) for o in stale_hashes])
        db.commit()
        yeni = [(o, m) for o, m in source_contents.items() if o not in yapildi or o in degisen]
        print(f"{len(yeni) - len(degisen)} yeni, {len(degisen)} üst verisi güncellenen ek içeriği", flush=True)
        g, t0 = ortak.Gomucu(is_parcacigi=a.is_parcacigi), time.time()
        for b in range(0, len(yeni), 500):
            dilim = yeni[b: b + 500]
            if dilim:
                db.execute(f"DELETE FROM ek_fts WHERE rowid IN (SELECT rowid FROM ek_fts WHERE ozet IN ({','.join('?' for _ in dilim)}))",
                           [o for o, _ in dilim])
            db.executemany("INSERT INTO ek_fts(ozet, ad, metin) VALUES (?,?,?)",
                           [(o, ortak.katla(adlar.get(o, "")), ortak.katla(m)) for o, m in dilim])
            parcalar = []
            for o, m in dilim:
                for n, p in enumerate(ortak.parcala(m)[:ANLAM_PARCA]):
                    parcalar.append((f"{o}#{n}", o, f"Ek: {adlar.get(o, '')}\n{p}"))
            if parcalar:
                v = g.gom([p[2] for p in parcalar], "passage: ")
                # SQLite commit'inden önce kesilmiş bir koşunun Chroma parçaları kalabilir.
                # Aynı içerik kimliklerine upsert, tekrar çalıştırmada bu parçaları tamamlar.
                kol.upsert(ids=[p[0] for p in parcalar], embeddings=v.tolist(),
                        metadatas=[{"ozet": p[1], "mail_ids": sorted(mailler[p[1]])} for p in parcalar])
            sayac = {}
            for p in parcalar:
                sayac[p[1]] = sayac.get(p[1], 0) + 1
            db.executemany("INSERT OR REPLACE INTO yapildi VALUES (?,?)",
                           [(o, sayac.get(o, 0)) for o, _ in dilim])
            db.commit()
            print(f"  {b + len(dilim)}/{len(yeni)}  {time.time() - t0:.0f} sn", flush=True)
        if set(kol.get(include=[])["ids"]) != expected:
            raise ValueError("Ek Chroma parça kümesi kaynakla eşit değil")
        if {r[0] for r in db.execute("SELECT ozet FROM yapildi")} != set(source_contents):
            raise ValueError("Ek SQLite içerik kümesi kaynakla eşit değil")
        if {r[0] for r in db.execute("SELECT ozet FROM ek_fts")} != set(source_contents):
            raise ValueError("Ek FTS içerik kümesi kaynakla eşit değil")
        for ay in months:
            aktarim.stage(ortak.KOK, ortak.ARSIV, ay, "ek_indeks", True,
                          dict(generation=generation, icerik=len(source_contents), parca=len(expected)))
        print(f"bitti: {len(yeni)} içerik, {time.time() - t0:.0f} sn")
    finally:
        db.close()
        kaynak.close()
        KILIT.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
