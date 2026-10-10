# Güncelleyici

Windows'ta Python, sabit 12 Python paketi, Node.js, pnpm, DuckDB ve Power BI Modeling MCP sürümlerini Work/Codex sohbetinden yönetir. DuckDB PDF eklentisi isteğe bağlıdır. Teklif değerlendirme skill'ini kontrol etmez, kurmaz veya güncellemez.

**Kararlı kaynak sürümü 2.3.0** · **GitHub etiketi v2.3.0** · **Bağımsız paket: skill.zip + skill.zip.sha256**.

## Bu sürüm

- pnpm 12 yerel ikilisi doğru tespit edilir; yüklü kurulum “Yüklü değil” görünmez ve engellerin gerekçesi gösterilir.
- pnpm'nin ana ve Windows ikili paketleri plana URL/SHA-512 ile bağlanır. Gerçek geçici kurulum testi geçti; offline/ignore-scripts korumaları korunur.
- Teklif değerlendirme yönetimi kaldırıldı. Altı ana bileşen ve isteğe bağlı PDF satırı vardır.
- Paket manifesti, dosya eşleşmesi ve tekrarlanabilir ZIP üretimi doğrulanır.

## Doğrulama ve sınırlar

Windows PowerShell 5.1: 47 genel, 29 pnpm ve 21 tarama kontrolü PASS. Python: 78 PASS, 2 NOT_RUN; hata yok. Gerçek pnpm 12.9.1 geçici kurulumunda altı kontrol ve DuckDB PDF'nin imzalı yükleme/tek sayfa metin testi PASS.

`production_approved=false`: tüm kurulum/kurtarma hata matrisi, Excel COM, gerçek istemci entegrasyonu ve personel pilotu bu sürümle tamamlanmadı. PDF smoke testi Türkçe OCR veya gerçek tablo doğruluğu kabulü değildir. [BUILD](skills/guncelleyici/BUILD.json), [test kanıtı](skills/guncelleyici/references/RELEASE_TESTS_2.3.0.json), [test raporu](skills/guncelleyici/references/TEST_RAPORU.md).

## Kullanım

Work/Codex sohbetinde **“Güncelleyiciyi çalıştır”** de. Yerel tarama seçim tablosunu gösterir. Yalnız açık **“Güncelle / bu seçimleri uygula”** onayı verilen sabit plan uygulanır.

[Skill](skills/guncelleyici/SKILL.md) · [Sürüm geçmişi](skills/guncelleyici/CHANGELOG.md) · [Kabul/kurtarma](skills/guncelleyici/references/kabul-ve-kurtarma.md).

## Paket üretimi

Geliştirici, depo kökünden `python tools/build_release.py --out <çıktı-klasörü>` ile manifesti doğrulayarak deterministik ZIP üretir. Kaynak değişikliği sonrası manifesti yenilemek için ayrıca `--refresh-manifest` kullanır. Çıktı skill ağacının dışında tutulmalıdır.
