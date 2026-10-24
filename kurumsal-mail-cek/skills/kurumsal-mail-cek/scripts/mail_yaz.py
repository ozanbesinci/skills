#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mail_yaz.py — kurumsal-mail-cek skill'inin yazma ayagi.

Bir sayfa metadata JSON'u + o sayfaya ait indirilmis .eml dosyalarini alir,
.eml'leri yerelde parse eder, mailler.csv / ekler.csv satirlarini yazar,
govdeleri ve ekleri diske cikarir, dogrular, sonra .eml'i siler.

Mail icerigi ajanin baglamina hic girmez: script tek satir ozet dondurur.

Kullanim:
  python mail_yaz.py --sayfa <sayfa.json> --kosu <kosu_klasoru>
                     --klasor-yolu "Arsiv\\01_Tedarikciler"
                     --ay-onek 202607 --baslangic-sira 1

Cikti (stdout, tek satir JSON):
  {"islenen":50,"ek":14,"atlanan":1,"hata":0,"son_sira":"202607-00050","notlar":[]}
"""

import archive_contract as contract
from pathlib import Path
import argparse
import base64
import csv
import datetime as dt
import email
import email.policy
import email.utils
import html
import json
import os
import re
import shutil
import sys
import unicodedata
from email.header import decode_header, make_header
from html.parser import HTMLParser

# --------------------------------------------------------------------------
# CSV semasi
# --------------------------------------------------------------------------

MAIL_KOLONLAR = [
    "sira_no", "klasor_yolu", "oge_tipi", "konu",
    "gonderen_ad", "gonderen_mail", "sender_ad", "sender_mail",
    "kime", "cc", "bcc", "yanit_adresi",
    "alinma_zamani", "gonderilme_zamani", "olusturma", "son_degisiklik",
    "govde_onizleme", "govde_dosya", "govde_tipi",
    "ek_var_mi", "ek_sayisi", "ek_adlari", "ek_klasoru",
    "okundu_mu", "taslak_mi", "onem", "bayrak_durumu", "kategoriler",
    "yanit_zinciri_mi", "boyut_byte", "cikarim_sinifi",
    "mukerrer_mi", "sifreli_mi",
    "mesaj_id", "konusma_id", "konusma_index", "internet_mesaj_id",
    "web_link", "basliklar_dosya",
]

EK_KOLONLAR = [
    "sira_no", "mesaj_id", "ek_adi", "ek_tipi", "boyut_byte",
    "gomulu_mu", "indirildi_mi", "kaydedilen_yol", "hata",
]

CSV_AYIRICI = ";"
CSV_KODLAMA = "utf-8-sig"
COKLU_BIRLESTIRICI = " | "
ISTANBUL_TZ = dt.timezone(dt.timedelta(hours=3), name="Europe/Istanbul")

# Windows'ta yasak karakterler + kontrol karakterleri
YASAK = r'[<>:"/\\|?*\x00-\x1f]'

# Turkce buyuk/kucuk tuzagina dusmemek icin acik eslesme.
# str.lower()/upper() Turkce I/i ciftinde yanlis sonuc verir; slug'da
# donusum yerine dogrudan ASCII karsiligina esliyoruz.
TR_ASCII = {
    "ı": "i", "İ": "I", "ş": "s", "Ş": "S",
    "ğ": "g", "Ğ": "G", "ü": "u", "Ü": "U",
    "ö": "o", "Ö": "O", "ç": "c", "Ç": "C",
    "â": "a", "Â": "A", "î": "i", "Î": "I",
    "û": "u", "Û": "U",
}

# Gomulu imza gorseli suphesi
IMZA_DESEN = re.compile(
    r"^(image|logo|oledata|ole|spacer|pixel)[0-9_\-]*"
    r"\.(png|jpg|jpeg|gif|bmp|emz|wmz|emf|wmf)$", re.I)

# Bu boyutun uzerindeki bir gorsel imza logosu degil, gercek ektir.
# Imza logolari tipik olarak 1-50 KB; 200 KB comert bir ust sinir.
GOMULU_BOYUT_SINIRI = 200 * 1024

TAKVIM_TIPLERI = ("text/calendar", "application/ics")
SIFRELI_TIPLERI = ("application/pkcs7-mime", "application/x-pkcs7-mime")
IMZALI_TIPLERI = ("application/pkcs7-signature", "application/x-pkcs7-signature")


# --------------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------------

class HTMLMetin(HTMLParser):
    """HTML govdeyi duz metne cevirir. bs4 yok, stdlib ile."""

    ATLA = {"script", "style", "head", "meta", "link", "title"}
    BLOK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
            "table", "blockquote", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parcalar = []
        self._atla_derinlik = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.ATLA:
            self._atla_derinlik += 1
        elif tag in self.BLOK:
            self.parcalar.append("\n")

    def handle_endtag(self, tag):
        if tag in self.ATLA and self._atla_derinlik > 0:
            self._atla_derinlik -= 1
        elif tag in self.BLOK:
            self.parcalar.append("\n")

    def handle_data(self, veri):
        if self._atla_derinlik == 0:
            self.parcalar.append(veri)

    def metin(self):
        ham = "".join(self.parcalar)
        ham = html.unescape(ham)
        ham = ham.replace(" ", " ").replace("\r\n", "\n").replace("\r", "\n")
        ham = re.sub(r"[ \t]+", " ", ham)
        ham = re.sub(r"\n[ \t]+", "\n", ham)
        ham = re.sub(r"\n{3,}", "\n\n", ham)
        return ham.strip()


def html_to_metin(kaynak):
    p = HTMLMetin()
    try:
        p.feed(kaynak)
        p.close()
    except Exception:
        kaynak = re.sub(r"<[^>]+>", " ", kaynak)
        return re.sub(r"\s+", " ", html.unescape(kaynak)).strip()
    return p.metin()


def basligi_coz(deger):
    """MIME encoded-word basligini okunur metne cevirir."""
    if not deger:
        return ""
    try:
        return str(make_header(decode_header(str(deger)))).strip()
    except Exception:
        return str(deger).strip()


def ascii_slug(metin, uzunluk=60):
    """Dosya adi icin guvenli ASCII slug."""
    if not metin:
        return "konusuz"
    for tr, asc in TR_ASCII.items():
        metin = metin.replace(tr, asc)
    metin = re.sub(YASAK, " ", metin)
    metin = re.sub(r"[^\w\s.\-]", " ", metin, flags=re.ASCII)
    metin = re.sub(r"\s+", "-", metin.strip())
    metin = re.sub(r"-{2,}", "-", metin).strip("-.")
    if not metin:
        return "konusuz"
    return metin[:uzunluk].rstrip("-.") or "konusuz"


def dosya_adi_temizle(ad, yedek="ek"):
    """Ek dosya adini korur ama Windows'ta yasak olani ayiklar."""
    if not ad:
        return yedek
    # NFC: bazi istemciler 's' + birlesen cengel (U+0327) gibi ayrik
    # kombinasyonlar gonderiyor. Gorsel olarak 's' ile ayni ama farkli byte;
    # normalize edilmezse dosya adi aramada ve eslesmede tutmuyor.
    try:
        ad = unicodedata.normalize("NFC", str(ad))
    except Exception:
        ad = str(ad)
    ad = os.path.basename(ad.replace("\\", "/"))
    ad = re.sub(YASAK, "_", ad).strip(" .")
    if not ad:
        return yedek
    kok = ad.split(".")[0].upper()
    if kok in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)[1-9]", kok):
        ad = "_" + ad
    return ad[:120]


def ek_adini_coz(parca, tip):
    """
    Ek adini olabildigince saglam cikarir.

    get_filename() RFC 2231 parcali (filename*0*, filename*1*) basliklarda
    Turkce karakterli adlarin basini kirpabiliyor — kalibrasyonda
    "Disolar Enerji ...pdf" adi "olar Enerji ...pdf" olarak geldi. Bu yuzden
    ikinci kaynak olarak Content-Type'in name parametresine ve ham
    Content-Disposition basligina da bakip en uzun makul adi seciyoruz.
    """
    adaylar = []

    try:
        a = basligi_coz(parca.get_filename())
        if a:
            adaylar.append(a)
    except Exception:
        pass

    try:
        a = basligi_coz(parca.get_param("name", header="content-type"))
        if a:
            adaylar.append(a)
    except Exception:
        pass

    # Ham basliktan regex ile: RFC 2231 parcalarini birlestirmeye calismaz,
    # ama tek parcali duz filename="..." durumunu kurtarir.
    try:
        ham = str(parca.get("Content-Disposition") or "")
        m = re.search(r'filename\s*=\s*"([^"]+)"', ham)
        if not m:
            m = re.search(r"filename\s*=\s*([^;\r\n]+)", ham)
        if m:
            a = basligi_coz(m.group(1).strip().strip('"'))
            if a:
                adaylar.append(a)
    except Exception:
        pass

    adaylar = [a for a in adaylar if a and a.strip()]
    if adaylar:
        # En uzun aday genelde kirpilmamis olan
        return dosya_adi_temizle(max(adaylar, key=len))

    cid = (parca.get("Content-ID") or "").strip("<> ")
    uzanti = (tip or "application/octet-stream").split("/")[-1].split("+")[0]
    return dosya_adi_temizle(
        "{0}.{1}".format(cid, uzanti) if cid else "ek.{0}".format(uzanti))


def cakismasiz(yol):
    """Var olan dosyanin uzerine yazma: -2, -3 ... ekle."""
    if not os.path.exists(yol):
        return yol
    kok, uzanti = os.path.splitext(yol)
    n = 2
    while os.path.exists("{0}-{1}{2}".format(kok, n, uzanti)):
        n += 1
    return "{0}-{1}{2}".format(kok, n, uzanti)


def yol_sinirla(klasor, ad, limit=240):
    """Windows 260 karakter yol sinirina karsi ad kisaltma."""
    tam = os.path.join(klasor, ad)
    if len(tam) <= limit:
        return tam
    kok, uzanti = os.path.splitext(ad)
    pay = limit - len(klasor) - len(uzanti) - 2
    if pay < 12:
        pay = 12
    return os.path.join(klasor, kok[:pay] + uzanti)


def adres_listesi(msg, alan):
    """To/Cc/Bcc alanlarini 'Ad <mail>' listesi olarak birlestir."""
    ham = msg.get_all(alan)
    if not ham:
        return ""
    parcalar = []
    for h in ham:
        for adres in email.utils.getaddresses([str(h)]):
            ad, mail = basligi_coz(adres[0]), adres[1].strip()
            if not ad and not mail:
                continue
            parcalar.append("{0} <{1}>".format(ad, mail) if ad else mail)
    return COKLU_BIRLESTIRICI.join(parcalar)


def tek_adres(msg, alan):
    ham = msg.get(alan)
    if not ham:
        return "", ""
    ciftler = email.utils.getaddresses([str(ham)])
    if not ciftler:
        return "", ""
    ad, mail = ciftler[0]
    return basligi_coz(ad), mail.strip()


def zaman_bicim(deger):
    """Graph ISO zamanini Istanbul yerel saatinde 'YYYY-MM-DD HH:MM' yapar."""
    if not deger:
        return ""
    raw = str(deger).strip()
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ISTANBUL_TZ)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", raw)
        return "{0} {1}".format(m.group(1), m.group(2)) if m else raw


def eb(deger):
    """Bool -> evet/hayir"""
    if deger is True:
        return "evet"
    if deger is False:
        return "hayir"
    return ""


def hucre(deger):
    """CSV hucresini guvenli hale getir: satir sonu ve NUL bozmasin."""
    if deger is None:
        return ""
    s = str(deger)
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    s = s.replace("\x00", "")
    return s.strip()


def metin_parcasi_coz(parca, durum):
    """Bir MIME metin parcasini sessiz veri kaybi olmadan cozer.

    email.message.get_content(), charset belirtilmeyen bir parçada ASCII +
    replacement kullanabiliyor. Mart 2026 e-Arsiv maillerinde govde aslinda
    gecerli UTF-8 idi; charset yoktu ve sonuna NUL dolgusu eklenmisti. Bu
    yardimci transfer encoding'i byte'a cevirir, yalniz sondaki NUL dolgusunu
    ayiklar ve aday charset'leri strict modda dener.

    Kaynak byte'lar zaten U+FFFD tasiyorsa karakter uydurulmaz; durum kaydina
    islenir ve ham .eml kanit olarak korunur.
    """
    ham = parca.get_payload(decode=True)
    if ham is None:
        ham_deger = parca.get_payload()
        if isinstance(ham_deger, str):
            try:
                ham = ham_deger.encode("ascii", "strict")
            except UnicodeEncodeError as exc:
                durum["metin_cozulemeyen"] += 1
                raise UnicodeError("metin payload byte'a cevrilemedi") from exc
        else:
            ham = b""

    kirpilmis = ham.rstrip(b"\x00")
    nul_adedi = len(ham) - len(kirpilmis)
    if nul_adedi:
        durum["metin_nul_kirpildi"] += nul_adedi
    ham = kirpilmis

    adaylar = []

    def aday_ekle(ad):
        ad = (ad or "").strip()
        if ad and ad.casefold() not in [x.casefold() for x in adaylar]:
            adaylar.append(ad)

    beyan = parca.get_content_charset() or ""
    aday_ekle(beyan)
    if ham.startswith((b"\xff\xfe", b"\xfe\xff")):
        aday_ekle("utf-16")
    if ham.startswith(b"\xef\xbb\xbf"):
        aday_ekle("utf-8-sig")
    aday_ekle("utf-8")
    # Yalniz strict decode. Fallback secilirse ham EML ayrica korunur.
    aday_ekle("cp1254")
    aday_ekle("iso-8859-9")
    aday_ekle("cp1252")

    for kodlama in adaylar:
        try:
            metin = ham.decode(kodlama, "strict")
        except (UnicodeDecodeError, LookupError):
            continue
        if "\x00" in metin:
            # Metnin icindeki NUL dolgu degil; baska charset denenmeli.
            continue
        if "\ufffd" in metin:
            durum["kaynak_replacement"] += metin.count("\ufffd")
        beyan_norm = beyan.casefold().replace("_", "-")
        kodlama_norm = kodlama.casefold().replace("_", "-")
        if (beyan and kodlama_norm != beyan_norm
                and not (beyan_norm == "utf-8" and kodlama_norm == "utf-8-sig")):
            durum["metin_fallback"] += 1
            durum["fallback_kodlamalar"].add(kodlama)
        elif not beyan and kodlama_norm not in ("utf-8", "utf-8-sig"):
            durum["metin_fallback"] += 1
            durum["fallback_kodlamalar"].add(kodlama)
        return metin

    durum["metin_cozulemeyen"] += 1
    raise UnicodeError("MIME metin parcasi strict charset ile cozulemedi")


def ham_kanit_sakla(eml_yolu, sorunlu_dizin, sira):
    """Kaynak anomalisi olan mailin ham halini atomik olarak saklar."""
    os.makedirs(sorunlu_dizin, exist_ok=True)
    hedef = os.path.join(sorunlu_dizin, sira + ".eml")
    gecici = hedef + ".tmp"
    shutil.copyfile(eml_yolu, gecici)
    os.replace(gecici, hedef)
    return hedef


def csv_ekle(yol, kolonlar, satirlar):
    """CSV'ye append; dosya yoksa basligi da yazar."""
    yeni = not os.path.exists(yol)
    with open(yol, "a", encoding=CSV_KODLAMA, newline="") as f:
        y = csv.DictWriter(f, fieldnames=kolonlar, delimiter=CSV_AYIRICI,
                           quoting=csv.QUOTE_MINIMAL, extrasaction="ignore")
        if yeni:
            y.writeheader()
        for s in satirlar:
            y.writerow(s)


# --------------------------------------------------------------------------
# .eml parse
# --------------------------------------------------------------------------

def _parca_gez(parca, duz_parcalar, html_parcalar, ekler, durum, ekli_sayac):
    """
    MIME agacini ozyinelemeli gezer.

    msg.walk() KULLANILMIYOR: walk() message/rfc822 konteynerinin de icine
    iniyor. Bu iki hataya yol aciyordu — ekli mail hic ek olarak kaydedilmiyor,
    ustelik icindeki text/plain dis mailin govdesine karisiyordu. Burada
    message/rfc822'da duruyoruz: ek olarak alip alt agacina inmiyoruz.
    """
    tip = (parca.get_content_type() or "").lower()
    disposition = (parca.get_content_disposition() or "").lower()
    ad_ham = parca.get_filename()

    # --- Mail icinde mail: ek olarak al, ICINE INME
    if tip == "message/rfc822":
        ic = parca.get_payload(0)
        if (parca.get("Content-Transfer-Encoding") or "").lower() == "base64":
            # MAPI exporter message/rfc822 ekini base64 ile sarar. Python'un
            # email parseri bunu otomatik cozmeyip yalniz base64 metni verir.
            ham = ic.get_payload() if ic.keys() else ic.as_bytes()
            if isinstance(ham, str):
                ham = ham.encode("ascii", "strict")
            bayt = base64.b64decode(b"".join(ham.split()), validate=True)
        else:
            bayt = ic.as_bytes()
        ekli_sayac[0] += 1
        ad = dosya_adi_temizle(
            basligi_coz(ad_ham) or "ekli-mail-{0}".format(ekli_sayac[0]))
        if bayt.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            if ad.lower().endswith(".eml"):
                ad = ad[:-4]
            if not ad.lower().endswith(".msg"):
                ad += ".msg"
            mime = "application/vnd.ms-outlook"
        else:
            if not ad.lower().endswith(".eml"):
                ad += ".eml"
            mime = "message/rfc822"
        ekler.append((ad, mime, bayt, False))
        return

    if parca.is_multipart():
        yuk = parca.get_payload()
        if isinstance(yuk, list):
            for alt in yuk:
                _parca_gez(alt, duz_parcalar, html_parcalar, ekler,
                           durum, ekli_sayac)
        return

    # --- Yaprak parcalar
    if tip in SIFRELI_TIPLERI:
        durum["sifreli"] = True
        return
    if tip in IMZALI_TIPLERI:
        return
    # Takvim eki normal maili kapsam dışı yapmaz; ana öğe aşağıda sınıflanır.

    gomulu = disposition == "inline" or bool(parca.get("Content-ID"))
    ek_mi = disposition == "attachment" or bool(ad_ham)

    if not ek_mi and tip == "text/plain":
        try:
            duz_parcalar.append(metin_parcasi_coz(parca, durum))
        except UnicodeError:
            pass
        return

    if not ek_mi and tip == "text/html":
        try:
            html_parcalar.append(metin_parcasi_coz(parca, durum))
        except UnicodeError:
            pass
        return

    bayt = parca.get_payload(decode=True) or b""
    ad = ek_adini_coz(parca, tip)

    # --- Gomulu mu, gercek ek mi?
    #
    # ONEMLI: "inline veya Content-ID varsa gomuludur" demek YETMEZ.
    # Kalibrasyonda Mac Mail'den gelen bir mailde uc gercek PDF (8,9 MB)
    # Content-Disposition: inline tasiyordu ve bu kural onlari indirmeden
    # atliyordu — script de "0 hata" diyordu. Sessiz veri kaybi.
    #
    # Dogru kriter: yalnizca KUCUK GORSELLER gomulu sayilir. PDF, office
    # dosyasi, zip asla gomulu degildir; kullanicinin gonderdigi buyuk bir
    # fotoğraf da gercek ektir.
    gomulu = False
    if disposition == "attachment":
        # Gonderen "attachment" demisse gercek ektir, Content-ID tasisa bile.
        # Kalibrasyondaki uc PDF tam boyleydi: attachment + Content-ID.
        gomulu = False
    elif (tip.startswith("image/") and len(bayt) < GOMULU_BOYUT_SINIRI
          and (disposition == "inline" or bool(parca.get("Content-ID")))):
        gomulu = True

    ekler.append((ad, tip, bayt, gomulu))


def govde_ve_ekler(msg):
    """
    .eml'i gezip govde metnini, govde tipini ve ek listesini cikarir.
    Ekler: (ad, tip, bayt, gomulu_mu) demetleri.
    """
    duz_parcalar, html_parcalar, ekler = [], [], []
    durum = {
        "sifreli": False,
        "takvim": False,
        "metin_nul_kirpildi": 0,
        "kaynak_replacement": 0,
        "metin_fallback": 0,
        "fallback_kodlamalar": set(),
        "metin_cozulemeyen": 0,
    }
    _parca_gez(msg, duz_parcalar, html_parcalar, ekler, durum, [0])
    sifreli = durum["sifreli"]
    takvim = msg.get_content_type().lower() in TAKVIM_TIPLERI

    duz = "\n\n".join(p.strip() for p in duz_parcalar if p and p.strip())
    zengin = html_to_metin("\n".join(html_parcalar)) if html_parcalar else ""

    # Hangi surum? Cogu Outlook maili hem text/plain hem text/html tasir ve
    # plain surum bazen kirpik gelir ("multipart message" yer tutucusu, imza
    # kalintisi). Korlemesine plain secmek sessiz govde kaybi demek: belirgin
    # sekilde zengin olan surumu aliyoruz.
    if duz and zengin:
        if len(zengin) > 200 and len(duz) < len(zengin) * 0.3:
            govde, tipi = zengin, "html"
        else:
            govde, tipi = duz, "text"
    elif duz:
        govde, tipi = duz, "text"
    elif zengin:
        govde, tipi = zengin, "html"
    else:
        govde, tipi = "", ""

    govde = govde.replace("\r\n", "\n").replace("\r", "\n")
    govde = re.sub(r"\n{3,}", "\n\n", govde).strip()
    metin_durumu = {
        "metin_nul_kirpildi": durum["metin_nul_kirpildi"],
        "kaynak_replacement": durum["kaynak_replacement"],
        "metin_fallback": durum["metin_fallback"],
        "fallback_kodlamalar": sorted(durum["fallback_kodlamalar"]),
        "metin_cozulemeyen": durum["metin_cozulemeyen"],
    }
    return govde, tipi, ekler, sifreli, takvim, metin_durumu


# --------------------------------------------------------------------------
# Ana isleme
# --------------------------------------------------------------------------

def _sayfayi_isle(sayfa_yolu, kosu, klasor_yolu, ay_onek, baslangic_sira):
    with open(sayfa_yolu, "r", encoding="utf-8") as f:
        veri = json.load(f)
    kayitlar = veri.get("value", veri) if isinstance(veri, dict) else veri
    if not isinstance(kayitlar, list):
        raise SystemExit(
            "sayfa JSON'unda mail listesi bulunamadi (beklenen: value dizisi)")

    d_ham = os.path.join(kosu, "ham")
    d_govde = os.path.join(kosu, "govdeler")
    d_baslik = os.path.join(kosu, "basliklar")
    d_ekler = os.path.join(kosu, "ekler")
    d_sorunlu = os.path.join(kosu, "sorunlu_eml")
    for d in (d_ham, d_govde, d_baslik, d_ekler, d_sorunlu):
        os.makedirs(d, exist_ok=True)

    gorulen_yolu = os.path.join(kosu, "_gorulen.json")
    atlanan_yolu = os.path.join(kosu, "_atlanan.json")
    uyarilar_yolu = os.path.join(kosu, "_uyarilar.json")
    gorulen = set(contract.read_json(gorulen_yolu, []))
    atlanan_kayit = contract.read_json(atlanan_yolu, [])
    uyari_kayit = contract.read_json(uyarilar_yolu, [])
    if not isinstance(atlanan_kayit, list) or not isinstance(uyari_kayit, list):
        raise ValueError("Atlanan/uyarı durum şeması bozuk")

    mail_satirlar, ek_satirlar, notlar = [], [], []
    islenen = ek_sayaci = atlanan = hata = 0
    ek_byte = gomulu_byte = gomulu_sayaci = 0
    sira_sayaci = baslangic_sira - 1
    son_sira = baslangic_sira - 1

    for kayit in kayitlar:
        sira_sayaci += 1
        sira = "{0}-{1:05d}".format(ay_onek, sira_sayaci)
        eml_yolu = os.path.join(d_ham, sira + ".eml")
        if contract.read_json(Path(kosu) / "_kayitlar" / (sira + ".json")):
            continue  # Dış sözleşme bu kaydın kimlik ve hash'lerini doğruladı.
        kayit_ek_satirlar = []
        olusan_dosyalar = []
        olusan_dizinler = []
        uyari_baslangici = len(uyari_kayit)
        kayit_ek_sayaci = kayit_ek_byte = 0
        kayit_gomulu_sayaci = kayit_gomulu_byte = 0

        if not os.path.exists(eml_yolu):
            hata += 1
            notlar.append("{0}: ham .eml bulunamadi".format(sira))
            continue
        if os.path.getsize(eml_yolu) == 0:
            hata += 1
            notlar.append("{0}: ham .eml 0 byte, indirme bozuk".format(sira))
            continue

        try:
            with open(eml_yolu, "rb") as f:
                msg = email.message_from_binary_file(f, policy=email.policy.default)
        except Exception as e:
            hata += 1
            notlar.append("{0}: .eml parse edilemedi ({1})".format(
                sira, type(e).__name__))
            continue

        # --- Message-ID dogrulamasi: sira <-> .eml eslesmesi kaymasin
        beklenen_mid = (kayit.get("internetMessageId") or "").strip()
        gercek_mid = (msg.get("Message-ID") or "").strip()
        if beklenen_mid and beklenen_mid != gercek_mid:
            hata += 1
            notlar.append(
                "{0}: Message-ID uyusmuyor - sira/eml eslesmesi kaymis, "
                "bu mail yazilmadi".format(sira))
            continue

        try:
            (govde, govde_tipi, ekler, sifreli, takvim,
             metin_durumu) = govde_ve_ekler(msg)
        except Exception as e:
            hata += 1
            notlar.append("{0}: govde/ek cikarilamadi ({1})".format(
                sira, type(e).__name__))
            continue

        # Toplanti daveti / takvim ogesi: kapsam disi.
        # Sayim adimi bunlari de sayar ama CSV'ye girmezler; kontrol adiminin
        # "eksik mail" yanlis pozitifi vermemesi icin _atlanan.json'a yazilir.
        icerik_sinifi = (msg.get("Content-Class") or "").lower()
        if takvim or "calendarmessage" in icerik_sinifi:
            atlanan += 1
            atlanan_kayit.append({
                "sira_no": sira,
                "klasor_yolu": klasor_yolu,
                "mesaj_id": kayit.get("id") or "",
                "neden": "takvim/toplanti ogesi",
            })
            notlar.append("{0}: takvim/toplanti ogesi, kapsam disi".format(sira))
            continue

        konu = basligi_coz(msg.get("Subject"))
        tarih_ham = zaman_bicim(contract.record_date(dict(kayit, _folder_path=klasor_yolu))) or ""
        tarih_kisa = tarih_ham[:10].replace("-", "")

        govde_yok = sifreli or not govde.strip()

        # --- Govde dosyasi
        if govde_yok:
            # Sifreli/imzali ya da govdesi cikarilamayan: ham hali tek kaynak
            hedef = yol_sinirla(d_govde, "{0}_{1}_{2}.eml".format(
                sira, tarih_kisa, ascii_slug(konu)))
            hedef = cakismasiz(hedef)
            olusan_dosyalar.append(hedef)
            try:
                with open(eml_yolu, "rb") as kaynak, open(hedef, "wb") as cikti:
                    cikti.write(kaynak.read())
            except Exception as e:
                hata += 1
                notlar.append("{0}: ham hali saklanamadi ({1})".format(
                    sira, type(e).__name__))
                for path in reversed(olusan_dosyalar):
                    try:
                        if os.path.isfile(path):
                            os.remove(path)
                    except OSError:
                        pass
                continue
        else:
            hedef = yol_sinirla(d_govde, "{0}_{1}_{2}.txt".format(
                sira, tarih_kisa, ascii_slug(konu)))
            hedef = cakismasiz(hedef)
            olusan_dosyalar.append(hedef)
            try:
                with open(hedef, "w", encoding="utf-8") as f:
                    f.write(govde)
            except Exception as e:
                hata += 1
                notlar.append("{0}: govde yazilamadi ({1})".format(
                    sira, type(e).__name__))
                for path in reversed(olusan_dosyalar):
                    try:
                        if os.path.isfile(path):
                            os.remove(path)
                    except OSError:
                        pass
                continue
        govde_dosya_rel = os.path.relpath(hedef, kosu)

        # --- Ham internet basliklari
        baslik_rel = ""
        baslik_ok = False
        b_hedef = os.path.join(d_baslik, sira + ".txt")
        olusan_dosyalar.append(b_hedef)
        try:
            with open(b_hedef, "w", encoding="utf-8") as f:
                for k, v in msg.items():
                    f.write("{0}: {1}\n".format(k, v))
            baslik_rel = os.path.relpath(b_hedef, kosu)
            baslik_ok = os.path.getsize(b_hedef) > 0
        except Exception:
            notlar.append("{0}: basliklar yazilamadi".format(sira))

        # --- Ekler
        ek_klasoru_rel = ""
        inen_adlar, inen = [], 0
        gercek_ekler = [e for e in ekler if not e[3]]
        gomulu_ekler = [e for e in ekler if e[3]]
        mapi_gomulu = kayit.get("_mapi_gomulu") or []
        if not isinstance(mapi_gomulu, list):
            mapi_gomulu = []
        dolu_ek_sayisi = len([e for e in gercek_ekler if e[2]])
        bos_ekler = [e for e in gercek_ekler if not e[2]]

        if gercek_ekler:
            ek_dizin = os.path.join(d_ekler, sira)
            ek_dizin_vardi = os.path.isdir(ek_dizin)
            os.makedirs(ek_dizin, exist_ok=True)
            if not ek_dizin_vardi:
                olusan_dizinler.append(ek_dizin)
            ek_klasoru_rel = os.path.relpath(ek_dizin, kosu)

        for ad, tip, bayt, _ in gercek_ekler:
            satir = {
                "sira_no": sira, "mesaj_id": hucre(kayit.get("id")),
                "ek_adi": hucre(ad), "ek_tipi": hucre(tip),
                "boyut_byte": len(bayt), "gomulu_mu": "hayir",
            }
            if not bayt:
                satir.update({"indirildi_mi": "hayir", "kaydedilen_yol": "",
                              "hata": "icerik bos"})
                kayit_ek_satirlar.append(satir)
                notlar.append("{0}: ek '{1}' icerigi bos".format(sira, ad))
                continue
            ek_hedef = cakismasiz(yol_sinirla(ek_dizin, ad))
            olusan_dosyalar.append(ek_hedef)
            try:
                with open(ek_hedef, "wb") as f:
                    f.write(bayt)
                satir.update({"indirildi_mi": "evet",
                              "kaydedilen_yol": os.path.relpath(ek_hedef, kosu),
                              "hata": ""})
                inen_adlar.append(os.path.basename(ek_hedef))
                inen += 1
                kayit_ek_sayaci += 1
                kayit_ek_byte += len(bayt)
            except Exception as e:
                satir.update({"indirildi_mi": "hayir", "kaydedilen_yol": "",
                              "hata": type(e).__name__})
                notlar.append("{0}: ek '{1}' yazilamadi ({2})".format(
                    sira, ad, type(e).__name__))
            kayit_ek_satirlar.append(satir)

        # Gomulu imza gorselleri: kayda gecer, diske yazilmaz
        for ad, tip, bayt, _ in gomulu_ekler:
            kayit_gomulu_sayaci += 1
            kayit_gomulu_byte += len(bayt)
            kayit_ek_satirlar.append({
                "sira_no": sira, "mesaj_id": hucre(kayit.get("id")),
                "ek_adi": hucre(ad), "ek_tipi": hucre(tip),
                "boyut_byte": len(bayt), "gomulu_mu": "evet",
                "indirildi_mi": "hayir", "kaydedilen_yol": "", "hata": "",
            })

        # MAPI Çevrimiçi Arşiv akışında küçük imza görsellerinin ikili
        # içeriğini indirmek gereksiz ve çok pahalıdır. Kaynak adı/türü/boyutu
        # metadata'da taşınır; normal akıştaki gibi CSV'ye kaydedilir ve diske
        # yazılmaz. Gerçek ekler her zaman EML içinde tam içerikle gelir.
        for kaynak_ek in mapi_gomulu:
            try:
                kaynak_boyut = max(0, int(kaynak_ek.get("boyut_byte") or 0))
            except (TypeError, ValueError):
                kaynak_boyut = 0
            kayit_gomulu_sayaci += 1
            kayit_gomulu_byte += kaynak_boyut
            kayit_ek_satirlar.append({
                "sira_no": sira, "mesaj_id": hucre(kayit.get("id")),
                "ek_adi": hucre(kaynak_ek.get("ad")),
                "ek_tipi": hucre(kaynak_ek.get("tip")),
                "boyut_byte": kaynak_boyut, "gomulu_mu": "evet",
                "indirildi_mi": "hayir", "kaydedilen_yol": "", "hata": "",
            })

        # Kaynagin kendisinde veri kaybi/anomali varsa ham EML kanit olarak
        # sorunlu_eml/ altinda tutulur. Bu, export hatasi ile kaynak hatasini
        # birbirinden ayirmayi mumkun kilar.
        kanit_nedenleri = []
        if metin_durumu["metin_nul_kirpildi"]:
            kanit_nedenleri.append("metin_nul_kirpildi")
        if metin_durumu["kaynak_replacement"]:
            kanit_nedenleri.append("kaynak_replacement")
        if metin_durumu["metin_fallback"]:
            kanit_nedenleri.append("metin_fallback")
        if metin_durumu["metin_cozulemeyen"]:
            kanit_nedenleri.append("metin_cozulemeyen")
        if bos_ekler:
            kanit_nedenleri.append("kaynakta_bos_ek")
        if any(p.get_content_type() in IMZALI_TIPLERI or p.get_content_type() == "multipart/signed" for p in msg.walk()):
            kanit_nedenleri.append("imzali_mime")

        kanit_rel = ""
        kanit_ok = not kanit_nedenleri
        if kanit_nedenleri:
            kanit_hedef = os.path.join(d_sorunlu, sira + ".eml")
            olusan_dosyalar.append(kanit_hedef)
            try:
                kanit = ham_kanit_sakla(eml_yolu, d_sorunlu, sira)
                kanit_rel = os.path.relpath(kanit, kosu)
                kanit_ok = True
            except Exception as e:
                hata += 1
                notlar.append("{0}: ham kanit saklanamadi ({1})".format(
                    sira, type(e).__name__))

        def uyari_ekle(tur, adet=1, detay=""):
            uyari_kayit.append({
                "sira_no": sira,
                "mesaj_id": hucre(kayit.get("id")),
                "tur": tur,
                "adet": adet,
                "detay": detay,
                "ham_dosya": kanit_rel,
                "ham_sha256": contract.digest(eml_yolu),
                "internet_mesaj_id": gercek_mid or beklenen_mid,
            })

        if metin_durumu["metin_nul_kirpildi"]:
            uyari_ekle("metin_nul_kirpildi",
                       metin_durumu["metin_nul_kirpildi"])
        if metin_durumu["kaynak_replacement"]:
            uyari_ekle("kaynak_replacement",
                       metin_durumu["kaynak_replacement"])
        if metin_durumu["metin_fallback"]:
            uyari_ekle("metin_fallback", metin_durumu["metin_fallback"],
                       ",".join(metin_durumu["fallback_kodlamalar"]))
        if metin_durumu["metin_cozulemeyen"]:
            uyari_ekle("metin_cozulemeyen",
                       metin_durumu["metin_cozulemeyen"])
        if bos_ekler:
            uyari_ekle("kaynakta_bos_ek", len(bos_ekler),
                       COKLU_BIRLESTIRICI.join(e[0] for e in bos_ekler))

        if "imzali_mime" in kanit_nedenleri:
            uyari_ekle("imzali_mime")

        # --- Mukerrer tespiti
        mid = gercek_mid or beklenen_mid
        mid_onceden_vardi = bool(mid and mid in gorulen)
        mukerrer = "evet" if mid_onceden_vardi else "hayir"
        if mid:
            gorulen.add(mid)

        gonderen_ad, gonderen_mail = tek_adres(msg, "From")
        sender_ad, sender_mail = tek_adres(msg, "Sender")

        onizleme = re.sub(r"\s+", " ", govde)[:255] if govde else ""
        bayrak = ""
        flag = kayit.get("flag")
        if isinstance(flag, dict):
            bayrak = flag.get("flagStatus") or ""
        kategoriler = kayit.get("categories")
        if isinstance(kategoriler, list):
            kategoriler = COKLU_BIRLESTIRICI.join(str(k) for k in kategoriler)

        ham_satir = {
            "sira_no": sira,
            "klasor_yolu": klasor_yolu,
            "oge_tipi": "eml" if govde_yok else "mail",
            "konu": konu,
            "gonderen_ad": gonderen_ad, "gonderen_mail": gonderen_mail,
            "sender_ad": sender_ad, "sender_mail": sender_mail,
            "kime": adres_listesi(msg, "To"),
            "cc": adres_listesi(msg, "Cc"),
            "bcc": adres_listesi(msg, "Bcc"),
            "yanit_adresi": adres_listesi(msg, "Reply-To"),
            "alinma_zamani": zaman_bicim(kayit.get("receivedDateTime")),
            "gonderilme_zamani": zaman_bicim(kayit.get("sentDateTime")),
            "olusturma": zaman_bicim(kayit.get("createdDateTime")),
            "son_degisiklik": zaman_bicim(kayit.get("lastModifiedDateTime")),
            "govde_onizleme": onizleme,
            "govde_dosya": govde_dosya_rel,
            "govde_tipi": govde_tipi,
            "ek_var_mi": "evet" if gercek_ekler else "hayir",
            "ek_sayisi": len(gercek_ekler),
            "ek_adlari": COKLU_BIRLESTIRICI.join(inen_adlar),
            "ek_klasoru": ek_klasoru_rel,
            "okundu_mu": eb(kayit.get("isRead")),
            "taslak_mi": eb(kayit.get("isDraft")),
            "onem": kayit.get("importance") or "",
            "bayrak_durumu": bayrak,
            "kategoriler": kategoriler or "",
            "yanit_zinciri_mi": "evet" if msg.get("In-Reply-To") else "hayir",
            # Graph akışında ham EML boyutu gerçek kaynak boyutudur. MAPI
            # Çevrimiçi Arşiv akışında ise EML yerelde yeniden kurulur; o
            # durumda Table'dan gelen özgün öğe boyutunu koru.
            "boyut_byte": (kayit.get("_source_size")
                            or os.path.getsize(eml_yolu)),
            "cikarim_sinifi": kayit.get("inferenceClassification") or "",
            "mukerrer_mi": mukerrer,
            "sifreli_mi": "evet" if sifreli else "hayir",
            "mesaj_id": kayit.get("id") or "",
            "konusma_id": kayit.get("conversationId") or "",
            "konusma_index": kayit.get("conversationIndex") or "",
            "internet_mesaj_id": mid,
            "web_link": kayit.get("webLink") or "",
            "basliklar_dosya": baslik_rel,
        }
        # --- DOGRULAMA once, silme sonra.
        # Ters sira olursa yarim parse edilmis bir mailde hem ham veri hem
        # cikti birlikte kaybolur; bu sessiz kayip demektir.
        tam_govde = os.path.join(kosu, govde_dosya_rel)
        govde_ok = os.path.exists(tam_govde) and os.path.getsize(tam_govde) > 0
        ekler_ok = inen == dolu_ek_sayisi
        if bos_ekler and not kanit_ok:
            ekler_ok = False
        kanitlar_ok = not kanit_nedenleri or kanit_ok

        kayit_ok = govde_ok and ekler_ok and kanitlar_ok and baslik_ok
        if kayit_ok:
            mail_satirlar.append(
                dict((k, hucre(v)) for k, v in ham_satir.items()))
            ek_satirlar.extend(kayit_ek_satirlar)
            ek_sayaci += kayit_ek_sayaci
            ek_byte += kayit_ek_byte
            gomulu_sayaci += kayit_gomulu_sayaci
            gomulu_byte += kayit_gomulu_byte
            islenen += 1
        else:
            hata += 1
            notlar.append("{0}: dogrulama gecmedi, ham .eml korundu".format(sira))
            del uyari_kayit[uyari_baslangici:]
            if mid and not mid_onceden_vardi:
                gorulen.discard(mid)
            for path in reversed(olusan_dosyalar):
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                except OSError as e:
                    notlar.append("{0}: geri alma dosya hatasi ({1})".format(
                        sira, type(e).__name__))
            for path in reversed(olusan_dizinler):
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                except OSError as e:
                    notlar.append("{0}: geri alma dizin hatasi ({1})".format(
                        sira, type(e).__name__))

        son_sira = sira_sayaci

    if mail_satirlar:
        csv_ekle(os.path.join(kosu, "mailler.csv"), MAIL_KOLONLAR, mail_satirlar)
    if ek_satirlar:
        csv_ekle(os.path.join(kosu, "ekler.csv"), EK_KOLONLAR, ek_satirlar)

    with open(gorulen_yolu, "w", encoding="utf-8") as f:
        json.dump(sorted(gorulen), f)

    if atlanan_kayit:
        with open(atlanan_yolu, "w", encoding="utf-8") as f:
            json.dump(atlanan_kayit, f, ensure_ascii=False, indent=1)

    if uyari_kayit:
        # Kesintide tekrar islenen kayitlar ayni uyariyi cogaltmasin.
        tekil = {}
        for kayit in uyari_kayit:
            anahtar = (kayit.get("sira_no"), kayit.get("tur"),
                       kayit.get("detay"))
            tekil[anahtar] = kayit
        with open(uyarilar_yolu, "w", encoding="utf-8") as f:
            json.dump(list(tekil.values()), f, ensure_ascii=False, indent=1)

    return {
        "islenen": islenen,
        "ek": ek_sayaci,
        "ek_mb": round(ek_byte / 1048576.0, 1),
        "gomulu_atlanan": gomulu_sayaci,
        "gomulu_atlanan_mb": round(gomulu_byte / 1048576.0, 1),
        "atlanan": atlanan,
        "hata": hata,
        "son_sira": ("{0}-{1:05d}".format(ay_onek, son_sira)
                     if son_sira >= baslangic_sira else ""),
        "notlar": notlar[:40],
    }


def sayfayi_isle(sayfa_yolu, kosu, klasor_yolu, ay_onek, baslangic_sira):
    """Sayfa commit'i: CSV ekleme sınırı ve dosyalar tek günlükten kurtarılır."""
    if not re.fullmatch(r"\d{6}", ay_onek) or baslangic_sira < 1:
        raise ValueError("Geçersiz ay/sıra tahsisi")
    root = Path(kosu)
    root.mkdir(parents=True, exist_ok=True)
    data = contract.read_json(sayfa_yolu)
    records = data.get("value", data) if isinstance(data, dict) else data
    if not isinstance(records, list):
        raise ValueError("Sayfa mail listesi değil")
    with contract.lock(root / "_yazici.lock"):
        contract.recover(root)
        index = contract.record_index(root)
        source_sequences = {r.get("mesaj_id"): seq for mapping in (index[0], index[2])
                            for seq, rows in mapping.items() for r in rows if r.get("mesaj_id")}
        sequences = []
        for offset, record in enumerate(records):
            seq = f"{ay_onek}-{baslangic_sira + offset:05d}"
            if not isinstance(record, dict) or not record.get("id"):
                raise ValueError("Kaynak kimliği eksik")
            if record["id"] in source_sequences and source_sequences[record["id"]] != seq:
                raise ValueError("Aynı kaynak kimliğine farklı sıra tahsis edilemez")
            source_sequences[record["id"]] = seq
            receipt = contract.read_json(root / "_kayitlar" / (seq + ".json"))
            if receipt:
                if not contract.receipt_valid(root, seq, record.get("id", ""), index):
                    raise ValueError("Tamamlanmış kaydın kimliği/içeriği uyuşmuyor: " + seq)
                continue
            if seq in index[0] or seq in index[2]:
                raise ValueError("Eski yarım/çakışan kayıt; otomatik çoğaltılmaz: " + seq)
            sequences.append(seq)
        if not sequences:
            for offset in range(len(records)):
                (root / "ham" / f"{ay_onek}-{baslangic_sira + offset:05d}.eml").unlink(missing_ok=True)
            return dict(islenen=0, ek=0, ek_mb=0, gomulu_atlanan=0, gomulu_atlanan_mb=0,
                        atlanan=0, hata=0, son_sira="", notlar=[])
        txn = contract.RecordTransaction(root, sequences)
        txn.prepare()
        result = _sayfayi_isle(sayfa_yolu, kosu, klasor_yolu, ay_onek, baslangic_sira)
        if result["hata"]:
            contract.recover(root)
        else:
            index = contract.record_index(root)
            owned = contract.owned_files_many(root, sequences)
            for offset, record in enumerate(records):
                seq = f"{ay_onek}-{baslangic_sira + offset:05d}"
                if seq not in sequences:
                    continue
                if record.get("_mapi_transport_headers") is not None and seq in index[0]:
                    contract.atomic_bytes(root / "basliklar" / (seq + ".txt"),
                        record["_mapi_transport_headers"].encode("utf-8"))
                contract.record_receipt(root, seq, record.get("id", ""), root / "ham" / (seq + ".eml"), index, owned[seq])
            txn.commit()
        return result


# Konsol Turkce karakterleri bozmasin: Windows'ta stdout cp1254/cp437
# olabiliyor, o zaman ciktidaki 'Arsiv' gibi adlar bozuk okunur.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser(
        description="Indirilen .eml'leri CSV + govde + eke cevirir")
    ap.add_argument("--sayfa", required=True, help="Graph liste sonucu (JSON)")
    ap.add_argument("--kosu", required=True, help="Kosu klasoru")
    ap.add_argument("--klasor-yolu", required=True,
                    help='Ornek: "Arsiv\\01_Tedarikciler"')
    ap.add_argument("--ay-onek", required=True, help="Ornek: 202607")
    ap.add_argument("--baslangic-sira", type=int, required=True,
                    help="Bu sayfanin ilk sira numarasi")
    a = ap.parse_args()

    if not os.path.isdir(a.kosu):
        raise SystemExit("kosu klasoru yok: " + a.kosu)
    if not os.path.isfile(a.sayfa):
        raise SystemExit("sayfa JSON'u yok: " + a.sayfa)

    sonuc = sayfayi_isle(a.sayfa, a.kosu, a.klasor_yolu,
                         a.ay_onek, a.baslangic_sira)
    print(json.dumps(sonuc, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
