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

### Şrift lisenziyası və həll

Gamiya Retro exFont-dan götürülüb və **yalnız şəxsi istifadə üçün pulsuzdur**. Font faylını açıq repoda və ya saytda paylaşmaq lisenziyanı pozardı. Buna görə:

- Font faylı repoda yoxdur və brauzerə heç vaxt göndərilmir.
- Gamiya Retro ilə yazılan hər şey (loqo, "Soruş, aşkara çıxsın." şüarı, Figma-dakı başlıqlar) konturlanmış vektordur. Bu, loqo üçün standart üsuldur və font quraşdırılmadan da hər yerdə eyni görünür.
- Yeni başlıq lazım olduqda `scripts/outline_text.py` skripti şrifti lokal kompüterdən oxuyub `fill="currentColor"` olan SVG yaradır.
- İnterfeys mətni açıq lisenziyalı (SIL OFL) IBM Plex Sans və IBM Plex Mono ilə yazılır; onlar `@fontsource` vasitəsilə saytın özündən verilir, Azərbaycan hərflərini tam dəstəkləyir.

Figma-da başlıqları mətn kimi redaktə etmək istəsəniz, şrifti kompüterinizə quraşdırın; Figma desktop tətbiqi lokal şriftləri avtomatik görür. Kommersiya istifadəsindən əvvəl exFont-dan lisenziya alınmalıdır.
