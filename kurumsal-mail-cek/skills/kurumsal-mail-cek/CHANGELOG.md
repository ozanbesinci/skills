## 1.3.0 — 2026-10-24

- Kalıcı sayfa commit/kurtarma, PST kopya+envanter kapısı, kaynak türü ve güncel doğrulama kimliği; MIME/tarih/kanıt düzeltmeleri ve sentetik regresyonlar.
- Gerçek arşiv/indeks/PST üzerinde geçiş veya aktarım çalıştırılmaz; eski indeks nesli için açık geçiş gerekir.

# Sürüm Geçmişi — kurumsal-mail-cek

## v1.2.2 — 2026-10-22

- Vault klasörünün `D:\MySecondBrain` adına (yalnız harf değişikliği) geçişi için SKILL.md ve `references/cevrimici-arsiv.md` içindeki script yolları yeni yazıma çevrildi. Windows yolları harfe duyarsız olduğundan davranış değişmedi; script'ler değiştirilmedi, aktarım çalıştırılmadı.

## v1.2.1 — 2026-10-16

- Ekim PST envanterinde görülen 96 Gelen Kutusu mailinin eksik kalmaması için MAPI aktarımına yalnız ana Gelen Kutusu eklendi; alt klasörler ve 08_Gmail hariç kalır.
- İçinde bulunulan ayın MAPI raporu `AY_ICI_KISMI` olarak etiketlenir; kaynaktaki kapsam içi maillerin en erken/en geç tarihi özete eklenir.
- Özette yeni gerçek mail sayısı, işlenen toplam öğeden ayrıldı; takvim öğeleri yeni mail sayısına eklenmez ve artımlı/kesinti devamında önceki CSV sayısı düşülür.

## v1.2.0 — 2026-10-16

- Varsayılan başlangıç, `D:\AI-BACKUP\pst` altındaki bütün PST'lerin sırayla işlenmesi oldu; çıktı mevcut `C:\Users\ozanbesinci\Drive'ım\maillerim` yıl/ay düzenine artımlı eklenir.
- PST aktarımı ve doğrulama sonrası arama indeksi güncellenir, işlem biter. Canlı Outlook/Graph çekimi yalnız ayrıca istendiğinde kullanılır; genel çağrıda önceki ay kendiliğinden seçilmez.
- Eski koşu sayıları, maliyet/hata hikâyeleri, kurulu sürüm varsayımları ve yinelenen açıklamalar kaldırıldı. Canlı çekim ayrı referansa toplandı.
- Kaynak PST koruması, hash eşliği, envanter kapısı, ek/kayıt bütünlüğü, artımlı devam ve indeks kontrolü korundu. MAPI'nin tek ay/klasör ve kimlik sınırları açıklandı; eski referanstaki Message-ID ile öğe atlama önerisi düzeltildi.
- Exporter ve parser betikleri değiştirilmedi; bu düzenlemede mail aktarımı çalıştırılmadı.

Bu skill 2026-10-14'e kadar numaralı sürüm tutmuyordu; önceki değişiklikler SKILL.md'nin
tarihli bölümlerinde (ör. "COM ERİŞİMİ — yasak KALDIRILDI, 2026-08-31") kayıtlı. Bu ilk
numaralı giriştir.

## v1.1.0 — 2026-10-14

- Akışa **adım 5** eklendi: kontrol GEÇTİ ise çekilen ay `mail-ara` indeksine
  `indeksle.py --ay YYYY-AA` ile eklenir (Ortak'ın 2026-10-14 talimatı). BAŞARISIZ ay
  indekslenmez; kilit dosyası varken ikinci indeksleme başlatılmaz.
- "Analiz katmanı" bölümündeki "`indeksle.py` (yazılacak)" notu, var olan `mail-ara`
  skill'ine bağlandı.
- Exporter betiklerine dokunulmadı.
