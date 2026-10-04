# Güncelleyici

Windows üzerinde Python, desteklenen Python kütüphaneleri, Node.js, pnpm,
DuckDB, Power BI Modeling MCP, isteğe bağlı DuckDB PDF eklentisi ve
`teklif-degerlendirme` skill sürümlerini ChatGPT Desktop Work/Codex sohbetinden
yöneten skill.

**Güncel kaynak sürüm:** 2.2.0  
**Kaynak yolu:** `skills/guncelleyici/`  
**GitHub Release:** `v2.2.0` (`skill.zip` + `skill.zip.sha256`).

> 2.2.0 kaynak ve GitHub Release olarak yayımlanmıştır; `BUILD.json` içindeki
> `production_approved=false` korunur. Düzeltilmiş Windows PowerShell 5.1 kabul
> testi, gerçek kurucular/Authenticode, Excel COM, Power BI native MCP ve DuckDB
> PDF native kabul adımları henüz PASS olarak işaretlenmemiştir.

## Kurulum ve kullanım

ChatGPT Desktop Work/Codex, bu depodaki `skills/guncelleyici/` yolunu skill olarak
kullanmalıdır. Kaynak sürüm `VERSION` ve `BUILD.json` ile doğrulanır.


Normal kullanıcı Terminal/PowerShell açmaz. ChatGPT Desktop Work veya Codex'te:

**“Güncelleyiciyi çalıştır”**

isteği verilir. Skill yerel komutları kendi araçlarıyla arka planda yürütür ve
sürüm/seçim tablosunu sohbette gösterir. Seçimi değiştirmek kurulum yetkisi
değildir; ancak kullanıcı açıkça **“Güncelle”** / **“bu seçimleri uygula”** dediğinde
sabitlenmiş plan uygulanır.

## 2.2.0 öne çıkanları

- Pro denetimindeki Y1–Y7 ve O1–O7 güvenilirlik bulguları için kod ve regresyon
  kontrolleri.
- Değişmez kurulum planı, kilit altında yeniden doğrulama ve açık `-ConfirmApply`.
- Power BI MCP ayarlarında bilinmeyen alanları koruyan atomik yazım/rollback.
- Sürüm uygunluğu ile işlev sağlığının ayrılması; `verify` ve kontrollü `repair`.
- Python paket downgrade etkilerinin onay öncesi görünür olması ve bakım penceresi.
- Windows amd64/PowerShell 5.1 çalışma kapısı.
- İsteğe bağlı, varsayılan seçili olmayan DuckDB PDF bileşeni.
- Son kullanıcı için Work/Codex **chat-only** yüzeyi; terminal komutları yalnız ajan-içi
  yürütme veya geliştirici/BT kabul testi içindir.

## Doğrulama

- 110/110 çevrimdışı regresyon testi PASS.
- Skill validator PASS.
- Paket açıldıktan sonra 110/110 tekrar test PASS.
- Kaynak manifesti 42 dosyayı SHA-256 ile bağlar.

Çalıştırılmayan native Windows kabul adımları başarı olarak gösterilmez; ayrıntı için
`skills/guncelleyici/BUILD.json` ve
`skills/guncelleyici/references/TEST_RAPORU.md` dosyalarına bakın.

Kaynak: [`skills/guncelleyici/`](skills/guncelleyici/)  
Sürüm geçmişi: [`CHANGELOG.md`](skills/guncelleyici/CHANGELOG.md)
