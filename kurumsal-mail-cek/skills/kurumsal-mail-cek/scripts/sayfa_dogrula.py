"""Parse ONCESI ad kontrolu.

Bir sayfanin .eml dosyalari beklenen adlarla mi inmis, ona bakar. Indirme
ajanlari iki kez yanlis adlandirdi (onek atlama, hane sayisi, yanlis
baslangic) ve hata ancak mail_yaz.py "ham .eml bulunamadi" dediginde
gorunur oldu. Bu script hatayi parse'tan ONCE yakalar.

Cikti tek satir JSON: {"durum": "TAMAM"|"EKSIK"|"HATALI_AD", ...}
"""
import argparse, io, json, os, re, sys

ap = argparse.ArgumentParser()
ap.add_argument("--kosu", required=True)
ap.add_argument("--sayfa", required=True)
ap.add_argument("--ay-onek", required=True)
ap.add_argument("--baslangic-sira", type=int, required=True)
a = ap.parse_args()

with io.open(a.sayfa, encoding="utf-8") as f:
    d = json.load(f)
adet = len(d.get("value", d) if isinstance(d, dict) else d)

beklenen = ["{0}-{1:05d}.eml".format(a.ay_onek, a.baslangic_sira + i)
            for i in range(adet)]
ham_dir = os.path.join(a.kosu, "ham")
mevcut = set(os.listdir(ham_dir)) if os.path.isdir(ham_dir) else set()

eksik = [x for x in beklenen if x not in mevcut]
fazla = sorted(mevcut - set(beklenen))
bos = [x for x in beklenen
       if x in mevcut and os.path.getsize(os.path.join(ham_dir, x)) == 0]

if fazla:
    durum = "HATALI_AD"
elif eksik or bos:
    durum = "EKSIK"
else:
    durum = "TAMAM"

print(json.dumps({
    "durum": durum,
    "beklenen_adet": adet,
    "eksik_adet": len(eksik),
    "eksik": eksik[:20],
    "bos_byte": bos[:20],
    "beklenmeyen_ad": fazla[:20],
    "ipucu": ("ham/ icinde beklenmeyen adlar var - yanlis adlandirdin; "
              "adlari duzelt, PARSE ETME" if durum == "HATALI_AD" else
              "eksikleri indir, sonra parse et" if durum == "EKSIK" else
              "parse edebilirsin"),
}, ensure_ascii=False))
sys.exit(0 if durum == "TAMAM" else 1)
