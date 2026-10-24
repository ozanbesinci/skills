# Geçmiş mail arşivi onarımı

Bu mod yalnız önceden dışa aktarılmış aylık koşularda parser kaynaklı gövde veya ek
bütünlüğü sorunu kanıtlandığında kullanılır. Yeni mail çekimi için `SKILL.md` içindeki
normal exporter akışını kullan.
Bu onarım Graph mesaj kimliklerini kullanır; MAPI/PST ayları keşifte atlanır.

## Değişmezler

- Mailbox erişimi yalnız Microsoft Graph `Mail.Read` kapsamındadır.
- Çalışma/yedek klasörü arşiv kökü `C:\Users\ozanbesinci\Drive'ım\maillerim\_onarim\` altında olmalıdır.
- Hazırlık sırasında aylık koşulara yazılmaz. Manifest `READY` olmadan `--uygula`
  çağrılmaz.
- Uygulama öncesi eski gövdeler, ham EML'ler, staged gövdeler ve aylık CSV imzaları
  yeniden doğrulanır. Herhangi bir değişiklik uygulamayı durdurur.
- Tüm eski gövdeler ve raporlar yedeklenmeden ilk canlı dosya değiştirilmez.
- Kaynak EML'de bulunan U+FFFD veya 0-byte gerçek ek uydurularak düzeltilmez;
  `sorunlu_eml/` ve `_uyarilar.json` ile kanıtlı uyarı olarak korunur.
- Graph kimlikleri harf büyüklüğüne duyarlıdır. Mükerrer denetiminde ordinal/case-sensitive
  karşılaştırma kullan; PowerShell'in varsayılan case-insensitive gruplamasını kullanma.
- `APPLIED` manifestte `--uygula` tekrar çağrılmaz. Geri dönüş gerekirse manifestteki
  `backup_root` kullanılır ve hedefler hash ile doğrulanır.

## Akış

Önce script regresyonlarını çalıştır:

```powershell
python -m unittest discover -s "<skill-folder>\tests" -p "test_*.py" -v
python -m py_compile "<skill-folder>\scripts\mail_onar.py" "<skill-folder>\scripts\mail_yaz.py" "<skill-folder>\scripts\kontrol.py" "<skill-folder>\scripts\mail_export.py"
```

Hazırlık çağrısı keşfi yeniden yapar, mevcut sıfırdan büyük EML'leri yeniden indirmez
ve manifesti her 100 kayıtta atomik günceller:

```powershell
python "<skill-folder>\scripts\mail_onar.py" --calisma "C:\Users\ozanbesinci\Drive'ım\maillerim\_onarim\<calisma-adi>"
```

`status=READY`, tüm kayıtlar `prepared=true`, `.part=0`, staged gövde hash'leri ve
ham EML hash'leri doğru olmadan devam etme. `BLOCKED` durumunda aylık arşivlere dokunma;
manifestteki `prepare_failures` veya `blockers` nedenini teşhis et.

Bağımsız denetim temizse yedekli uygula:

```powershell
python "<skill-folder>\scripts\mail_onar.py" --calisma "C:\Users\ozanbesinci\Drive'ım\maillerim\_onarim\<calisma-adi>" --uygula
```

Uygulama sonrasında yedi koşunun tamamını doğrulayıp raporları ancak hepsi geçerse
atomik yenile:

```powershell
python "<skill-folder>\scripts\mail_onar.py" --calisma "C:\Users\ozanbesinci\Drive'ım\maillerim\_onarim\<calisma-adi>" --raporlari-yenile
```

Son hüküm için şunların tümünü doğrula:

- manifest `APPLIED` ve `report_verdicts` değerlerinin tamamı `GECTI`;
- yedek gövdeler eski hash'lerle, canlı gövdeler staged hash'lerle eşleşiyor;
- her etkilenen mesajın `sorunlu_eml/<sira_no>.eml` kanıtı var ve ham hash'i doğru;
- yedi `kontrol.txt` dosyasının ilk satırı `KONTROL: GECTI`;
- kanıt gerektiren her uyarının `_uyarilar.json` kaydı ve sıfırdan büyük ham EML'si var;
- aylık koşularda `.part`, `.onarim.tmp` veya yarım rapor kalmamış.

## İndekse yeniden teslim

APPLIED yalnız onarımın uygulanmasıdır. Rapor yenileme güncel `_aktarim.json`
kimliği üretir; gövde ve ek indeksleri ayrıca `mail-ara/scripts/aktarim_indeksle.py`
ile yeniden teslim edilir. Onarım, eski hash makbuzunu etkilenen kayıt için yeniler;
başarısız/yarım onarım indeks kapısını açmaz. Manuel MAPI yeniden sınıflandırma
teslimi geçersiz kılar; ilgili PST/MAPI kaynağıyla başarılı yeniden doğrulama gerekir.
Yeni nesil gereksinimleri için [güvenli devam](guvenli-devam.md) geçerlidir.

## 2026-08-27 tamamlanan taban onarımı

Ocak–Temmuz 2026 arşivleri onarıldı: 2.423 mesaj kanıtlandı, 2.421 gövde işlendi,
327.352 NUL temizlendi; yeni gövdelerde NUL 0, yalnız kaynaktan gelen kanıtlı 28
U+FFFD kaldı. Üç 0-byte PDF ham EML'de de 0 byte olduğu için kaynak uyarısıdır.

O tarihteki manifest `APPLIED` idi ve yedi aylık kontrol `GECTI` sonucunu verdi.
Eski `_onarim` çalışma alanı Ortak'ın 29.09.2026 temizlik talimatıyla Geri Dönüşüm
Kutusu'na taşındı; aynı yoldaki manifestin hâlâ bulunduğu varsayılmaz.
