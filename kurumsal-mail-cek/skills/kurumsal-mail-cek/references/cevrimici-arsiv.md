# Canlı Outlook/Graph çekimi

Bu yol yalnız kullanıcı canlı posta kutusundan çekim veya güncelleme istediğinde
kullanılır. `kurumsal-mail-cek` becerisinin varsayılanı PST aktarımıdır; PST yokluğu
veya PST aktarımının bitmesi canlı çekimi kendiliğinden başlatmaz.

## Kaynak seçimi

- Birincil posta kutusu: `scripts/mail_export.py` ile Graph, yalnız `Mail.Read`.
- Çevrimiçi Arşiv (In-Place Archive): `scripts/mail_export_mapi.py` ile klasik
  Outlook COM/MAPI. Graph bu ayrı arşiv posta kutusunu göstermez.
- MAPI birincil kutunun yerel önbelleğine dayanabileceğinden, canlı birincil kutu
  çekiminde Graph yerine kullanma. Graph'taki sıfırı arşivde mail yok diye yorumlama.
- COM kullanımı serbesttir; Outlook kapatılmaz veya yeniden başlatılmaz. Çevrimiçi
  Arşiv önbelleklenmez: sayımda `GetTable` kullanılır, içerik gerektiğinde açılır.
  Outlook yeniden başlarsa bağlantı kesilebilir; aynı ayda artımlı devam edilir.

## Ay seçimi

Açık tarih/ay verilmişse onu kullan. Kullanıcı ayrıca **canlı aylık rutin** istemiş
ve ay belirtmemişse bir önceki tamamlanmış takvim ayını `Europe/Istanbul` ile seç.
Mevcut ay istendiyse ayın 1'inden bugüne kadar çek. Genel beceri çağrısını bu rutin
sayma. Ayın 3'ü eski aylık rutinin günüdür; zamanlanmış görev ayrıca istenmedikçe
kurulmaz.

`--tamamlayici-tarama`, canlı aylık rutin ve mevcut ay güncellemesinde açıktır;
geriyedönük tek ay doldurmada kapalıdır. Önceki üç aya ait mevcut aylık arşivleri
yeniden sayar, yeni mesajları ekler; eksik eski ay klasörlerini kendiliğinden açmaz.

```powershell
$graphExporter = 'D:\MySecondBrain\skills\kurumsal-mail-cek\scripts\mail_export.py'
# $ay kullanıcının canlı çekim isteğine göre belirlenir.
py -3 -u $graphExporter --ay $ay --tamamlayici-tarama
# Geçmiş tek ay doldurma:
py -3 -u $graphExporter --ay $ay
```

Çevrimiçi Arşiv için `mail_export_mapi.py --ay $ay` kullanılır; `--pst` verilmez.
Kaynak erişimi yoksa bunu bildir; farklı kaynağın eksik kapsamıyla başarı iddia etme.

## Kimlik ve devam

- Graph kimliği MSAL device-code ile mevcut `Kilic_365` uygulamasıdır; token yerel
  önbellekte tutulur. `Mail.Read` dışında izin istenmez; uygulama kimlikleri kodun
  içindedir. Yeniden giriş gerekirse betiğin istediği device-code adımını bildir;
  token veya cache içeriğini sohbete dökme.
- Aylık modda `--ay YYYY-MM` kullan; her çalıştırma canlı listeyi tazeler ve mevcut
  Graph `mesaj_id` kayıtlarını korur. Kesintide bekleyen sıra numaralarıyla devam eder.
- `--baslangic`/`--bitis` yalnız aylık olmayan özel aralık içindir; var olan özel
  aralıkta `--devam` kullan. Var olan EML'yi yeniden indirme; baştan çekim yapma.
- HTTP hata/429 bekleme ve bir onarım turu betiğin işidir. Eksik kayıt gizlenmez;
  final kontrol başarısızsa nedeni teşhis edilir.

## Son kontrol

`SKILL.md` içindeki kapsam, çıktı düzeni ve bütünlük kuralları geçerlidir.
Graph kimliği ile MAPI/PST EntryID aynı anahtar değildir; internet Message-ID
üzerinden farklı öğeleri otomatik atlama. Mükerrer kopyaların klasör bilgisi korunur.

Yalnız aynı koşunun `_aktarim.json` ve `kontrol.txt` sonucu GEÇTİ ise
`mail-ara/scripts/aktarim_indeksle.py --ay YYYY-MM` ile üç aşamalı teslim yap.
Graph ve MAPI ayı arasında otomatik kaynak geçişi yoktur. Tamamlayıcı taramada
etkilenen ayları `_tamamlayici_sonuc.json` üzerinden ayrı raporla ve başarılı ayları
indekse ver. Rapor kapsam bitişini, `AY_TAMAM`/`AY_ICI_KISMI` durumunu, eklenen/toplam
maili, gerçek ek sayısı/GB'ını, atlananları ve süreyi çıktıdan alır.
