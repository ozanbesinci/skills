#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kontrol.py — kurumsal-mail-cek skill'inin bagimsiz dogrulama ayagi.

Bir kosu klasorunu tarar ve sessiz eksikligi arar. Yorum yapmaz, sayar:
karari kontrol ajani verir.

Kullanim:
  python kontrol.py --kosu <kosu_klasoru>
                    [--beklenen beklenen.json]
                    [--baslangic 2026-07-01] [--bitis 2026-07-31]

beklenen.json bicimi (sayim adiminda uretilir):
  {"Arsiv\\01_Tedarikciler": 218, "Gonderilmis Ogeler": 197}

Cikti (stdout, JSON):
  {"hukum":"GECTI|BASARISIZ", "bulgular":[...], "sayilar":{...}}

Yan urun:
  <kosu>/_mevcut_idler.txt  — CSV'de kayitli mesaj_id listesi.
  Onarim ajani bunu Graph listesiyle karsilastirip eksigi bulur.
"""

import archive_contract as contract
import email
import email.policy
import argparse
import csv
import json
import os
import re
import sys
from collections import Counter

CSV_AYIRICI = ";"
CSV_KODLAMA = "utf-8-sig"

MAIL_KOLON_SAYISI = 39  # mail_yaz.py MAIL_KOLONLAR uzunlugu
EK_KOLON_SAYISI = 9

KANIT_GEREKTIREN_UYARILAR = {
    "metin_nul_kirpildi", "kaynak_replacement", "metin_fallback",
    "metin_cozulemeyen",
    "kaynakta_bos_ek", "imzali_mime",
}


def csv_oku(yol):
    """CSV'yi okur; (satirlar, bulgular) dondurur."""
    bulgular = []
    if not os.path.exists(yol):
        return None, ["{0} yok".format(os.path.basename(yol))]

    # BOM kontrolu: Excel Turkce karakterleri BOM olmadan bozuk gosterir
    with open(yol, "rb") as f:
        ilk = f.read(3)
    if ilk != b"\xef\xbb\xbf":
        bulgular.append(
            "{0}: UTF-8 BOM yok — Excel Turkce karakterleri bozuk gosterir"
            .format(os.path.basename(yol)))

    with open(yol, "r", encoding=CSV_KODLAMA, newline="") as f:
        ornek = f.readline()
        if CSV_AYIRICI not in ornek:
            bulgular.append(
                "{0}: baslik satirinda ';' ayirici yok"
                .format(os.path.basename(yol)))
        f.seek(0)
        okuyucu = csv.DictReader(f, delimiter=CSV_AYIRICI)
        satirlar = list(okuyucu)
    return satirlar, bulgular


def satir_uzunluk_kontrol(yol, beklenen_kolon, etiket):
    """Ham satirlarda kolon sayisi tutarliligi. Govdedeki ';' satiri bolmus mu?"""
    bulgular = []
    if not os.path.exists(yol):
        return bulgular
    with open(yol, "r", encoding=CSV_KODLAMA, newline="") as f:
        for i, satir in enumerate(csv.reader(f, delimiter=CSV_AYIRICI), start=1):
            if not satir:
                continue
            if len(satir) != beklenen_kolon:
                bulgular.append(
                    "{0} satir {1}: kolon sayisi {2}, beklenen {3}"
                    .format(etiket, i, len(satir), beklenen_kolon))
            if len(bulgular) >= 20:
                bulgular.append("{0}: kolon hatalari 20'den fazla, kesildi"
                                .format(etiket))
                break
    return bulgular


def govde_metin_sorunlari(yol):
    """UTF-8 metin govdede NUL/U+FFFD sayar; icerigi disari basmaz."""
    nul = replacement = 0
    try:
        with open(yol, "r", encoding="utf-8", errors="strict") as f:
            while True:
                parca = f.read(1024 * 1024)
                if not parca:
                    break
                nul += parca.count("\x00")
                replacement += parca.count("\ufffd")
    except UnicodeDecodeError:
        return 0, 0, "UTF-8 decode hatasi"
    return nul, replacement, ""


def uyari_kaniti(kosu, kayit):
    rel = (kayit.get("ham_dosya") or "").strip()
    if not rel:
        return False
    kok = os.path.normcase(os.path.abspath(kosu))
    tam = os.path.normcase(os.path.abspath(os.path.join(kosu, rel)))
    try:
        if os.path.commonpath([kok, tam]) != kok:
            return False
    except ValueError:
        return False
    try:
        tam = str(contract.inside(kosu, rel))
    except ValueError:
        return False
    if not os.path.isfile(tam) or os.path.getsize(tam) == 0:
        return False
    try:
        if not kayit.get("ham_sha256") or contract.digest(tam) != kayit["ham_sha256"]:
            return False
        with open(tam, "rb") as handle:
            msg = email.message_from_bytes(handle.read(), policy=email.policy.default)
        if not msg.keys() or msg.defects:
            return False
        mid = (msg.get("Message-ID") or "").strip()
        if mid != (kayit.get("internet_mesaj_id") or "").strip():
            return False
        from mail_yaz import govde_ve_ekler
        body, _, attachments, _, _, state = govde_ve_ekler(msg)
        kind = kayit.get("tur")
        if kind == "kaynakta_bos_ek":
            empty_names = [name for name, _, data, embedded in attachments if not embedded and not data]
            if sorted(empty_names) != sorted(str(kayit.get("detay", "")).split(" | ")):
                return False
            count = len(empty_names)
        elif kind == "imzali_mime":
            count = int(any(p.get_content_type() in ("multipart/signed", "application/pkcs7-signature", "application/x-pkcs7-signature") for p in msg.walk()))
        else:
            count = state.get(kind, 0)
        return count == int(kayit.get("adet", 0)) and count > 0
    except (OSError, ValueError, TypeError, KeyError):
        return False


def pozitif_tam_sayi(deger, varsayilan=0):
    try:
        sayi = int(deger)
    except (TypeError, ValueError):
        return varsayilan
    return sayi if sayi > 0 else varsayilan


# Konsol Turkce karakterleri bozmasin: Windows'ta stdout cp1254/cp437
# olabiliyor, o zaman ciktidaki 'Arsiv' gibi adlar bozuk okunur.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser(description="Kosu klasorunu bagimsiz dogrula")
    ap.add_argument("--kosu", required=True)
    ap.add_argument("--beklenen", help="Sayim adiminda uretilen JSON")
    ap.add_argument("--baslangic", help="YYYY-MM-DD")
    ap.add_argument("--bitis", help="YYYY-MM-DD")
    a = ap.parse_args()

    kosu = a.kosu
    if not os.path.isdir(kosu):
        raise SystemExit("kosu klasoru yok: " + kosu)

    bulgular = []
    uyarilar = []
    sayilar = {}

    # ---------------------------------------------------------------- mailler
    mail_yolu = os.path.join(kosu, "mailler.csv")
    mailler, b = csv_oku(mail_yolu)
    bulgular.extend(b)
    if mailler is None:
        print(json.dumps({"hukum": "BASARISIZ", "bulgular": bulgular,
                          "uyarilar": uyarilar, "sayilar": {}},
                         ensure_ascii=False))
        return 0

    sayilar["mail_satiri"] = len(mailler)
    bulgular.extend(satir_uzunluk_kontrol(mail_yolu, MAIL_KOLON_SAYISI,
                                          "mailler.csv"))

    # ---------------------------------------- kaynak anomalisi / kanit kayitlari
    uyari_kayit = []
    uyari_yolu = os.path.join(kosu, "_uyarilar.json")
    if os.path.isfile(uyari_yolu):
        try:
            with open(uyari_yolu, "r", encoding="utf-8") as f:
                uyari_kayit = json.load(f)
            if not isinstance(uyari_kayit, list):
                raise ValueError("liste degil")
        except Exception as e:
            bulgular.append("_uyarilar.json okunamadi ({0})".format(
                type(e).__name__))
            uyari_kayit = []

    mail_index = {r.get("sira_no"): r for r in mailler}
    # Dışarı yönlenen CSV yolları hiçbir dosya açılmadan reddedilir.
    for row in mailler:
        for field in ("govde_dosya", "basliklar_dosya", "ek_klasoru"):
            if row.get(field):
                try:
                    contract.inside(kosu, row[field])
                except ValueError:
                    print(json.dumps(dict(hukum="BASARISIZ", bulgular=["Kök dışı CSV yolu"], uyarilar=[], sayilar={}), ensure_ascii=False))
                    return 0
    uyari_indeksi = {}
    for kayit in uyari_kayit:
        if not isinstance(kayit, dict):
            bulgular.append("_uyarilar.json icinde nesne olmayan kayit")
            continue
        sira = (kayit.get("sira_no") or "").strip()
        tur = (kayit.get("tur") or "").strip()
        if not sira or not tur:
            bulgular.append("_uyarilar.json icinde sira_no/tur bos")
            continue
        expected_row = mail_index.get(sira)
        if tur in KANIT_GEREKTIREN_UYARILAR and expected_row is not None:
            if (kayit.get("mesaj_id", "") != expected_row.get("mesaj_id", "") or
                kayit.get("internet_mesaj_id", "") != expected_row.get("internet_mesaj_id", "")):
                bulgular.append(sira + ": uyarı kanıtı CSV kimliğiyle eşleşmiyor")
        uyari_indeksi.setdefault(sira, {}).setdefault(tur, []).append(kayit)
        if tur in KANIT_GEREKTIREN_UYARILAR and not uyari_kaniti(kosu, kayit):
            bulgular.append(
                "{0}: {1} uyarisi var ama ham EML kaniti yok/0 byte"
                .format(sira, tur))
    sayilar["uyari_kaydi"] = len(uyari_kayit)

    # ---------------------------------------------------- klasor bazli sayilar
    klasor_sayilari = {}
    for s in mailler:
        k = (s.get("klasor_yolu") or "").strip()
        klasor_sayilari[k] = klasor_sayilari.get(k, 0) + 1
    sayilar["klasor_sayilari"] = klasor_sayilari

    # Kapsam disi kalanlar (takvim ogeleri) sayima girer ama CSV'ye girmez.
    # Mahsup edilmezse her biri "eksik mail" gibi gorunur.
    atlanan_sayilari = {}
    atlanan_kayitlar = []
    atlanan_yolu = os.path.join(kosu, "_atlanan.json")
    if os.path.isfile(atlanan_yolu):
        try:
            with open(atlanan_yolu, "r", encoding="utf-8") as f:
                atlanan_kayitlar = json.load(f)
                if not isinstance(atlanan_kayitlar, list):
                    raise ValueError("liste degil")
                for kayit in atlanan_kayitlar:
                    k = (kayit.get("klasor_yolu") or "").strip()
                    atlanan_sayilari[k] = atlanan_sayilari.get(k, 0) + 1
        except Exception as e:
            bulgular.append("_atlanan.json okunamadi ({0})".format(
                type(e).__name__))
    sayilar["atlanan"] = sum(atlanan_sayilari.values())

    # Aylik/artimli kosuda Graph'in o an gordugu kimlikler kaydedilir. Yerel arsiv
    # append-only'dir: kaynakta sonradan tasinan/silinen eski kayitlar korunur, ama
    # kaynakta bulunan her kaydin yerelde olmasi zorunludur.
    yerel_id_listesi = [
        (s.get("mesaj_id") or "").strip() for s in mailler
        if (s.get("mesaj_id") or "").strip()
    ] + [
        (s.get("mesaj_id") or "").strip() for s in atlanan_kayitlar
        if isinstance(s, dict) and (s.get("mesaj_id") or "").strip()
    ]
    tekrar_idler = sorted(
        message_id for message_id, count in Counter(yerel_id_listesi).items()
        if count > 1
    )
    if tekrar_idler:
        bulgular.append(
            "ayni Graph mesaj_id ile tekrar eden {0} yerel kayit (ilk 10: {1})"
            .format(len(tekrar_idler), tekrar_idler[:10]))
    yerel_idler = set(yerel_id_listesi)
    sayilar["yerel_mesaj_id"] = len(yerel_idler)

    kaynak_yolu = os.path.join(kosu, "_kaynak_idler.json")
    kaynak_manifesti_var = os.path.isfile(kaynak_yolu)
    if kaynak_manifesti_var:
        try:
            with open(kaynak_yolu, "r", encoding="utf-8") as f:
                kaynak_ham = json.load(f)
            if not isinstance(kaynak_ham, dict):
                raise ValueError("nesne degil")
            kaynak_idler = set()
            for klasor, kimlikler in kaynak_ham.items():
                if not isinstance(kimlikler, list):
                    raise ValueError(str(klasor) + " liste degil")
                kaynak_idler.update(str(k).strip() for k in kimlikler if str(k).strip())
            eksik_kaynak = sorted(kaynak_idler - yerel_idler)
            if eksik_kaynak:
                bulgular.append(
                    "canli kaynak taramasinda bulunan {0} mesaj yerelde yok "
                    "(ilk 10: {1})".format(len(eksik_kaynak), eksik_kaynak[:10]))
            sayilar["kaynak_mesaj_id"] = len(kaynak_idler)
            sayilar["kaynakta_olmayip_yerelde_korunan"] = len(
                yerel_idler - kaynak_idler)
        except Exception as e:
            bulgular.append("_kaynak_idler.json okunamadi ({0})".format(
                type(e).__name__))

    if (not kaynak_manifesti_var and a.beklenen
            and os.path.isfile(a.beklenen)):
        with open(a.beklenen, "r", encoding="utf-8") as f:
            beklenen = json.load(f)
        for klasor, adet in beklenen.items():
            gercek = klasor_sayilari.get(klasor, 0)
            atlanan = atlanan_sayilari.get(klasor, 0)
            if gercek + atlanan != adet:
                fark = adet - gercek - atlanan
                bulgular.append(
                    "{0}: sayimda {1}, CSV'de {2}, kapsam disi {3} "
                    "-> {4} mail {5}"
                    .format(klasor, adet, gercek, atlanan, abs(fark),
                            "eksik" if fark > 0 else "fazla"))
        for klasor in klasor_sayilari:
            if klasor and klasor not in beklenen:
                bulgular.append(
                    "{0}: sayimda yok ama CSV'de {1} mail var — kapsam disi klasor?"
                    .format(klasor, klasor_sayilari[klasor]))

    # -------------------------------------------------------- sira numaralari
    siralar = []
    for s in mailler:
        m = re.match(r"^(\d{6})-(\d{5})$", (s.get("sira_no") or "").strip())
        if m:
            siralar.append((m.group(1), int(m.group(2))))
        else:
            bulgular.append("gecersiz sira_no: '{0}'".format(s.get("sira_no")))
    # Kapsam disi atlanan mailler kendi sira numarasini tuketir; o numaralar
    # CSV'de yoktur ama bosluk sayilmaz.
    atlanan_siralar = set()
    if os.path.isfile(os.path.join(kosu, "_atlanan.json")):
        try:
            with open(os.path.join(kosu, "_atlanan.json"), "r",
                      encoding="utf-8") as f:
                for kayit in json.load(f):
                    m = re.match(r"^(\d{6})-(\d{5})$",
                                 (kayit.get("sira_no") or "").strip())
                    if m:
                        atlanan_siralar.add((m.group(1), int(m.group(2))))
        except Exception:
            pass

    for onek in set(o for o, _ in siralar):
        nums = sorted(n for o, n in siralar if o == onek)
        atlanan_num = set(n for o, n in atlanan_siralar if o == onek)
        tekrar = {x for x, count in Counter(nums).items() if count > 1}
        if tekrar:
            bulgular.append("{0}: tekrar eden sira numarasi {1}".format(
                onek, sorted(tekrar)[:10]))
        if nums:
            var = set(nums) | atlanan_num
            eksik = [n for n in range(nums[0], nums[-1] + 1) if n not in var]
            if eksik:
                bulgular.append(
                    "{0}: sira numarasinda {1} bosluk (ilk 10: {2})"
                    .format(onek, len(eksik), eksik[:10]))

    # ----------------------------------------------------- govde dosyalari
    govde_beklenen = set()
    baslik_beklenen = set()
    govde_nul = govde_replacement = 0
    kanitli_replacement_mail = 0
    for s in mailler:
        baslik_rel = (s.get("basliklar_dosya") or "").strip()
        if not baslik_rel:
            bulgular.append("{0}: basliklar_dosya bos".format(s.get("sira_no")))
        else:
            baslik_tam = os.path.join(kosu, baslik_rel)
            baslik_beklenen.add(os.path.normcase(os.path.abspath(baslik_tam)))
            if not os.path.exists(baslik_tam):
                bulgular.append("{0}: baslik dosyasi diskte yok ({1})".format(
                    s.get("sira_no"), baslik_rel))
            elif os.path.getsize(baslik_tam) == 0:
                bulgular.append("{0}: baslik dosyasi 0 byte ({1})".format(
                    s.get("sira_no"), baslik_rel))
        rel = (s.get("govde_dosya") or "").strip()
        if not rel:
            bulgular.append("{0}: govde_dosya bos".format(s.get("sira_no")))
            continue
        tam = os.path.join(kosu, rel)
        govde_beklenen.add(os.path.normcase(os.path.abspath(tam)))
        if not os.path.exists(tam):
            bulgular.append("{0}: govde dosyasi diskte yok ({1})".format(
                s.get("sira_no"), rel))
        elif os.path.getsize(tam) == 0:
            bulgular.append("{0}: govde dosyasi 0 byte ({1})".format(
                s.get("sira_no"), rel))
        elif os.path.splitext(tam)[1].lower() == ".txt":
            nul, replacement, metin_hatasi = govde_metin_sorunlari(tam)
            govde_nul += nul
            govde_replacement += replacement
            if metin_hatasi:
                bulgular.append("{0}: govde {1}".format(
                    s.get("sira_no"), metin_hatasi))
            if nul:
                bulgular.append("{0}: govdede {1} NUL karakteri".format(
                    s.get("sira_no"), nul))
            if replacement:
                sira = (s.get("sira_no") or "").strip()
                kaynak_kayitlari = uyari_indeksi.get(sira, {}).get(
                    "kaynak_replacement", [])
                kanitli_adet = sum(
                    pozitif_tam_sayi(k.get("adet"), 1)
                    for k in kaynak_kayitlari if uyari_kaniti(kosu, k)
                )
                if kanitli_adet >= replacement:
                    kanitli_replacement_mail += 1
                else:
                    bulgular.append(
                        "{0}: govdede {1} U+FFFD var, kanitli kaynak adedi {2}"
                        .format(sira, replacement, kanitli_adet))

    d_govde = os.path.join(kosu, "govdeler")
    oksuz = 0
    if os.path.isdir(d_govde):
        for ad in os.listdir(d_govde):
            tam = os.path.abspath(os.path.join(d_govde, ad))
            if os.path.isfile(tam) and os.path.normcase(tam) not in govde_beklenen:
                oksuz += 1
    if oksuz:
        bulgular.append(
            "govdeler/ icinde CSV'de karsiligi olmayan {0} dosya".format(oksuz))
    sayilar["oksuz_govde"] = oksuz
    sayilar["govde_nul"] = govde_nul
    sayilar["govde_replacement"] = govde_replacement
    sayilar["kanitli_replacement_mail"] = kanitli_replacement_mail
    d_baslik = os.path.join(kosu, "basliklar")
    oksuz_baslik = 0
    if os.path.isdir(d_baslik):
        for ad in os.listdir(d_baslik):
            tam = os.path.abspath(os.path.join(d_baslik, ad))
            if os.path.isfile(tam) and os.path.normcase(tam) not in baslik_beklenen:
                oksuz_baslik += 1
    if oksuz_baslik:
        bulgular.append(
            "basliklar/ icinde CSV'de karsiligi olmayan {0} dosya".format(
                oksuz_baslik))
    sayilar["oksuz_baslik"] = oksuz_baslik
    if kanitli_replacement_mail:
        uyarilar.append(
            "{0} mailin kaynaginda U+FFFD var; ham EML kaniti saklandi"
            .format(kanitli_replacement_mail))

    # ------------------------------------------------------------------ ekler
    ek_yolu = os.path.join(kosu, "ekler.csv")
    ekler, b = csv_oku(ek_yolu)
    if ekler is None:
        sayilar["ek_satiri"] = 0
        if any((s.get("ek_var_mi") or "") == "evet" for s in mailler):
            bulgular.append("ekler.csv yok ama ekli mail var")
    else:
        bulgular.extend(b)
        bulgular.extend(satir_uzunluk_kontrol(ek_yolu, EK_KOLON_SAYISI,
                                              "ekler.csv"))
        sayilar["ek_satiri"] = len(ekler)
        inen = gomulu = kaynakta_bos = indirilen_gomulu = 0
        kaynakta_bos_sayilari = {}
        gercek_ek_sayilari = {}
        for e in ekler:
            if e.get("kaydedilen_yol"):
                try:
                    contract.inside(kosu, e["kaydedilen_yol"])
                except ValueError:
                    print(json.dumps(dict(hukum="BASARISIZ", bulgular=["Kök dışı ek yolu"], uyarilar=[], sayilar={}), ensure_ascii=False))
                    return 0
            if (e.get("gomulu_mu") or "") == "evet":
                gomulu += 1
                if (e.get("indirildi_mi") or "") == "evet":
                    indirilen_gomulu += 1
                    rel = (e.get("kaydedilen_yol") or "").strip()
                    tam = os.path.join(kosu, rel) if rel else ""
                    if not rel or not os.path.isfile(tam):
                        bulgular.append(
                            "{0}: indirilen gomulu gorsel diskte yok ({1})"
                            .format(e.get("sira_no"), rel or e.get("ek_adi")))
                    elif os.path.getsize(tam) != int(e.get("boyut_byte") or 0):
                        bulgular.append(
                            "{0}: gomulu gorsel boyutu uyusmuyor ({1})"
                            .format(e.get("sira_no"), rel))
                continue
            sira = (e.get("sira_no") or "").strip()
            gercek_ek_sayilari[sira] = gercek_ek_sayilari.get(sira, 0) + 1
            try:
                beklenen_boyut = int(e.get("boyut_byte") or 0)
            except ValueError:
                beklenen_boyut = -1
                bulgular.append("{0}: ek boyut_byte gecersiz ({1})".format(
                    sira, e.get("ek_adi")))
            if (e.get("indirildi_mi") or "") != "evet":
                hata_metni = (e.get("hata") or "").strip()
                bos_kayitlari = uyari_indeksi.get(sira, {}).get(
                    "kaynakta_bos_ek", [])
                if (beklenen_boyut == 0 and hata_metni == "icerik bos"
                        and any(uyari_kaniti(kosu, k) for k in bos_kayitlari)):
                    kaynakta_bos += 1
                    kaynakta_bos_sayilari[sira] = (
                        kaynakta_bos_sayilari.get(sira, 0) + 1)
                    continue
                bulgular.append(
                    "{0}: gercek ek indirilmemis ({1}; hata={2})".format(
                        sira, e.get("ek_adi"), hata_metni or "yok"))
                continue
            inen += 1
            if (e.get("hata") or "").strip():
                bulgular.append(
                    "{0}: ek indirildi ama hata alani dolu ({1}: {2})".format(
                        sira, e.get("ek_adi"), e.get("hata")))
            rel = (e.get("kaydedilen_yol") or "").strip()
            if not rel:
                bulgular.append("{0}: ek indirildi ama yol bos ({1})".format(
                    e.get("sira_no"), e.get("ek_adi")))
                continue
            tam = os.path.join(kosu, rel)
            if not os.path.exists(tam):
                bulgular.append("{0}: ek diskte yok ({1})".format(
                    e.get("sira_no"), rel))
            elif os.path.getsize(tam) == 0:
                bulgular.append("{0}: ek 0 byte, indirme bozuk ({1})".format(
                    e.get("sira_no"), rel))
            elif beklenen_boyut >= 0 and os.path.getsize(tam) != beklenen_boyut:
                bulgular.append(
                    "{0}: ek boyutu uyusmuyor; CSV {1}, disk {2} byte ({3})"
                    .format(e.get("sira_no"), beklenen_boyut,
                            os.path.getsize(tam), rel))
        sayilar["inen_ek"] = inen
        sayilar["gomulu_ek"] = gomulu
        sayilar["indirilen_gomulu"] = indirilen_gomulu
        sayilar["kaynakta_bos_ek"] = kaynakta_bos
        if kaynakta_bos:
            uyarilar.append(
                "Kaynaktaki ham EML'de {0} gercek ek 0 byte; kanit saklandi"
                .format(kaynakta_bos))

        for sira, gercek_bos in kaynakta_bos_sayilari.items():
            kayitlar = uyari_indeksi.get(sira, {}).get("kaynakta_bos_ek", [])
            kanitli_bos = sum(
                pozitif_tam_sayi(k.get("adet"), 1)
                for k in kayitlar if uyari_kaniti(kosu, k)
            )
            if kanitli_bos != gercek_bos:
                bulgular.append(
                    "{0}: 0 byte ek satiri {1}, kanitli kaynak adedi {2}"
                    .format(sira, gercek_bos, kanitli_bos))

        for s in mailler:
            sira = (s.get("sira_no") or "").strip()
            try:
                beklenen_ek = int(s.get("ek_sayisi") or 0)
            except ValueError:
                bulgular.append("{0}: ek_sayisi gecersiz".format(sira))
                continue
            gercek_ek = gercek_ek_sayilari.get(sira, 0)
            if gercek_ek != beklenen_ek:
                bulgular.append(
                    "{0}: mail ek_sayisi {1}, ekler.csv gercek ek satiri {2}"
                    .format(sira, beklenen_ek, gercek_ek))

        # Hacim raporu: "tum ekler inecek" karari geregi ust sinir yok,
        # o yuzden ne kadar yer tuttugu gorunur olmali.
        inen_byte = gomulu_byte = 0
        en_buyuk = []
        for e in ekler:
            try:
                b = int(e.get("boyut_byte") or 0)
            except ValueError:
                b = 0
            if (e.get("gomulu_mu") or "") == "evet" and (e.get("indirildi_mi") or "") != "evet":
                gomulu_byte += b
            elif (e.get("indirildi_mi") or "") == "evet":
                inen_byte += b
                en_buyuk.append((b, e.get("ek_adi") or ""))
        sayilar["inen_ek_mb"] = round(inen_byte / 1048576.0, 1)
        sayilar["gomulu_atlanan_mb"] = round(gomulu_byte / 1048576.0, 1)
        en_buyuk.sort(reverse=True)
        sayilar["en_buyuk_ekler"] = [
            "{0} ({1:.1f} MB)".format(ad[:60], b / 1048576.0)
            for b, ad in en_buyuk[:5]
        ]

    # ------------------------------------------------------------- ham klasor
    d_ham = os.path.join(kosu, "ham")
    kalan = []
    if os.path.isdir(d_ham):
        kalan = [x for x in os.listdir(d_ham)
                 if os.path.isfile(os.path.join(d_ham, x))]
    sayilar["ham_kalan"] = len(kalan)
    if kalan:
        bulgular.append(
            "ham/ bos degil: {0} dosya parse edilememis (ilk 5: {1})"
            .format(len(kalan), kalan[:5]))

    # ------------------------------------------------------------ tarih siniri
    if a.baslangic and a.bitis:
        disari = 0
        for s in mailler:
            t = contract.record_date(s, csv_mode=True).strip()
            if not t:
                bulgular.append("{0}: tarih alani bos".format(s.get("sira_no")))
                continue
            gun = t[:10]
            if gun < a.baslangic or gun > a.bitis:
                disari += 1
                if disari <= 5:
                    bulgular.append(
                        "{0}: tarih araligi disinda ({1})".format(
                            s.get("sira_no"), gun))
        if disari > 5:
            bulgular.append("tarih araligi disinda toplam {0} mail".format(disari))
        sayilar["aralik_disi"] = disari

    # ---------------------------------------------------------------- kapsam
    gmail = sum(1 for s in mailler
                if "08_gmail" in (s.get("klasor_yolu") or "").lower())
    if gmail:
        bulgular.append("08_Gmail'den {0} mail sizmis — kapsam ihlali".format(gmail))

    takvim = sum(1 for s in mailler
                 if "ipm.schedule" in (s.get("oge_tipi") or "").lower())
    if takvim:
        bulgular.append("{0} takvim/toplanti ogesi CSV'ye girmis".format(takvim))

    # -------------------------------------------------------------- bilgi
    sayilar["mukerrer"] = sum(1 for s in mailler
                              if (s.get("mukerrer_mi") or "") == "evet")
    sayilar["sifreli"] = sum(1 for s in mailler
                             if (s.get("sifreli_mi") or "") == "evet")

    # ------------------------------------------- onarim icin mevcut id listesi
    id_yolu = os.path.join(kosu, "_mevcut_idler.txt")
    try:
        with open(id_yolu, "w", encoding="utf-8") as f:
            for s in mailler:
                mid = (s.get("internet_mesaj_id") or "").strip()
                gid = (s.get("mesaj_id") or "").strip()
                f.write("{0}\t{1}\n".format(gid, mid))
        sayilar["id_dosyasi"] = os.path.basename(id_yolu)
    except Exception as e:
        bulgular.append("_mevcut_idler.txt yazilamadi ({0})".format(
            type(e).__name__))

    # Bilgi nitelikli kaynak anomalilerini toplula.
    nul_kirpilan_mail = len([
        1 for sira in uyari_indeksi
        if uyari_indeksi[sira].get("metin_nul_kirpildi")
    ])
    fallback_mail = len([
        1 for sira in uyari_indeksi
        if uyari_indeksi[sira].get("metin_fallback")
    ])
    cozulmeyen_mail = len([
        1 for sira in uyari_indeksi
        if uyari_indeksi[sira].get("metin_cozulemeyen")
    ])
    sayilar["nul_kirpilan_mail"] = nul_kirpilan_mail
    sayilar["fallback_mail"] = fallback_mail
    sayilar["cozulemeyen_metin_mail"] = cozulmeyen_mail
    if nul_kirpilan_mail:
        uyarilar.append(
            "{0} mailde metin sonundaki NUL dolgusu guvenle kirpildi"
            .format(nul_kirpilan_mail))
    if fallback_mail:
        uyarilar.append(
            "{0} mailde beyan disi strict charset kullanildi; ham kanit saklandi"
            .format(fallback_mail))
    if cozulmeyen_mail:
        uyarilar.append(
            "{0} mailin metin parcasi cozulemedi; ham kanit saklandi"
            .format(cozulmeyen_mail))

    bulgular.extend(contract.integrity_errors(kosu))
    if os.path.exists(os.path.join(kosu, "_islem.json")):
        bulgular.append("Yarım kayıt işlem günlüğü var")
    try:
        state = contract.read_json(os.path.join(kosu, "_bekleyen.json"), [])
        if state:
            bulgular.append("Bekleyen aktarım kayıtları var")
    except (ValueError, TypeError):
        bulgular.append("Bekleyen aktarım JSON bozuk")
    if a.baslangic:
        prefix = a.baslangic[:7].replace("-", "")
        if any((s.get("sira_no") or "").split("-")[0] != prefix for s in mailler):
            bulgular.append("Sıra numarası hedef aya ait değil")
    hukum = "GECTI" if not bulgular else "BASARISIZ"
    print(json.dumps({"hukum": hukum, "bulgular": bulgular,
                      "uyarilar": uyarilar, "sayilar": sayilar},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
