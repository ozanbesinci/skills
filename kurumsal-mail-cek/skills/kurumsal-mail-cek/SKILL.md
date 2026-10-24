---
name: kurumsal-mail-cek
description: D:\AI-BACKUP\pst içindeki PST dosyalarını sırayla ayrıştırıp kurumsal mailleri C:\Users\ozanbesinci\Drive'ım\maillerim altında mevcut yıl/ay düzenine aktarır; doğrulama sonrası mail-ara indeksini günceller. Canlı Outlook/Graph çekimi ve eski arşiv onarımı yalnız ayrıca istendiğinde kullanılır.
---

# Kurumsal mail çekme

**Varsayılan iş: PST → aylık arşiv → doğrulama → arama indeksi → bitiş.**
Bu beceri tek başına çağrıldığında ilk iş `D:\AI-BACKUP\pst` içindeki `.pst`
dosyalarını bulmaktır. Önceki ayı kendiliğinden seçme; canlı Outlook/Graph taraması
başlatma. Bu sıra Ozan'ın 16.10.2026 tarihli açık tercihidir.

Mailleri özetlemez veya sınıflandırmaz; farklı işlerde kullanılacak veri setini
hazırlar. Bütün ayrıştırma yerel betiklerle yapılır; mail gövdeleri modele yüklenmez.

## 1. PST dosyalarını bul ve sıraya al

```powershell
Get-ChildItem -LiteralPath 'D:\AI-BACKUP\pst' -Filter '*.pst' -File -Recurse |
    Sort-Object FullName
```

- Bulunan bütün kaynak PST'leri sırayla işle. Paralel exporter veya alt ajan çalıştırma.
- PST yoksa bunu bildir ve bitir; canlı posta kutusuna kendiliğinden geçme.
- Dosya adını ayın kanıtı sayma; gerçek tarih ve klasör kapsamını envanterle doğrula.
  Birden çok PST aynı aya aitse aynı aylık arşive sırayla artımlı devam et.
- Kaynak PST'leri değiştirme, silme, taşıma veya yeniden adlandırma. Outlook'u kapatma
  veya yeniden başlatma. Her kaynağın SHA-256 özeti ve eşleşen çalışma kopyasıyla çalış.

Çalışma kopyası ve koşu kanıtları arşiv kökündeki `_pst-calisma/<kosu>/` altında
kalır; kopyayı kaynak PST klasörüne koyma. Kaynak ve kopyanın SHA-256 değerleri
Outlook'a bağlamadan önce eşit olmalıdır. Kaynak değişiyorsa kararlı kopya almadan
aktarıma başlama.

## 2. Mevcut yıl/ay düzenini koru

Arşiv kökü: `C:\Users\ozanbesinci\Drive'ım\maillerim`.
Örnek hedef: `2026/ekim-2026/`.

- Ay adları ASCII Türkçedir: `ocak`, `subat`, `mart`, `nisan`, `mayis`, `haziran`,
  `temmuz`, `agustos`, `eylul`, `ekim`, `kasim`, `aralik`.
- Aynı ay varsa soru sormadan artımlı devam et; kayıtları silme veya baştan yazma.
  Kaynakta artık bulunmayan eski mailler de yerelde korunur.
- Aynı ay eski düz kökte bulunuyorsa orada devam et. Hem düz kökte hem yıl altında
  varsa ya da eski tarih kodlu aylık klasör varsa arşivi bölmeden çakışmayı bildir.
- Ay içi PST de aynı aylık klasöre gider. Kaynakta görülen tarih aralığını raporla;
  PST adından veya ayın geçmiş olmasından tam ay olduğu sonucunu çıkarma.

```text
<yıl>/<ay-yıl>/
├── mailler.csv       Mail kayıtları
├── ekler.csv         Ek kayıtları
├── govdeler/         Gövde metinleri; gerekirse korunmuş EML
├── basliklar/        İnternet başlıkları
├── ekler/            Gerçek dosya ekleri
├── ozet.txt          Koşu özeti
├── kontrol.txt       Doğrulama hükmü
└── _*.json, _gecici/, ham/   İlerleme, kaynak kimlikleri ve geçici veriler
```

Aylar birleştirilmez. Çıktı, geçici çalışma ve onarım verisi bu kökün dışına
ancak kullanıcı açıkça başka bir çıktı kökü seçerse yazılır. Mail verisini vault'a
ve eski `D:\AI-BACKUP\maillerim\*.db.gz` arşivlerine yazma. Arama indeksi aşağıda
belirtilen ayrı yerde tutulur; beceri düzenlemesi ve hafıza kayıtları vault'ta kalır.

## 3. Kapsamı doğrula ve PST'den aktar

**Dahil:** `Arşiv` ve alt klasörleri; `Gelen Kutusu` yalnız ana klasör;
`Gönderilmiş Öğeler`.

**Hariç:** `Arşiv\08_Gmail` ağacı, Gelen Kutusu alt klasörleri, Taslaklar,
Silinmiş Öğeler, Gereksiz E-posta ve toplantı davetleri/kabul-red öğeleri.
Kapsam dışı Outlook öğeleri `_atlanan.json` ile sayımda açıklanır.

Tarih: Arşiv/Gelen Kutusu için alınma, Gönderilmiş Öğeler için gönderilme zamanı;
ay sınırları `Europe/Istanbul` takvimidir.

Mevcut araç `scripts/mail_export_mapi.py` ve klasik Outlook COM/MAPI'dir.
COM kullanımı serbesttir. Betik verilen PST'yi kendisi `_pst-calisma/` altına
kopyalar, kaynak/kopya SHA-256 eşitliğini kontrol eder ve yalnız kopyayı bağlar.
Kaynak hash'ini sonunda yeniden kontrol eder. `--bagli-pst-kullan` artık reddedilir;
bağlı kaynak PST üzerinde çalışılmaz. Oluşturulan kopya ve kanıt kendiliğinden silinmez.

Ayı belirlemek için tam envanter al; aktarım aynı kapıyı kendi kopyasında yeniden uygular:

```powershell
$exporter = 'D:\MySecondBrain\skills\kurumsal-mail-cek\scripts\mail_export_mapi.py'
# $kaynakPst: sıradaki kaynak dosyanın tam yolu; $ay: envanterle doğrulanan YYYY-MM
python $exporter --ay $ay --pst $kaynakPst --tam-pst-envanter
python -u $exporter --ay $ay --pst $kaynakPst --gomulu-metadata
```

- Envanter kapsam filtresi olmadan bütün klasör/sınıfları, mail ve mail dışı öğe
  sayılarını, en erken/en geç tarihleri, tarihsiz ve ay dışı mailleri doğrular.
  Kapı geçmeden mail/ek/CSV yazılmaz; eski koşuların sayılarını başka PST'ye taşıma.
  Yeni koşu eski teslimi baştan geçersiz kılar; kapı hatası güncel BAŞARISIZ sonucudur.
- Mevcut CLI tek aylık kapı uygular; MAPI exporter `Arşiv`/`Gönderilmiş Öğeler`
  yapısını bekler; Gelen Kutusu varsa yalnız ana klasörü tarar. Çok aylı PST veya bu yapıya uymayan
  kaynakla karşılaşılırsa bir ayı/klasörü sessizce dışlama. Tam kapsamı işleyecek
  araç uyarlaması yapılmadan aktarımın eksiksiz olduğunu söyleme.
- MAPI artımlı anahtarı PST `EntryID`'sidir. Aynı internet Message-ID'ye sahip
  farklı öğeleri silme veya atlama; mükerrer bilgisi CSV'de korunur. Farklı PST
  kopyaları veya Graph kimlikleri arasında otomatik tekilleştirme varmış gibi davranma.
- Kesintide aynı kaynak ve aylık hedefle devam et. `_bekleyen.json` içindeki
  sıra numaralarını koru; önce yarım kayıtları tamamla, sonra yenilere geç.

Tek betik sürecini başlat ve sonucunu izle; aynı CSV'ye ikinci süreç yazdırma.
Bir kaydın hatası gizlenmez; kalan kayıtlar işlense bile final hüküm belirleyicidir.

## 4. Doğrula ve kısa raporla

`kontrol.txt` ile aynı koşunun `_aktarim.json` kaydı **GECTI** olmadan
indeksleme. İndeks betikleri koşu kimliği, bekleyen işlem ve arşiv içerik hash'ini
kendileri denetler. Geçmiş ay PST'si için `KAYNAK_KAPSAMI_TAMAMLANDI` yalnız
verilen kaynağın işlendiğini söyler; takvim ayının eksiksizliği anlamına gelmez. BAŞARISIZ ise somut eksik/hata sayısını ve nedenini bildir; eski
GEÇTİ kaydını güncel doğrulama yerine kullanma.

Her PST/ay için yeni eklenen ve toplam mail sayısını, gerçek ek sayısını ve GB'ını,
atlananları, kaynak tarih aralığını, kontrol hükmünü ve süreyi çıktıdan raporla.
Sayıları `_durum.json`, CSV'ler, `ozet.txt` ve `kontrol.txt` üzerinden al.

## 5. Mail arama indeksini güncelle ve bitir

Yalnız GEÇTİ diyen aylar için `mail-ara` becerisini kullan. İndeks artımlıdır;
arşive yazmaz, `D:\AI-BACKUP\mail-indeks` altında tutulur.

```powershell
$indeksPython = 'D:\AI-BACKUP\mail-indeks\.venv\Scripts\python.exe'
$indeksleyici = 'D:\MySecondBrain\skills\mail-ara\scripts\aktarim_indeksle.py'
& $indeksPython -I $indeksleyici --ay $ay
```

- `D:\AI-BACKUP\mail-indeks\index\indeksle.kilit` varsa ikinci indeksleyici başlatma;
  süren işi bekle. Kilidi süreç kontrolü yapmadan silme.
- Sarmalayıcı gövde → sistem Python'u ile ek çıkarma → ek indeksi sırasını uygular.
  Üç aşama aynı koşu ve nesle bağlıysa `INDEKS_TESLIM: TAMAMLANDI` yazar;
  makbuz indeks kökünde `index/aktarim/<YYYY-MM>.json` dosyasındadır.
- İşlenen her ayı indekse sırayla ver; raporda indekslenen ayı ve yazılan mail
  sayısını belirt. Başarısız indekslemeyi tamamlandı diye sunma.
- Ardından bitir. Canlı Outlook/Graph tamamlayıcı taraması veya zamanlanmış görev
  kendiliğinden başlatılmaz.

## Veri bütünlüğü kuralları

- Canlı mail taşınmaz, silinmez, değiştirilmez veya okundu işaretlenmez. MAPI'de
  bu davranış betik sözleşmesidir; Graph'ta ayrıca yalnız `Mail.Read` kullanılır.
- Gerçek eklerde boyut üst sınırı yoktur. Yalnız `image/*` tipindeki, inline veya
  Content-ID taşıyan **200 KiB (204.800 bayt) altı** görseller gömülü sayılır; `attachment`
  işaretli parçalar gömülü kabul edilmez. Atlanan görseller metadata olarak korunur.
  Eski arşivde indirilmiş gömülü görselleri silme.
- Gövdede zengin sürüm seçimi, başlık ve ek ayrıştırması `mail_yaz.py`'nin işidir.
  CSV'ye elle satır ekleme veya parser yerine kestirme ayrıştırıcı kullanma.
- Ham EML, gövde/ekler + iki CSV + durum + `_kayitlar/<sira>.json` hash makbuzu
  kalıcı commit edilince silinir. `_islem.json` varsa önce kurtarılır. Şifreli veya
  gövdesiz mail `govdeler/` altında EML olarak; okunabilir imzalı MIME'ın ham hali
  `sorunlu_eml/` altında korunur. Normal mailin takvim eki gerçek ek olarak saklanır.
  MAPI'nin yeniden kurduğu EML kriptografik imza sadakatini kanıtlamaz.
- Kaynaktaki U+FFFD veya 0-byte eki uydurarak düzeltme; ham kanıtla raporla.
- CSV: `utf-8-sig`, `;` ayırıcı, çoklu alanlarda ` | `; tarihler `YYYY-MM-DD HH:MM`,
  boolean alanlar `evet`/`hayir`. Kolonların tek kaynağı `mail_yaz.py`'dir.
- Dosya adlarını betikler üretir: EML `<YYYYMM>-<5 hane>.eml`; Windows yasak
  karakterleri ve ayrılmış adları temizlenir, ek adı çakışınca `-2`, `-3` eklenir.

Kesinti, eski yarım kayıt ve indeks nesli geçişinde [güvenli devam rehberini](references/guvenli-devam.md) oku.

## Yalnız ayrıca istendiğinde kullanılan yollar

- **Canlı Outlook/Graph çekimi:** [canlı çekim rehberini](references/cevrimici-arsiv.md)
  oku. Varsayılan PST aktarımının devamı değildir.
- **Geçmiş arşiv onarımı:** [onarım rehberini](references/repair.md) tamamen oku;
  normal çekimle karıştırma. Bu rehber Graph kimlikli arşivler içindir.
- **İçerik analizi/arama:** ayrı `mail-ara` becerisidir; toplu gövdeleri modele okutma.
