# Türkiye IPTV — Web'den kolay yükleme sürümü

Bu sürüm GitHub web arayüzünde kolay yükleme için düzleştirilmiştir.

## 1) Önce şu dosyaları repo köküne yükle

- build_playlist.py
- validate_playlist.py
- channels.json
- .gitattributes
- .gitignore
- README.md

`update-playlist.yml` dosyasını şimdilik köke yükleme.

## 2) Workflow'u GitHub'da oluştur

Repo içinde:

**Add file → Create new file**

Dosya adı alanına aynen şunu yaz:

`.github/workflows/update-playlist.yml`

Sonra bu paketteki `update-playlist.yml` dosyasının içeriğini kopyalayıp yapıştır ve commit et.

GitHub, dosya adındaki `/` karakterlerinden klasörleri otomatik oluşturur.

## 3) Workflow'u çalıştır

**Actions → Update playlist → Run workflow**

Çalışınca repo kökünde `playlist.m3u` oluşur.

Eğer workflow push yapamazsa:

**Settings → Actions → General → Workflow permissions → Read and write permissions**

seçeneğini aç.

## 4) TiviMate URL'si

`KULLANICI_ADI` ve `REPO_ADI` kısmını değiştir:

`https://raw.githubusercontent.com/KULLANICI_ADI/REPO_ADI/main/playlist.m3u`

## Dosyalar neden düz?

GitHub web arayüzünde klasör sürükleme bazı tarayıcı/ortamlarda sorun çıkarabiliyor.
Bu nedenle Python ve JSON dosyaları repo köküne taşındı. Sadece GitHub Actions'ın zorunlu klasörü
`.github/workflows/` altında kalıyor; onu da GitHub'ın **Create new file** ekranından tek adımda oluşturabilirsin.
