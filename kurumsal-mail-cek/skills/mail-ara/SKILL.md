---
name: mail-ara
description: Kurumsal mail arşivinde (Drive'ım\maillerim, 2024'ten bugüne) gövde ve PDF/Excel/Word ek metinlerini anlam + kelime + kişi/tarih süzgeciyle arar; bulunan kaynakları okuyup özetlemeye hazırlar. Arşive salt okunur erişir, yerel çalışır. "maillerde ara", "eklerde ara", "ekteki teklifi bul", "şu konu ne aşamada", "X kişisi neyle uğraşıyor", "şu tedarikçiyle ne yazıştık", "hangi mailde geçiyordu", "mail indeksini güncelle" isteklerinde kullan. Mail çekme işi kurumsal-mail-cek becerisindedir.
metadata:
  version: "1.3.0"
---

# Mail Ara

Mail gövdeleri temizlenip (bağlantı, imza, base64, uzun alıntı zinciri atılır) iki indekse
yazılır: **Chroma** (anlamsal, `multilingual-e5-small` ONNX, Türkçe çalışır) ve **SQLite FTS5**
(kelime, Türkçe katlamalı: `GÖRDES` = `gördes` = `gordes`). Arama ikisini RRF ile birleştirir;
kişi ve tarih süzgeci üst veriden uygulanır. Gömme modeli ve aramalar yerel çalışır.

**v1.2.0 (2026-10-15):** PDF, XLSX/XLSM ve DOCX ekleri artımlı çıkarılıp aranır.
Normal hibrit ve kelime araması ekleri de kullanır; `--mod ek` yalnız ek içeriğinde,
`--eksiz` gövdelerde arar. Ek sonucunda `[E]`, ekin kendi alıntısı ve dosya yolu bulunur.
Kişi/tarih süzgeci 30 bin içerik sınırına kadar ek sıralamasından önce uygulanır.
Gövde aramasını bastırmaması için ek kolunun RRF ağırlığı **0,1**'dir
(`MAIL_EK_AGIRLIK`); yalnız ek modunda sıralama bu ortak çarpandan etkilenmez.
71 soruda ilk5: eksiz hibrit50, eşit ek ağırlığı43, seçilen0,1 ile51;
kişi ilk5=8/9, MRR0,652. Bu set gövde soruları ağırlıklıdır ve ayar seçiminde kullanılmıştır.
Yeni ek soruları için bağımsız başarı oranı değildir. Kanıt:
[[outputs/chroma-yeniden-inceleme-20261014/CODEX-DEVAM]].

**v1.1.0 (2026-10-14):** Chroma koleksiyonu `index\chroma_v2`'dir: metin yazılmaz (metin
`mail.sqlite`/FTS5'te), e5 gömücü Chroma'ya kayıtlıdır (`query_texts` doğru modelle çalışır,
kaydı yüklemeyen süreç açık hata alır). Kişi süzgeci (`--kimden`/`--kisi`) Chroma'nın içinde
uygulanır; kelime kolu 5 harf kökü kullanır ("konteynerlerin" → `konte*`), anlam kolu RRF'de
0,5 ağırlıklıdır. Gerekçe ve ölçüm: [[outputs/chroma-yeniden-inceleme-20261014/SONUC]].
Eski `index\chroma` (v1) Ortak'ın kararıyla 2026-10-14'te Geri Dönüşüm Kutusu'na taşındı.

## Yollar

| Ne | Yer |
|---|---|
| Arşiv (**salt okunur**, CLAUDE.md/AGENTS.md koruma tablosu) | `C:\Users\ozanbesinci\Drive'ım\maillerim\<yıl>\<ay-yıl>\{govdeler,basliklar,ekler}` |
| Sanal ortam, model, indeks | `D:\AI-BACKUP\mail-indeks\{.venv, model\onnx, index}` |
| Betikler | bu skill'in `scripts\` klasörü |

Arama, gövde/ek indeksleme ve değerlendirme sanal ortamdan koşar.
**Ek metni çıkarma sistem Python'uyla `py -3 -E` kullanır:** openpyxl/python-docx
kullanıcı paketlerindedir; `-I` bunları gizler. Ek çıkarıcı venv ile çalıştırılmaz.

```powershell
$py  = 'D:\AI-BACKUP\mail-indeks\.venv\Scripts\python.exe'
$sk  = "$env:USERPROFILE\.claude\skills\mail-ara\scripts"   # Codex: ~\.codex\skills\mail-ara\scripts
$env:PYTHONIOENCODING = 'utf-8'
```

## Komutlar

```powershell
& $py -I "$sk\ara.py" "gördes ges arazi tapu sorunu"                     # hibrit, ilk 15
& $py -I "$sk\ara.py" "konteyner teklifi" --bas 2026-08-01 --bit 2026-08-31 --adet 25
& $py -I "$sk\ara.py" "ödeme blokajı" --kimden burak                     # gönderen süzgeci
& $py -I "$sk\ara.py" "olin" --kisi "ozanbesinci"                        # kimden/kime/bilgi herhangi biri
& $py -I "$sk\ara.py" --kimden "burak yılmaz" --bas 2026-08-01 --bit 2026-08-31 --listele --adet 500
& $py -I "$sk\ara.py" --tam 202608-05596 202608-05597                    # temiz metin + ham dosya yolu
& $py -I "$sk\ara.py" "..." --mod kelime    # veya --mod anlam
& $py -I "$sk\ara.py" "teklif birim fiyat" --mod ek        # PDF/Excel/Word ek içeriği
& $py -I "$sk\ara.py" "ödeme blokajı" --eksiz             # yalnız gövde

& $py -I "$sk\indeksle.py" --durum           # hangi ay indekste
& $py -I "$sk\indeksle.py" --ay 2026-09      # kurumsal-mail-cek yeni ay çektikten sonra
& $py -I "$sk\indeksle.py" --tumu            # bütün arşiv; değişmeyen mail atlanır (artımlı)

& $py -I "$sk\degerlendir.py"                # 71 soruluk sabit set: kelime/anlam/hibrit/kişi ölçümü
& $py -I "$sk\degerlendir.py" --ekli --json "D:\AI-BACKUP\mail-indeks\degerlendirme\sonuc.json"

py -3 -E "$sk\ek_cikar.py" --durum          # çıkarma ayları ve metin/hata sınıfları
py -3 -E "$sk\ek_cikar.py"                  # tüm aylar; bitmiş dosyalar atlanır
py -3 -E "$sk\ek_cikar.py" --ay 2026-09      # yeni ayın ekleri
& $py -I "$sk\ek_indeksle.py" --durum        # metinli/indeksli içerik ve parça sayısı
& $py -I "$sk\ek_indeksle.py" --is-parcacigi 8  # yerelde ölçülen CPU ayarı; artımlı
```

Aktarımdan teslim için `& $py -I "$sk\aktarim_indeksle.py" --ay YYYY-MM` kullan.
Bu sarmalayıcı üç aşamayı sırayla çalıştırır ve güncel run_id/arşiv hash'i ile
`index/aktarim/<ay>.json` teslim makbuzunu üretir. Alt betikler de güncel aktarım
doğrulaması olmadan yazmaz; `--durum` tarihçe/sayım bilgisidir.
Düz ay ve yıl/ay düzeni desteklenir; iki konum birden varsa durulur.
Kod/model/tokenizer/paket nesli değişirse mevcut nesille karıştırılmaz. Geçiş için
`kurumsal-mail-cek/references/guvenli-devam.md` okunur. Mevcut indeksi kendiliğinden
silme veya yeni köke geçirme. Arama/puanlama mantığı bu aktarım güncellemesinde değişmez.

Yeni ay geldikten sonra gövdeyi `indeksle.py --ay`, ekleri `ek_cikar.py --ay`,
ardından `ek_indeksle.py` ile güncelle. Ek indeksleme, çıkarma ve gövde indekslemesinin
bitmesini bekler. Aynı içerik yeni mailde veya yeni dosya adıyla geldiğinde mail listesi
ve dosya adı alanı yenilenir. Tam metin Türkçe katlamalı FTS'de, ham çıkarılmış metin
`index\ekler.sqlite`'ta, vektörler Chroma v2 `ekler` koleksiyonundadır.

Arama veya indeksleme mantığı değişirse önce ve sonra `degerlendir.py` koş; ayar kararı
ölçümsüz verilmez. Set kurumsal içerik taşıdığı için vault dışında:
`D:\AI-BACKUP\mail-indeks\degerlendirme\soru-seti-v1.json`.

Sonuç satırında `[A]` anlamsal, `[K]` kelime, `[E]` ek eşleşmesidir; harfler birleşebilir.
RRF puanı sıralama içindir, güven yüzdesi değildir. `--mod anlam` gövde anlam kolunu kullanır.
Çıktı uzunsa `> "$env:TEMP\...txt"` ile dosyaya al ve Read ile oku (konsol kod sayfası
Türkçe karakteri bozabilir; veri bozuk değildir).

## Soruya göre yol (2026-10-13 denemesinden)

- **Kişi soruları** ("X neyle uğraşıyor"): anlamsal arama rastgele 10 doğru mail getirir,
  resmi kaçırır. `--kimden X --listele` ile **hepsini** al, konuya göre grupla, özetle.
  Gönderdikleri ile alıcı olduklarını (`--kisi`) ayırarak söyle.
- **Adı bilinen konu** ("Gördes GES ne aşamada"): hibrit kullan ama `--adet` yüksek tut (50+).
  Denemede anlamsal ilk 15'in hepsi isabetliydi ama kelime araması 55 mail buldu ve
  en kritik son durum maili yalnız onda vardı. Son durumu tarih sırasıyla kur, en yeni
  mailleri `--tam` ile oku.
- **Kelimesi belirsiz soru** ("fiyat itirazı olan yazışma", "geciken sevkiyat şikâyeti"):
  anlamsal arama burada değer katar; hibrit varsayılan kalsın.
- Cevapta mail kimliği ve tarih ver; arşivin **son indekslenen ayını** (`--durum`) söyle —
  arşiv canlı posta kutusunun gerisinde kalır, "şu an" diye sunma.
- Ham metin (alıntı zinciri dahil) gerekirse `--tam` çıktısındaki `Dosya:` yolunu Read ile oku.

## Sınırlar

- Eklerde OCR yok. Taranmış/boş belge `metin_yok`; bozuk, şifreli ve hata veren kaynaklar
  ayrı sınıflanır. 15.10.2026 envanteri: 90.046 desteklenen dosya, 69.498 farklı içerik;
  60.104 metinli içerik/110.432 vektör parçası. Kayıtların tamamı metinli değildir.
- PDF ilk40sayfa ve en çok60.000karakter; XLSX/XLSM her sayfada ilk3.000satır ve
  toplam60.000karakter; DOCX ana gövde paragrafları ve tabloları, en çok60.000karakter.
  PDF'de gerçek alfanümerik metin40karakteri aşmalıdır; kısa gerçek metin de `metin_yok` kalabilir.
  Sayfa etiketleri gerçek metin sayılmaz. XLSX formülleri yeniden hesaplanmaz,
  kaydedilmiş değerleri okunur; DOCX revizyon/yorum, üst/alt bilgi ve çizim metinleri aktarılmaz.
- Eklerin kelime kolu çıkarılmış tam metni, anlam kolu yalnız ilk2parçayı kullanır.
  PNG/JPG/görsel, MSG/EML ekleri, eski DOC ve XLS bu ek çıkarıcının kapsamı dışındadır.
  Gövde klasöründeki EML için aşağıdaki destek geçerlidir.
- Gövdenin ilk 6.000 karakteri anlamsal indekse, ilk 20.000 karakteri kelime indeksine girer.
  Kendi metni 300 karakterden kısa cevaplarda alıntının ilk 1.500 karakteri eklenir;
  daha derindeki alıntı zinciri indekste yoktur (o mailler genelde ayrıca arşivdedir).
- Gövdelerin ~%2'si (2.670) düz metne çevrilememiş ham `.eml`'dir; indeksleyici bunları
  kendisi çözer (düz metin yoksa HTML'den). `--tam` çıktısındaki `Dosya:` `.eml` olabilir.
- Çok genel/belirsiz sorular ("fiyat itirazı olan yazışma") zayıf sonuç verir: anlamsal taraf
  konu yakınlığı bulur, ama "itiraz" gibi niyet kelimelerini ayırt etmez. Soruyu tedarikçi,
  malzeme, tarih aralığı ile daralt; bir kez geniş, sonra `--kimden`/`--bas` ile dar ara.
- e5 benzerlik puanları dar bantta (0,84–0,89) toplanır; puanı mutlak eşik gibi kullanma, sıraya bak.
- **Anlamsal arama 146 bin mailde tek başına zayıftır** (2026-10-14, 71 soru): kelimeleri
  bilerek değiştirilmiş 11 soruda anlam kolu ilk 5'te 0/11; kelime kolu genel olarak
  yardımcıdır (15.10.2026: ilk5 kelime49/71, eksiz hibrit50/71, ekli hibrit51/71). Soruyu maildeki olası
  kelimelerle (tedarikçi, ürün, belge adı) kur; anlamsal taraf yardımcıdır.
- Kişi ön-süzgeci SQLite değişken sınırı nedeniyle 30 bin maile kadar Chroma içinde çalışır;
  daha geniş bir süzgeçte (ör. `--kisi ozan` tüm dönem) eski yönteme (geniş havuzdan sonradan
  süzme) düşer; tarih aralığı vererek daralt.
- İlk tam indeksleme 143 bin mail için ~4 saat sürer (CPU, fp32; Ağustos 5.663 mail = 14 dk).
  `--tumu` en yeni aydan geriye gider ve süreç boyunca Windows boşta uykusunu erteler
  (kapak kapanırsa yine uyur; yarıda kalırsa `--tumu` kaldığı yerden devam eder).
  int8 sıkıştırılmış model 3–4 kat hızlı ama ilk 10 sonuçta 5–9/10 örtüşüyor (2026-10-13
  ölçümü) — kullanılmıyor; `model\onnx\model_int8.onnx` yalnız o ölçümün artığı.
- Gövde ve ek indeksleme aynı `index\indeksle.kilit` dosyasını atomik edinir;
  çıkarma `index\ekler.kilit` kullanır. Kilit yaşı canlı işlemi geçersiz kılmaz.
  Bayat kilidi kaldırmadan önce sahibi süreç ve diğer indeksleyiciler kontrol edilir.
  **SQLite `*-journal` dosyaları silinmez:** yarım işlemi SQLite açılışta geri alır.
- Arşiv klasörüne hiçbir şey yazılmaz; onarım ve bütün çıktı indeks ağacında yapılır.
