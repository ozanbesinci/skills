# Güncelleyici

Windows üzerinde Python, desteklenen Python kütüphaneleri, Node.js, pnpm,
DuckDB, Power BI Modeling MCP ve `teklif-degerlendirme` skill sürümlerini tek
sohbet tablosunda karşılaştıran masaüstü Work ve Codex skill'i.

**Güncel kararlı sürüm:** 2.1.0
**Kurulum paketi:** `guncelleyici-v2.1.0.zip` ve SHA-256 kaydı

## Kurulum

Codex'e veya Claude Code'a `ozanbesinci/guncelleyici` deposundaki
`skills/guncelleyici` yolunu kurmasını söyleyin. Elle kurulumda Release
paketindeki `guncelleyici/` klasörünü kullanıcı skill dizinine yerleştirin.
Paketin SHA-256 değerini yanında yayımlanan `.zip.sha256` dosyasıyla
doğrulayın.

## Kullanım

“Güncelleyiciyi çalıştır” isteğiyle skill önce yüklü sürümleri ve kararlı
yayınları kontrol eder. Eksik bileşenler **Yüklü değil** gösterilir;
yükleme veya güncelleme gereken satırlar varsayılan işaretli gelir. Kullanıcı
seçimleri değiştirebilir. Bütün bileşenler güncelse tablo açılmadan
**Güncelsiniz.** sonucu verilir. İnternet kontrolü başarısız olan satır
güncel kabul edilmez.

Kullanıcı sohbette **Güncelle** dediğinde seçilen işlemler sırayla tamamlanır
ve sonuç tablosu sohbette gösterilir. Bu yanıt verilmeden
kurulum başlamaz. `teklif-degerlendirme` güncellemesi yalnız o skill'i
değiştirir; kararlı paket `ozanbesinci/teklif-degerlendirme` Release
sayfasından SHA-256 ile doğrulanır.

Kullanıcı **Güncelle** dedikten sonra önceki `program-guncelle` ve
`program-guncelleme` kurulumları standart
kullanıcı yollarında doğrulanarak kaldırılır. `guncelleyici` kendi kaynağını
bu işlemde değiştirmez.

## Gereksinimler

- Windows PowerShell 5.1
- İnternet erişimi: python.org, PyPI, nodejs.org, npm kayıt deposu,
  Visual Studio Marketplace ve GitHub (yalnız seçilen bileşenler için)
- Sistem geneline kurulmuş uygulamaları değiştirmek için gerektiğinde IT yetkisi

Kaynak ve değişiklikler: [`skills/guncelleyici/`](skills/guncelleyici/),
[`CHANGELOG.md`](skills/guncelleyici/CHANGELOG.md).
