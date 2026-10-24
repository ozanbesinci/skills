"""mail-ara ortak parçaları: yollar, temizlik, Türkçe katlama, ONNX gömücü, veritabanı.

Arşiv (Drive'ım\\maillerim) yalnız okunur. Yazılan her şey MAIL_INDEKS_KOK altına gider.
"""
import aktarim
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import timezone, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

KOK = Path(os.environ.get("MAIL_INDEKS_KOK", r"D:\AI-BACKUP\mail-indeks"))
ARSIV = Path(os.environ.get("MAIL_ARSIV_KOK", str(Path.home() / "Drive'ım" / "maillerim")))
MODEL_DIZIN = KOK / "model" / "onnx"
DB_YOLU = KOK / "index" / "mail.sqlite"
CHROMA_DIZIN = KOK / "index" / "chroma"        # v1: belgeli, varsayılan EF kayıtlı
CHROMA_V2 = KOK / "index" / "chroma_v2"        # v2: belgesiz, kayıtlı e5 EF (1.2.0)
KOLEKSIYON = "mailler"
EF_ADI = "mail_ara_e5_small_onnx"
MODEL_ADI = "intfloat/multilingual-e5-small (onnx)"

AYLAR = ["ocak", "subat", "mart", "nisan", "mayis", "haziran",
         "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik"]
TR_SAAT = timezone(timedelta(hours=3))

PARCA, BINDIRME, GOMME_SINIRI, METIN_SINIRI = 1200, 150, 6000, 20000


def utf8_cikti():
    for akim in (sys.stdout, sys.stderr):
        try:
            akim.reconfigure(encoding="utf-8")
        except Exception:
            pass


def kilit_al(yol):
    """Tek yazıcı: varlık kontrolü ve yaratma tek atomik dosya işlemidir.

    Süre dolması canlı bir işi bitirmez. Bayat kilit ancak sahibi çalışmıyorsa,
    devirdeki süreç kontrolünden sonra kaldırılır; SQLite günlükleri kaldırılmaz.
    """
    yol.parent.mkdir(parents=True, exist_ok=True)
    try:
        with yol.open("x", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except FileExistsError:
        sys.exit(f"Kilit mevcut: {yol}. Canlı süreci doğrulayın; yalnız süreç yoksa kilidi kaldırın.")


# ---------------------------------------------------------------- arşiv yolları

def ay_klasoru(ay):
    return aktarim.ay_klasoru(ARSIV, ay)


def arsiv_aylari():
    return [ay for ay in aktarim.arsiv_aylari(ARSIV) if (ay_klasoru(ay) / "govdeler").is_dir()]


# ---------------------------------------------------------------- metin

_TR_BUYUK = str.maketrans({"İ": "i", "I": "ı"})
_TR_ASCII = str.maketrans({"ı": "i", "ö": "o", "ü": "u", "ç": "c", "ş": "s", "ğ": "g",
                           "â": "a", "î": "i", "û": "u"})


def katla(metin):
    """Türkçe güvenli küçük harf + ASCII katlama: 'GÖRDES', 'Gördes', 'gordes' aynı olur."""
    metin = metin.translate(_TR_BUYUK).lower().translate(_TR_ASCII)
    metin = unicodedata.normalize("NFKD", metin)
    return "".join(c for c in metin if not unicodedata.combining(c))


_URL = re.compile(r"<?https?://[^\s>]+>?")
_CID = re.compile(r"\[(cid:[^\]]*|[^\]]*\.(png|jpe?g|gif))\]", re.I)
_ALINTI = re.compile(
    r"^(From:|Kimden:|Gönderen:|-----Original Message|-----Özgün İleti|_{20,})", re.M)
_IMZA = re.compile(
    r"^.*(Saygılarımla \|\| Best Regards|KILIÇ DENİZ ÜRÜNLERİ A\.Ş|Kemikler Mah\.|"
    r"Tel: \+90|www\.kilic|Tanıtım Filmi|\[Instagram\]|\[LinkedIn\]|\[Facebook\]|"
    r"\[Youtube\]|Bu e-posta ve ekleri|This e-mail and any|\|\| [A-Z][a-z]+ [A-Z]).*$"
    r"|^\s*\[[^\]\n]{0,30}\]\s*$",
    re.M | re.I)
# Gövdeye düşmüş base64/izleme kodu gibi boşluksuz uzun diziler anlam taşımaz.
_UZUN_DIZI = re.compile(r"\S{40,}")


def temizle(metin):
    metin = _URL.sub("", metin)
    metin = _CID.sub("", metin)
    m = _ALINTI.search(metin)
    if m:
        kendi = metin[: m.start()]
        # Kısa cevaplarda ("ekte", "uygundur") asıl içerik alıntıdadır.
        if len(kendi.strip()) >= 300:
            metin = kendi
        else:
            metin = kendi + "\n" + metin[m.start(): m.start() + 1500]
    metin = _IMZA.sub("", metin)
    metin = _UZUN_DIZI.sub("", metin)
    metin = re.sub(r"[ \t]+", " ", metin)
    return re.sub(r"\n\s*\n+", "\n", metin).strip()[:METIN_SINIRI]


def parcala(metin):
    metin = metin[:GOMME_SINIRI]
    if len(metin) <= PARCA:
        return [metin]
    parcalar, i = [], 0
    while i < len(metin):
        parcalar.append(metin[i: i + PARCA])
        i += PARCA - BINDIRME
    return parcalar


def baslik_coz(deger):
    if not deger:
        return ""
    try:
        return str(make_header(decode_header(str(deger)))).strip()
    except Exception:
        return str(deger).strip()


def tarih_coz(deger):
    """(görünen 'YYYY-AA-GG SS:DD', YYYYAAGG tamsayı) — Türkiye saatine çevrilmiş."""
    try:
        t = parsedate_to_datetime(deger)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        t = t.astimezone(TR_SAAT)
        return t.strftime("%Y-%m-%d %H:%M"), int(t.strftime("%Y%m%d"))
    except Exception:
        return "", 0


# ---------------------------------------------------------------- gömücü

class Gomucu:
    """multilingual-e5-small'ın resmi ONNX sürümü; torch gerektirmez, saniyede açılır."""

    def __init__(self, is_parcacigi=None):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.np = np
        so = ort.SessionOptions()
        so.intra_op_num_threads = is_parcacigi or max(1, (os.cpu_count() or 4) - 2)
        self.oturum = ort.InferenceSession(
            str(MODEL_DIZIN / "model.onnx"), so, providers=["CPUExecutionProvider"])
        self.girdiler = {g.name for g in self.oturum.get_inputs()}
        self.tok = Tokenizer.from_file(str(MODEL_DIZIN / "tokenizer.json"))
        self.tok.enable_truncation(max_length=512)
        pad = self.tok.token_to_id("<pad>")
        self.tok.enable_padding(pad_id=pad, pad_token="<pad>")

    def _kodla(self, metinler):
        np = self.np
        kod = self.tok.encode_batch(metinler)
        ids = np.array([k.ids for k in kod], dtype=np.int64)
        maske = np.array([k.attention_mask for k in kod], dtype=np.int64)
        besle = {"input_ids": ids, "attention_mask": maske}
        if "token_type_ids" in self.girdiler:
            besle["token_type_ids"] = np.zeros_like(ids)
        gizli = self.oturum.run(None, besle)[0]
        m = maske[..., None].astype(np.float32)
        v = (gizli * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def gom(self, metinler, onek, toplu=32, ilerleme=None):
        """onek: belge için 'passage: ', soru için 'query: ' (e5 sözleşmesi)."""
        np = self.np
        sira = sorted(range(len(metinler)), key=lambda i: len(metinler[i]))
        sonuc = np.zeros((len(metinler), 384), dtype=np.float32)
        for b in range(0, len(sira), toplu):
            dilim = sira[b: b + toplu]
            sonuc[dilim] = self._kodla([onek + metinler[i] for i in dilim])
            if ilerleme:
                ilerleme(min(b + toplu, len(sira)), len(sira))
        return sonuc


# ---------------------------------------------------------------- depolar

SEMA = """
CREATE TABLE IF NOT EXISTS mail(
    mail_id TEXT PRIMARY KEY, ay TEXT, tarih TEXT, tarih_int INTEGER,
    kimden TEXT, kime TEXT, cc TEXT, konu TEXT, dosya TEXT,
    boyut INTEGER, mtime REAL, parca INTEGER, metin TEXT,
    kimden_k TEXT, kisiler_k TEXT);
CREATE INDEX IF NOT EXISTS mail_ay ON mail(ay);
CREATE INDEX IF NOT EXISTS mail_tarih ON mail(tarih_int);
CREATE VIRTUAL TABLE IF NOT EXISTS mail_fts USING fts5(
    mail_id UNINDEXED, konu, kisiler, metin, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS mail_fingerprint(mail_id TEXT PRIMARY KEY, fingerprint TEXT);
CREATE TABLE IF NOT EXISTS ay_durum(
    ay TEXT PRIMARY KEY, mail_sayisi INTEGER, parca_sayisi INTEGER, zaman TEXT, model TEXT);
"""


def db_ac():
    DB_YOLU.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_YOLU)
    db.executescript(SEMA)
    return db


_EF_SINIFI = None


def e5_ef():
    """multilingual-e5-small gömücüsünü Chroma'ya kayıtlı bir EF olarak döndürür.

    Koleksiyon modelini kendisi tanır: `query_texts` doğru önekle (query:) bu modeli kullanır;
    sınıfı yüklemeyen bir süreç sessizce varsayılan İngilizce MiniLM'e düşmez, açık hata alır.
    """
    global _EF_SINIFI
    if _EF_SINIFI is None:
        from chromadb.api.types import EmbeddingFunction
        from chromadb.utils.embedding_functions import register_embedding_function

        @register_embedding_function
        class E5OnnxEF(EmbeddingFunction):
            def __init__(self):
                self._gomucu = None

            def _g(self):
                if self._gomucu is None:
                    self._gomucu = Gomucu()
                return self._gomucu

            def __call__(self, input):
                return list(self._g().gom(list(input), "passage: "))

            def embed_query(self, input):
                return list(self._g().gom(list(input), "query: "))

            @staticmethod
            def name():
                return EF_ADI

            def default_space(self):
                return "cosine"

            def supported_spaces(self):
                return ["cosine"]

            def get_config(self):
                return {"model": "intfloat/multilingual-e5-small", "bicim": "onnx"}

            @staticmethod
            def build_from_config(config):
                return E5OnnxEF()

        _EF_SINIFI = E5OnnxEF
    return _EF_SINIFI()


def v2_var():
    return (CHROMA_V2 / "chroma.sqlite3").exists()


def koleksiyon():
    """v2 (belgesiz, kayıtlı e5 EF) varsa onu, yoksa geçiş öncesi v1 koleksiyonunu açar."""
    import chromadb
    ef = e5_ef()
    if v2_var() or not (CHROMA_DIZIN / "chroma.sqlite3").exists():
        istemci = chromadb.PersistentClient(path=str(CHROMA_V2))
        kol = istemci.get_or_create_collection(
            KOLEKSIYON, embedding_function=ef, metadata={"hnsw:space": "cosine", "model": MODEL_ADI})
        ad = kol.configuration_json.get("embedding_function", {}).get("name")
        if ad != EF_ADI:
            raise RuntimeError(f"v2 koleksiyonunun kayıtlı EF'si beklenmedik: {ad}")
        return kol
    # v1: varsayılan MiniLM kayıtlı; yalnız query_embeddings ile kullanılır, metin verilmez.
    istemci = chromadb.PersistentClient(path=str(CHROMA_DIZIN))
    return istemci.get_or_create_collection(
        KOLEKSIYON, metadata={"hnsw:space": "cosine", "model": MODEL_ADI})
