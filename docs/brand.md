# Brend

Tam brend bələdçisi Figma faylındadır: [Sorvia Brand Identity](https://www.figma.com/design/kPivyo9fIQx1eGO8kqdlqy). Bu sənəd onun qısa xülasəsidir; fayllar `assets/brand/` qovluğundadır.

## Konsepsiya

**Sorvia** = *sor* (soruş) + *via* (yol): sualdan cavaba gedən yol. İşarə bir nöqtədən açılan işıq şüalarıdır: sual verilir, cavab aşkara çıxır.

**Şüar:** *Soruş, aşkara çıxsın.* (EN: *Ask your data. Reveal the answer.*)

## Loqo

| Fayl | İstifadə |
|---|---|
| `sorvia-logo-horizontal.svg` / `-light.svg` | Əsas loqo: sayt başlığı, sənədlər, slaydlar |
| `sorvia-logo-stacked.svg` / `-light.svg` | Kvadrat sahələr, cover, poster |
| `sorvia-mark.svg` / `-light.svg` | Kiçik ölçülər, avatar |
| `sorvia-wordmark.svg` / `-light.svg` | Yalnız ad lazım olduqda |
| `sorvia-app-icon.svg`, `sorvia-app-icon-512.png`, `favicon.svg`, `favicon.ico` | Tətbiq ikonu və favicon |
| `social-preview.png` | GitHub repo örtüyü (1280 x 640) |

`-light` versiyaları tünd fon üçündür.

**Qaydalar:**
- Boş sahə hər tərəfdən işarənin hündürlüyünün yarısı qədərdir.
- Minimum ölçü: lockup 96 px (çapda 24 mm), işarə 16 px (çapda 5 mm).
- Loqonu dartmayın, fırlatmayın, ona kölgə və ya effekt verməyin.
- Loqonu zəif kontrastlı fonda istifadə etməyin. Kəhrəba fonda loqo həmişə mürəkkəb rəngdə olmalıdır.

## Rəng

| Ad | Hex | Rol |
|---|---|---|
| Mürəkkəb | `#0B0C0E` | Mətn, loqo, tünd fon |
| Kağız | `#F5F2EA` | Əsas açıq fon |
| Kəhrəba | `#F0A43A` | Vurğu, düymə, ikon fonu (mətn rəngi deyil) |
| Xəzər | `#2A716C` | Data və analitika |

Status rəngləri API-dəki statuslara uyğundur: `ok` yaşıl, `blocked` kəhrəba, `error` qırmızı, `timeout` göy. Bütün token-lər açıq və tünd rejim üçün `assets/brand/tokens.css` faylında CSS dəyişənləri kimi verilib.

## Tipoqrafiya

| Şrift | Rol |
|---|---|
| Gamiya Retro | Loqo və başlıqlar (minimum 24 px), bir ekranda ən çox bir başlıq |
| IBM Plex Sans | İnterfeys və gövdə mətni |
| IBM Plex Mono | SQL, rəqəmlər, texniki etiketlər |

Gamiya Retro exFont-dan götürülüb və **yalnız şəxsi istifadə üçün pulsuzdur**. Lisenziya imkan vermədiyi üçün font faylı bu repoda paylaşılmır. Kommersiya istifadəsindən əvvəl lisenziya alınmalıdır. Loqodakı yazı konturlanmış vektordur, ona görə font quraşdırılmadan da düzgün görünür.
