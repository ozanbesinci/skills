# Kurumsal Mail Çek 1.3.0

Windows üzerinde kaynak PST'yi koruyarak kurumsal mailleri aylık dosya arşivine aktarır;
güncel doğrulama sonrasında yerel mail arama indeksine teslim eder.

Bu sürüm kalıcı sayfa commit/kurtarma, MAPI hata yönetimi, MIME/ek/tarih doğruluğu,
hash bağlı kontrol ve üç aşamalı indeks teslim düzeltmelerini içerir.

## Paket

`skills/kurumsal-mail-cek/` ana beceridir. `skills/mail-ara/` aynı seviyede tutulması
gereken bağımlılıktır. İki becerinin VERSION değeri 1.3.0'dır. Arama ve tarihsel
v2 geçiş betikleri mevcut kurulumdan değiştirilmeden korunmuştur; 1.3.0 doğrulaması
aktarım/indeks akışını kapsar, gerçek mailde arama başarımı iddiası içermez.

Paket yalnız kaynak kodu, talimatlar ve sentetik testler taşır. PST, mail, ek,
SQLite/Chroma indeksi, ONNX modeli, token veya kullanıcı oturumu içermez.

## Kurulum ve önkoşullar

Mevcut yerel kurulum için iki skill klasörünü kardeş kalacak biçimde kullanın.
Mevcut arşiv ve indeks klasörlerini bu paketle değiştirmeyin. Codex/Claude skill
girişleri gerçek skill kaynağına bakmalıdır; her uygulama için ayrı kopya üretmeyin.

Mevcut Windows örneklerinde gerçek kaynak `D:\MySecondBrain\skills` altındadır;
SKILL.md komutlarındaki kişiye özgü yolları kullanmadan önce kendi ortamınızla
karşılaştırın. Varsayılan PST aktarımı klasik Outlook/MAPI ve sistem Python'unda
pywin32 kullanır; isteğe bağlı Graph için msal gerekir. İndeks sanal ortamında
Chroma, numpy, onnxruntime ve tokenizers; sistem Python'unda PyMuPDF, openpyxl ve
python-docx gerekir. Model.onnx ve tokenizer.json indeks kökünün model/onnx
klasöründe önceden bulunmalıdır. Bu paket yazılım/model indirmez ve işlem başlatmaz.

## Kullanım

`skills/kurumsal-mail-cek/SKILL.md` ana talimattır. PST dosyaları sırayla işlenir;
betik çalışma kopyasını/hash kanıtını kendisi üretir ve tam PST envanter kapısını
aynı çalıştırmada uygular. Kaynak PST doğrudan Outlook'a bağlanmaz.
Kesintide aynı kaynak/ay ile devam edilir; pending ve işlem günlükleri elle silinmez.

İndeks teslimi sanal ortam Python'uyla `mail-ara/scripts/aktarim_indeksle.py --ay YYYY-MM`
üzerinden yürür: gövde → sistem Python'u ile ek çıkarma → ek indeksi. Üç aşama aynı
koşu kimliği, arşiv hash'i ve sürüm nesliyle doğrulanmadan tamamlandı sayılmaz.

## Geçiş

**Sürüm kimliği olmayan dolu eski indeks veya değişen model/ayrıştırıcı nesli,
yeni nesille karıştırılmaz.** Mevcut indeks korunur; yeni indeks kökünde kontrollü
yeniden üretim gerekir. Eski yarım CSV kayıtları otomatik sıfırlanmaz.
Ayrıntı: `skills/kurumsal-mail-cek/references/guvenli-devam.md`.
Tarihsel `v2_gecis.py` yeni nesil kimliği kurma işleminin yerine geçmez.

## Doğrulama

87 sentetik unittest, gerçek veri/Outlook/Graph/ONNX çalıştırmadan aktarımın hata
ve kesinti durumlarını sınar. Çalışma kopyasında ve Codex'in kurulu junction
yolunda aynı 87 test geçti. Paket ZIP'ten açılıp ayrıca sınanır; sonuç
kaynak testinin sonucu `VALIDATION.json` ve `tests.log` içinde kaydedilir;
ZIP kabul sonucu yayımlanan Release notunda raporlanır. 22 Python kaynağı sözdizimi
kontrolünden geçirilir; iki SKILL.md skill-creator doğrulamasını geçer.

```powershell
python -B -m unittest discover -s "skills/kurumsal-mail-cek/tests" -v
```

Gerçek Outlook sağlayıcısı, gerçek ONNX/Chroma çalışma zamanı ve büyük arşiv
performansı bu kabulün dışında kalır. Hash ilk MIME dönüşümünü tek başına kanıtlamaz;
MAPI'nin kurduğu EML için kriptografik imza sadakati iddia edilmez. Kilit tek makine
içindir; farklı bilgisayarlardan aynı senkron arşive eşzamanlı yazılmaz.
