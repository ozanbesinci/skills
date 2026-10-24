## 1.3.0 — 2026-10-24

- Aktarım doğrulama kapısı ve üç aşamalı indeks teslimi; düz ay çözümü, metadata hash invalidasyonu, silinen ek/vektör uzlaştırması ve nesil kimliği.
- Gerçek arşiv/indeks/PST üzerinde geçiş veya aktarım çalıştırılmaz; eski indeks nesli için açık geçiş gerekir.

# Sürüm Geçmişi — mail-ara

Sürümleme: büyük sürüm komut yapısını, küçük sürüm yeni komut veya kontrolü, yama sürümü
düzeltmeyi belirtir.

## v1.2.0 — 2026-10-15

Kaynak: `outputs/chroma-yeniden-inceleme-20261014/CODEX-DEVIR.md`; sonuç ve sınırlar:
`outputs/chroma-yeniden-inceleme-20261014/CODEX-DEVAM.md`.

- PDF/XLSX/XLSM/DOCX metin çıkarma, SHA-1 ile içerik tekilleştirme, FTS tam metin ve
  Chroma v2 `ekler` koleksiyonu (yalnız ilk2parça, kayıtlı e5 EF, belgesiz).
  32ay/90.046dosya, 60.104metinli içerik/110.432parça; tüm ID/metin/mail-listesi kontrolleri0fark.
- `--mod ek`, `--eksiz`, normal hibritte ek kolu; kişi/tarih ön-süzgeci, gerçek ek alıntısı
  ve dosya yolu. Ek dosya adlarının bütün farklı biçimleri kelime alanına yazılır,
  bağlı mail kimlikleri liste üst verisinde tutulur.
- Yeni mail/dosya adıyla gelen aynı içerik artımlı çalışmada yenilenir; FTS tekrarı oluşmaz.
  Kesinti sonrası vektörler aynı ID'ye upsert edilir. 8iş parçacığı seçeneği eklenmiştir;
 128gerçek örnekte20iş parçacığıyla vektör farkı0, hız yaklaşık%37 fazla.
- Sayfa etiketinin boş/taranmış belgeyi metinli sayması düzeltildi; türetilmiş kayıtlarda
  519içerik/658bağ ve ek6kısaPDF/8bağ düzeltildi. Bozuk/hata/şifreli/OCR kapsamı açık tutulur.
- Tarihi dolu ama göndereni eksik mail artımlı seçime girer; CSV'den1mail/2parça onarıldı.
  146.036mail/179.537parça eşit, tarihsiz/gönderensiz0, 434kaynakta boş konu korunur.
- Üç yazma girişinde atomik ve süreden bağımsız kilit; sistem çıkarıcısında UTF8 stderr
  ve izolasyonlu betik yolu. İki süreç yarışı/eski kilit4kontrol, çıkarma8, arama12,
  artımlı yenileme4 ve gerçek CLI5senaryo geçti; bunlar ticari kabul değildir.
- `degerlendir.py --ekli` ve isteğe bağlı `--siralamalar`: aynı71soruda eksiz/ekli ölçüm.
  Eşit ek ağırlığında ilk5=43/71; 0,1 ağırlıkla51/71, eksiz50/71.
  Kişi ilk5=8/9 ve MRR0,652korundu. `MAIL_EK_AGIRLIK` ile değiştirilebilir.
  Ayar bu sette seçildi; bağımsız ek soruları başarısı olarak sunulmaz.

## v1.1.0 — 2026-10-14

Kaynak: Chroma deposunun yeniden incelemesi ve Ortak'ın "hepsini sırayla yap" talimatı
(outputs/chroma-yeniden-inceleme-20261014/SONUC.md).

- **Koleksiyon v2** (`index\chroma_v2`, `v2_gecis.py`): belgesiz; kayıtlı e5 EF
  (`mail_ara_e5_small_onnx`, `embed_query` "query:" önekiyle). v1 varsayılan İngilizce MiniLM'i
  kayıtlıydı (aynı 384 boyut → `query_texts` sessiz yanlış sonuç). Geçiş yeniden gömmeden
  vektör kopyaladı: 175.245 parça eşit, 200 örnekte vektör/üst veri aynı, kesin ilk-20'ye göre
  isabet v2 ≥ v1; disk 1,5 GB → 365 MB. v1 klasörü Ortak'ın kararıyla aynı gün Geri Dönüşüm Kutusu'na taşındı.
  `indeksle.py` v2 varken metni Chroma'ya yazmaz.
- **Kişi süzgeci Chroma içinde** (`mail_id $in`, 30 bin değere kadar; üstünde geniş havuzdan
  sonradan süzme). 9 kişi sorusunda anlamsal kol ilk 10: 6 → 8, MRR 0,38 → 0,52.
- **5 harf kökü** (kelime kolu) ve **anlam ağırlığı 0,5** (RRF): 71 soruda kelime ilk 5
  44 → 49; kişi hibrit MRR 0,67 → 0,73. Ortam değişkeniyle değiştirilebilir
  (`MAIL_KOK_UZ`, `MAIL_KELIME_AGIRLIK`, `MAIL_ANLAM_AGIRLIK`).
- **Değerlendirme seti + `degerlendir.py`**: 71 soru (kelime 51, anlam 11, kişi 9),
  `D:\AI-BACKUP\mail-indeks\degerlendirme\` (kurumsal içerik vault dışında). Ölçüm v1'de;
  başlık onarımı sürerken alındı, v2'de onarım sonrası tekrar koşulacak.

## v1.0.2 — 2026-10-14

- düzeltme: Gönderilmiş Öğeler'deki maillerde sunucu başlığı yok (başlık dosyasında yalnız
  "MAPI transport başlığı yok"); onarılmış 9 ayda 665 mail bu yüzden tarihsiz/gönderensiz
  kalıyordu — Ortak'ın kendi gönderdiği mailler. Başlıkta tarih veya gönderen yoksa ayın
  `mailler.csv` satırından (konu, gönderen, kime, bilgi, gönderilme zamanı) tamamlanıyor.
  İç göndericide adres X.500 olduğu için yalnız ad yazılır → `--kimden "ozan"` çalışır,
  `--kimden "ozanbesinci@"` bu mailleri bulmaz.
- Not: aynı gün diğer Claude oturumu v2 geçişini yaptı (index\chroma_v2, kayıtlı e5 EF,
  belgesiz koleksiyon; ara.py kişi ön-süzgeci). Onun sürüm kaydı ayrıca bu dosyaya eklenecek.

## v1.0.1 — 2026-10-14

- düzeltme: PST/MAPI yoluyla gelen 20 ayda (2024-01 → 2025-08) başlık dosyalarında satır
  aralarında boş satır var; ayrıştırıcı ilk boş satırda durup tarih/kimden/kime/konuyu boş
  bırakıyordu. İlk tam indekste 76.318 mail (%52) üst verisiz yazıldı → tarih süzgeci bu
  mailleri dışlamıyordu, anlamsal metinde konu eksikti. Boş satırlar atılarak ayrıştırılıyor.
- Artımlı indeksleme tarihi boş kayıtları da yeniden dener; onarım `--tumu` ile yapıldı.
- İlk tam indeks doğrulaması: 146.036 mail (143.366 .txt + 2.670 .eml) = dosya sayısı;
  SQLite, FTS ve Chroma'da 179.537 parça eşit; 32 ay, 242 dk.

## v1.0.0 — 2026-10-13

- İlk sürüm. Ortak'ın kararıyla ("bu sistemi kuralım, maillerde çok işime yarayacak"),
  Ağustos 2026 denemesinin (5.663 mail, Chroma + sentence-transformers) ardından kuruldu.
- Hibrit arama: Chroma (multilingual-e5-small, resmi ONNX; torch yok, açılış ~2 sn) +
  SQLite FTS5 (Türkçe katlama, önek eşleşmesi) + kimden/kişi/tarih süzgeci, RRF birleştirme.
- ONNX çıktısı sentence-transformers ile eşdeğer doğrulandı (7 metinde kosinüs ≥ 0,9997).
- Artımlı indeksleme: yeni/değişen/silinen gövde mail düzeyinde izlenir; kilit dosyası.
- Kapsam: gövde + başlık. Ekler ikinci aşamaya bırakıldı (Ortak'ın 2026-10-13 kararı).
- Arşiv kimlik denetimi: 143.366 gövdede çakışan mail kimliği yok (2026-10-13).
- Ham `.eml` gövdeler (arşivin ~%2'si, 2.670) e-posta ayrıştırıcıyla okunur; HTML düz metne çevrilir.
- `--tumu` en yeni aydan başlar; indeksleme süresince Windows boşta uykusu ertelenir.
- int8 nicemleme ölçüldü (3–4× hızlı, ilk 10 örtüşme 5–9/10) ve kalite gerekçesiyle reddedildi.
- Ölçüm: hibrit sorgu 2,7 sn (açılış dahil); "Gördes GES arazi tapu sorunu" ilk 12'nin 12'si isabetli.
