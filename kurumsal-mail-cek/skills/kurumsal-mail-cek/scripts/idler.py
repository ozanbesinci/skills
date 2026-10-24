"""Sayfa JSON'undan sira_no + mesaj id ciftlerini basar (ajan baglamina
sadece bunlar girsin diye). mail_yaz.py ile AYNI siralama ve ayni numara
formulu kullanilir: value dizisi sirasi, baslangic_sira'dan itibaren."""
import argparse, io, json, sys

ap = argparse.ArgumentParser()
ap.add_argument("--sayfa", required=True)
ap.add_argument("--ay-onek", required=True)
ap.add_argument("--baslangic-sira", type=int, required=True)
a = ap.parse_args()

with io.open(a.sayfa, encoding="utf-8") as f:
    d = json.load(f)
kayitlar = d.get("value", d) if isinstance(d, dict) else d
n = a.baslangic_sira - 1
for k in kayitlar:
    n += 1
    sys.stdout.write("{0}-{1:05d} {2}\n".format(a.ay_onek, n, k.get("id") or ""))
sys.stdout.write("# adet={0} son_sira={1}-{2:05d} nextLink={3}\n".format(
    len(kayitlar), a.ay_onek, n,
    "var" if isinstance(d, dict) and "@odata.nextLink" in d else "yok"))
