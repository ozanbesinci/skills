# Program ve ortam bileşenleri

Tüm programlar [seçim paneli](../SKILL.md) üzerinden yönetilir. Betikler panelin
ilk taramasında `-YalnizBul` veya `--yalniz-bul` ile çağrılır. Bu aşamada kurulum
ve ayar değişikliği yapılmaz. Kullanıcının **Güncelle** düğmesine basması, yalnız
işaretli satırların kurulumuna izin verir.
Eksik bileşen “Yüklü değil” olarak gösterilir; eksik ve eski bileşenlerin
kutuları varsayılan işaretlidir. Bütün satırlar doğrulanmış biçimde güncelse
tablo açılmaz. Güncelle tıklamasında seçim penceresi kapanır; betik seçilenleri
tamamlayıp sıralı sonuç verisini `@@SONUC` ile döndürür.

| Panel satırı | Sürüm kaynağı | Kurulum betiği |
|---|---|---|
| Python | python.org, desteklenen serinin son kararlı yaması | `scripts/python-kur.ps1` |
| Python kütüphaneleri (12) | Skill içinde sabit sürüm ve PyPI SHA-256 özetleri | `scripts/kurulum-testi.py` |
| Node.js LTS | nodejs.org, son LTS | `scripts/node-kur.ps1` |
| pnpm | npm `latest` kararlı etiketi | `scripts/pnpm-kur.ps1` |
| DuckDB | PyPI, seçilen Python ile uyumlu son sürüm | `scripts/python-paket-kur.py duckdb` |
| Power BI Modeling MCP | Microsoft Marketplace, son kararlı sürüm | `scripts/powerbi-mcp-kur.ps1` |

Python kütüphaneleri tek set olarak seçilir. Sürüm sütunundaki “12 paket · sabit set”,
skill ile doğrulanan paket sürümlerini temsil eder; internetin en yeni sürümleri
olduğu iddia edilmez. Yüklü/ hedef paket sürümleri satır ipucunda görünür.
`kurulum-testi.py` indirilen her dağıtımın özetini doğrular ve kütüphaneleri
gerçek işle sınar. Python veya Node.js gerektiren satırlar, bağımlılık satırı
seçilmemiş ve bilgisayarda mevcut değilse **hata** ile biter; diğer seçili
satırlar devam eder.

Kurulum veya kontrolü gerçekten engelleyen açık kullanıcı programları,
mevcut kural uyarınca önce normal, gerekirse zorla kapatılır; yalnız açık
olmaları kapatma gerekçesi değildir. Güvenlik politikası, ağ veya yetki engeli
atlatılmaz. Power BI sunucusu kurulumdan önce çalıştırılarak doğrulanır, sonra
Codex ve Claude ayarlarına bağlanır. Kullanım sözleşmesi kullanıcı adına
onaylanmaz. Betiklerin `@@SONUC` içindeki `it_isi`, `ozet`, `neden` ve `rapor`
alanları hata ve uyarı yorumunun kaynağıdır.
Alt süreç çıktıları UTF-8 olarak okunur. Sıfır olmayan çıkış kodu, eksik sonuç
ve kurulum sonrası sürümün doğrulanamaması başarı sayılmaz. Tamamlanan işlemde
hedef sürüme ulaşılamadıysa uyarı gösterilir; uzun ayrıntılar sonuç hücresinin
ipucunda ve varsa betiğin raporunda bulunur.

İnternet veya sürüm kaynağı erişilemezse panel o satırı “Kontrol edilemedi”
gösterir; bilinen eski sürüm güncelmiş gibi sunulmaz. Kurulum yapılmış her
satırın son durumu sohbet tablosuna aktarılacak sonuç kaydında bulunur.
