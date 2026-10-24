# Güvenli devam ve sürüm geçişi

## Yeni koşular

`_islem.json` sayfa işlem günlüğüdür. PREPARED ise CSV ekleme sınırları, JSON'lar
ve o sayfanın çıktıları geri alınır; ham EML'ler korunur. COMMITTED ise yalnız
ham temizlik tamamlanır. Günlük ve ham dosyaları elle silme. Yeni koşuyu aynı
ay/kaynakla başlat; tamamlanmış sıra+EntryID hash makbuzu varsa yeniden yazılmaz.
Bozuk JSON veya farklı Graph/MAPI kaynak türü açık hata üretir; boş sayılmaz.
Kilitler kendiliğinden zaman aşımına uğramaz. Kilidi kaldırmadan önce PID sahibinin
durduğunu doğrula. Uzak hostta eşzamanlı yazıcıya karşı yerel dosya kilidi yeterli değildir;
aynı senkron arşivi farklı bilgisayarlarda eşzamanlı işletme.

## Eski kayıtlar

Eski, sağlam kayıtlar yerinde kalır ve güncel kontrolle yeniden değerlendirilir.
Yeni koşunun arşiv fingerprint'i eski dosyaların o andaki baytlarını da kapsar;
bu, geçmişteki ilk PST/MIME dönüşümünün doğru yapıldığını geriye dönük kanıtlamaz.
Eski yarım kayıtta CSV satırı bulunup yeni işlem günlüğü/hash makbuzu bulunmuyorsa
otomatik çoğaltma yapılmaz. CSV/ek eksikliği somut kanıtla ayrı onarım ister;
pending dosyasını sıfırlayarak veya CSV'ye elle satır ekleyerek devam etme.
Eski anomali uyarısının kanıtı MIME kimliği/türü/sayısı ve SHA-256 ile doğrulanmalıdır.
Yalnız dosyanın varlığı veya eski GEÇTİ yeterli değildir.

## İndeks nesli

`mail-ara` gövde, ek çıkarma ve ek indeks aşamalarının kod/paket/Python sürümlerini;
vektör aşamalarında model.onnx ve tokenizer.json SHA-256 değerlerini kaydeder.
Sürüm kimliği olmayan dolu indeks veya değişen nesil karışımı açık hata üretir.
Eski neslin dosyalarını silme, nesil JSON'unu elle değiştirerek kapıyı aşma.

Geçiş ayrıca yürütülecek bir arşiv/indeks işlemidir. Kullanıcı geçişi istediğinde
ayrı bir `MAIL_INDEKS_KOK` belirle; mevcut model/onnx dosyalarını bu kökün
model/onnx dizinine kopyala (indeks/SQLite/Chroma dosyalarını kopyalama).
Aynı `MAIL_ARSIV_KOK` arşivini kullan. Doğrulanan ayları gövde → ek çıkarma → ek
indeksi sırasıyla yeni kökte üret. Yeni kök v2 koleksiyonunu açar. Eski indeks
korunur. Üç aşamanın güncel teslim makbuzları ve kapsama sayıları doğrulandıktan
sonra arama süreçlerini de yeni MAIL_INDEKS_KOK ile başlat. Aynı nesilde tekrar
çalıştırma artımlıdır. Paket/model indirimi veya mevcut indeksin otomatik taşınması yoktur.

Ek çıkarma PDF/XLSX/XLSM/DOCX ile sınırlıdır; taranmış PDF için OCR yoktur.
Kaynak dosyanın saklanmış olması her ekin aranabilir metni olduğu anlamına gelmez.
Makbuzdaki çıkarma durumlarını (ok/metin_yok/sifreli/bozuk/hata) raporla;
`hata` teslimi durdurur. `--durum` tek başına teslim kanıtı değildir.

## Yerel regresyonlar

Gerçek PST/Outlook/Graph/arşiv kullanılmadan:

```powershell
python -B -m unittest discover -s "<skill-folder>\tests" -v
```

Testler sentetik MIME, geçici SQLite, sahte COM/Chroma/gömücü kullanır.
Üretim kabulü, gerçek Outlook sağlayıcısı ve büyük veri performansı bu testlerin kapsamı dışındadır.
