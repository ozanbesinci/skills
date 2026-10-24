"""mail-ara'yı sabit soru setiyle ölçer: kelime / anlam / hibrit ve kişi süzgeci.

    python degerlendir.py                       # varsayılan set, özet tablo
    python degerlendir.py --set <soru.json> --json <çıktı.json>
    python degerlendir.py --ekli --json <çıktı.json>  # aynı sorularda ekli / eksiz karşılaştırma

Doğru cevap: hedef mail + aynı yazışma zincirindeki mailler (konu önekleri ve [EXTERNAL]
gibi etiketler atılmış aynı konu, ±90 gün). Ölçüler: ilk 1 / 5 / 10 isabet ve MRR@10.
Kişi soruları (tur=kisi) anlamsal kolda iki yöntemle ölçülür: v1.0.x'in sonradan süzmesi
(eski) ve Chroma içi mail_id $in ön-süzgeci (yeni). Arşive ve indekse yazmaz.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ortak  # noqa: E402
import ara  # noqa: E402

ortak.utf8_cikti()
VARSAYILAN_SET = ortak.KOK / "degerlendirme" / "soru-seti-v1.json"
ONEK = re.compile(r"^\s*((re|fw|fwd|ynt|ilt|sv|aw|tr|cevap|yanit)\s*:\s*|\[[^\]]*\]\s*)", re.I)


def konu_kok(konu):
    k = konu or ""
    while True:
        y = ONEK.sub("", k)
        if y == k:
            break
        k = y
    return ortak.katla(k).strip()


def dogrular(db, hedef):
    r = db.execute("SELECT konu, tarih FROM mail WHERE mail_id=?", (hedef,)).fetchone()
    if not r:
        return {hedef}
    kok, t = konu_kok(r[0]), r[1]
    if len(kok) < 6 or not t:
        return {hedef}
    t0 = datetime.strptime(t[:10], "%Y-%m-%d").toordinal()
    kume = {hedef}
    for m, k, tt in db.execute("SELECT mail_id, konu, tarih FROM mail WHERE tarih_int BETWEEN ? AND ?",
                               (int(datetime.fromordinal(t0 - 90).strftime("%Y%m%d")),
                                int(datetime.fromordinal(t0 + 90).strftime("%Y%m%d")))):
        if konu_kok(k) == kok:
            kume.add(m)
    return kume


def eski_anlam(db, soru, a, sinir):
    """v1.0.x anlamsal kolu: süzgeçsiz ilk sinir*8 parça, kişi süzgeci sonradan."""
    kol = ortak.koleksiyon()
    v = ortak.Gomucu().gom([soru], "query: ")[0].tolist()
    n = min(kol.count(), sinir * 8)
    sonuc = kol.query(query_embeddings=[v], n_results=n, include=["metadatas"])
    sirali = []
    for meta in sonuc["metadatas"][0]:
        if meta["mail_id"] not in sirali:
            sirali.append(meta["mail_id"])
    kosul, deger = ara.suzgec_sql(a)
    izinli = {r[0] for r in db.execute(f"SELECT m.mail_id FROM mail m WHERE {' AND '.join(kosul)}", deger)}
    return [m for m in sirali if m in izinli][:sinir]


def rrf(kelime, anlam, ek_kelime=(), ek_anlam=()):
    puan = {}
    for agirlik, liste in ((ara.KELIME_AGIRLIK, kelime), (ara.ANLAM_AGIRLIK, anlam),
                          (ara.EK_AGIRLIK * ara.KELIME_AGIRLIK, ek_kelime),
                          (ara.EK_AGIRLIK * ara.ANLAM_AGIRLIK, ek_anlam)):
        for s, m in enumerate(liste):
            puan[m] = puan.get(m, 0) + agirlik / (ara.RRF_K + s + 1)
    return sorted(puan, key=puan.get, reverse=True)


def olc(sonuclar, dogru):
    sira = next((i + 1 for i, m in enumerate(sonuclar[:10]) if m in dogru), None)
    return sira


def ozet(satirlar):
    n = len(satirlar)
    if not n:
        return "-"
    s = [x for x in satirlar]
    return (f"ilk1 {sum(1 for x in s if x == 1)}/{n}  ilk5 {sum(1 for x in s if x and x <= 5)}/{n}  "
            f"ilk10 {sum(1 for x in s if x)}/{n}  MRR {sum(1 / x for x in s if x) / n:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=str(VARSAYILAN_SET))
    ap.add_argument("--json")
    ap.add_argument("--ekli", action="store_true", help="ek kolunu ve ekli/eksiz hibriti ayrıca ölç")
    ap.add_argument("--siralamalar", action="store_true", help="JSON'a aday kimliklerini ekle; aynı sıralarda ağırlık kıyası için")
    a = ap.parse_args()
    veri = json.load(open(a.set, encoding="utf-8"))
    db = ortak.db_ac()
    if a.ekli:
        if not ara.EK_DB.exists() or not ara.EK_ARAMA_DB.exists():
            ap.error("--ekli için ek çıkarma ve ek indeksleme tamamlanmış olmalı.")
        from ek_indeksle import arama_db
        from contextlib import closing
        with closing(arama_db()) as ek_db:
            if not ek_db.execute("SELECT COUNT(*) FROM yapildi").fetchone()[0]:
                ap.error("Ek indeksi boş; ekli ölçüm yapılmadı.")
    havuz = 60
    sonuc = {"set": veri.get("surum"), "koleksiyon": "v2" if ortak.v2_var() else "v1",
             "ekli_olcum": a.ekli, "ek_agirlik": ara.EK_AGIRLIK, "sorular": []}
    for q in veri["sorular"]:
        ns = SimpleNamespace(kimden=q.get("kimden"), kisi=None, bas=None, bit=None)
        bos = SimpleNamespace(kimden=None, kisi=None, bas=None, bit=None)
        dogru = dogrular(db, q["hedef"])
        satir = {"id": q["id"], "tur": q["tur"], "dogru_sayisi": len(dogru)}
        k = ara.kelime_ara(db, q["soru"], bos, havuz)
        an = ara.anlam_ara(db, q["soru"], bos, havuz)
        satir.update(kelime=olc(k, dogru), anlam=olc(an, dogru), hibrit=olc(rrf(k, an), dogru))
        if a.siralamalar:
            satir["siralamalar"] = {"dogru": sorted(dogru), "kelime": k, "anlam": an}
        if a.ekli:
            ek_k, _ = ara.ek_kelime_ara(db, q["soru"], bos, havuz)
            ek_a, _ = ara.ek_anlam_ara(db, q["soru"], bos, havuz)
            satir.update(ek=olc(rrf([], [], ek_k, ek_a), dogru),
                         hibrit_ekli=olc(rrf(k, an, ek_k, ek_a), dogru),
                         ek_kelime_aday=len(ek_k), ek_anlam_aday=len(ek_a))
            if a.siralamalar:
                satir["siralamalar"].update(ek_kelime=ek_k, ek_anlam=ek_a)
        if q["tur"] == "kisi":
            kk = ara.kelime_ara(db, q["soru"], ns, havuz)
            eski = eski_anlam(db, q["soru"], ns, havuz)
            yeni = ara.anlam_ara(db, q["soru"], ns, havuz)
            satir.update(kisi_eski_anlam=olc(eski, dogru), kisi_yeni_anlam=olc(yeni, dogru),
                         kisi_eski_hibrit=olc(rrf(kk, eski), dogru),
                         kisi_yeni_hibrit=olc(rrf(kk, yeni), dogru),
                         kisi_eski_aday=len(eski), kisi_yeni_aday=len(yeni))
            if a.ekli:
                ek_k, _ = ara.ek_kelime_ara(db, q["soru"], ns, havuz)
                ek_a, _ = ara.ek_anlam_ara(db, q["soru"], ns, havuz)
                satir["kisi_hibrit_ekli"] = olc(rrf(kk, yeni, ek_k, ek_a), dogru)
                if a.siralamalar:
                    satir["siralamalar"]["kisi"] = {"kelime": kk, "anlam": yeni, "ek_kelime": ek_k, "ek_anlam": ek_a}
        sonuc["sorular"].append(satir)
        print(q["id"], {x: satir[x] for x in satir if x not in ("id", "siralamalar")}, flush=True)

    print(f"\nKoleksiyon {sonuc['koleksiyon']}, {len(veri['sorular'])} soru")
    for tur in ("kelime", "anlam", None):
        grup = [s for s in sonuc["sorular"] if tur is None or s["tur"] == tur]
        etiket = tur or "tümü"
        for yontem in (("kelime", "anlam", "hibrit", "ek", "hibrit_ekli") if a.ekli else
                       ("kelime", "anlam", "hibrit")):
            print(f"  [{etiket:6}] {yontem:6}  {ozet([s[yontem] for s in grup])}")
    kisi = [s for s in sonuc["sorular"] if s["tur"] == "kisi"]
    if kisi:
        for y in ("kisi_eski_anlam", "kisi_yeni_anlam", "kisi_eski_hibrit", "kisi_yeni_hibrit"):
            print(f"  [kişi  ] {y:17} {ozet([s[y] for s in kisi])}")
        print(f"  [kişi  ] anlamsal aday sayısı eski {sum(s['kisi_eski_aday'] for s in kisi)} / "
              f"yeni {sum(s['kisi_yeni_aday'] for s in kisi)}")
        if a.ekli:
            print(f"  [kişi  ] hibrit_ekli {ozet([s['kisi_hibrit_ekli'] for s in kisi])}")
    if a.json:
        json.dump(sonuc, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
