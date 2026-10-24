# Repo Denetle - 1.1.3 (kararlı)

1.1.3 kararlı sürümdür. Windows kod testleri, Antigravity sekiz aşamalı akışı ve
örnek raporun Codex içinde yapılan kaynak bağlı düzeltmesi/bağımsız son okuması doğrulandı.
Uygulama ve sürüm bazındaki kanıt kapsamı `TEST-RESULTS.md` içindedir.

GitHub deposunu (ya da yerel bir Git kopyasını) tek bir commit'e sabitleyip çok ajanlı,
kanıta dayalı statik denetim yapar. Dört bağımsız rapor (BIZ, ARCH, REL, QA), bulgu doğrulama
(VERIFY) ve beşinci bütünleşik yaşam döngüsü raporu (LIFE) + yol haritası üretir. Raporlar
Türkçedir. Claude Code, Codex ve Antigravity'de aynı klasörden çalışır.

## Kurulum
Python 3.10+ ve Git gerekir. Windows: `KUR-WINDOWS.cmd`. Diğerleri:
`python3 scripts/kur.py --target all`. Kopya yapılmaz: Claude Code ve Codex skill klasörüne
junction/symlink açılır; Antigravity junction izlemediği için `~/.gemini/config/skills.json`
içine bu klasörü gösteren bir kayıt eklenir. Yolda başka bir şey varsa `~/.repo-denetle-yedek/`
altına taşınır. Önizleme `--dry-run`, kaldırma `--uninstall`. Kurulumdan sonra yeni oturum açın.

## Kullanım
- Claude Code: `/repo-denetle https://github.com/kullanici/proje`
- Codex: `$repo-denetle https://github.com/kullanici/proje`
- Antigravity: "repo-denetle ile şu depoyu denetle: https://github.com/kullanici/proje"
  (uygulama/IDE ya da etkileşimli `agy`; başsız `agy -p` komut izni soramaz)
- Özel depo / ağ yok: yerel kopyayla `--local-git YOL --repo sahip/ad`.
- Profil: `--profile guvence` (varsayılan) | `dengeli` | `derin`.

Çalışma klasörü varsayılanı `~/repo-denetle-calisma/<repo>-<zaman>`; `REPO_DENETLE_ROOT`
ortam değişkeniyle değişir. Sonuç: o klasörde `repo-denetle-raporlar.zip`.
LIFE sonrasında tam çıktı incelemesi ve `review.json` zorunludur. `review-template` boş
form üretir; gerçek okuyucu kaynakları kontrol eder, `review-check` ardından `finalize`
çalışır. Ayrıntı: `references/final-review.md`. Aşama yeniden açılırsa eski ZIP/inceleme
`superseded/` altına taşınır; yeni sonuç gibi sunulmaz.

## Sınırlar
Statik denetimdir: hedef deponun kodu, testi, kurulumu, CI'ı çalıştırılmaz; PR açılmaz.
Kontroller dosya/hash/satır/alıntı ve aşama sırasını denetler, raporun anlamca doğruluğunu
kanıtlamaz. Gerçek alt ajan yoksa sıralı kip raporda açıkça yazılır. Model ve efor seçimi
uygulamaya bağlıdır. Raporlar gizli bilgi içerebilir; dışarı otomatik gönderilmez.
Hangi uygulamada neyin canlı doğrulandığı `TEST-RESULTS.md` içindedir.
