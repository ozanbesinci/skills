---
name: guncelleyici
description: Python, Python kütüphaneleri, Node.js, pnpm, DuckDB, Power BI Modeling MCP ve teklif-degerlendirme skill sürümlerini tek seçim panelinde karşılaştırır; işaretlenenleri günceller. "Güncelleyiciyi çalıştır", "programları güncelle" veya "teklif skill'ini güncelle" isteklerinde kullan.
---

# Güncelleyici

## Tek giriş: seçim paneli

Windows PowerShell 5.1 ile `scripts/panel.ps1` çalıştır. Önce sürüm taraması
yapılır; işlem gerekiyorsa kullanıcının görebileceği etkileşimli pencere açılır.
Skill yolu, bu dosyanın bulunduğu klasörün tam
yoludur; geliştirme bilgisayarına ait sabit yolu başka makinede kullanma.

```powershell
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "<SKILL>\scripts\panel.ps1"
```

Başlangıçta eski `program-guncelle` / `program-guncelleme` skill kurulumu
standart kullanıcı skill yollarından kaldırılır. Junction ise yalnız bağlantı
kaldırılır; fiziksel eski skill doğrulandıktan sonra kullanıcı alanındaki
karantinaya taşınır. Yeni `guncelleyici` ve hedef skill ağacına bu temizlikte
dokunulmaz.

Panel ilk olarak bilgisayardaki yüklü sürümleri ve çevrimiçi güncel kararlı
sürümleri salt okuma seçenekleriyle denetler. `teklif-degerlendirme` sürümü
GitHub'daki doğrulanmış Release paketinin manifestinden okunur. İnternet
doğrulaması yapılamayan satır “Kontrol edilemedi” gösterir; sürüm uydurulmaz.
Bu durumda satırın durum sütunu ağ erişimi engelini belirtir; ayrıntılı hata
satır ipucunda ve işlem sonucunda korunur. Gerçekten yüklü olmayan bileşenin
yüklü sürüm hücresi **Yüklü değil** olur; seçilirse güncel kararlı sürüm kurulur.
Eksik ve eski bileşenler **varsayılan işaretli** gelir; kullanıcı seçimleri
değiştirebilir. Güncel veya güncelliği doğrulanamayan satırlar işaretlenmez.
Tüm bileşenler yüklüyse ve hedef sürümlerle eşleşiyor veya onlardan ilerideyse
pencere açılmaz: yalnız **Güncelsiniz.** denir ve bitirilir. Bir satırın kontrolü
başarısızsa bu kısa çıkış kullanılmaz.
Python kütüphaneleri bir set olarak
listelenir; o satır seçilirse 12 desteklenen paket birlikte kurulur ve sınanır.
Power BI MCP de aynı varsayılan seçim kuralına tabidir. Başka bir
başlangıç onayı veya ayrı Power BI sorusu sorma.

Kullanıcı alttaki **Güncelle** düğmesine bastığında seçim penceresi hemen
kapanır; yalnız işaretli satırlar arka planda ekrandaki sırayla işlenir.
Varsayılan tikler tek başına kurulum başlatmaz. Bağımlılık seçimini kullanıcı
kaldırabilir: Python gerektiren
satırlarda Python yoksa veya pnpm için Node.js yoksa ilgili satırın sonucu
açık hata olur. Betiğin tamamlanmasını bekle; çıkan `@@SONUC` JSON kaydındaki
`results` ve `rows` ile **sohbette sıralı son durum tablosu** göster. Seçim
penceresini tekrar açma. Seçilmeyen adaylar “Atlandı · seçilmedi” olarak kalır.
Güncel, yayından yeni ve kontrol edilemeyen satırların durum bilgisi korunur.
Komutu izlenemeyen bağımsız bir süreç olarak bırakma; doğrudan çalıştır veya
`Start-Process -Wait` ile çıktısını al. Pencerenin kapanması kurulumun bittiği
anlamına gelmez; süreç bitene kadar sonucu izle. Kullanıcı Güncelle'ye basmadan
pencereyi kapatırsa `status: cancelled` döner ve kurulum yapılmaz. Betiklerin nihai
`@@SONUC` kayıtları, süreç çıkış kodu ve kurulum sonrası sürüm sonucu belirler.
Paneli güncelleme düğmesine kullanıcı
yerine basarak geçme.

Kurulumlar yalnız kararlı yayınları kullanır. Var olan betiklerin imza, SHA-256,
geri dönüş, kullanıcı alanı, süreç engeli ve IT raporu kuralları korunur.
Uygulama ayrıntıları: [program ve ortam](references/program-kurulumu.md),
[teklif paketi](references/teklif-paketi.md).

Sonraki sürüm değişiklikleri ve GitHub yayınları ayrı kullanıcı talimatıyla
yapılır; yerel geliştirme kayıtları `CHANGELOG.md` içinde “Yayımlanmamış”
altında tutulur.
