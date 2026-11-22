# Azərbaycan dilində Text-to-SQL test dəsti (az_text2sql_v1)

## Tərkibi

`benchmark/data/az_text2sql_v1.jsonl`, 60 qeyd:

| Sahə | Məzmun |
|---|---|
| `id` | `q001` ... `q060` |
| `difficulty` | `easy` (15), `medium` (30), `hard` (15) |
| `question` | Azərbaycan dilində sual |
| `question_en` | ingiliscə paralel tərcümə (RQ2 üçün) |
| `sql` | düzgün (gold) PostgreSQL sorğusu |
| `ordered` | nəticənin sırası vacibdirmi |
| `tags` | `join`, `group`, `date`, `ranking`, `window`, `hierarchy`, `olap`, `ratio`, `anti-join`, `view`, `subquery`, `case` |

Çətinlik meyarları: **easy** tək cədvəl və sadə filtr və ya aqreqat; **medium** join, qruplaşdırma, nisbi tarixlər, view və ya ulduz sxemi; **hard** pəncərə funksiyaları, iyerarxiya (alt kateqoriyalar), anti-join, CTE, dövrlərin müqayisəsi.

Nisbi tarixli suallar ("keçən ay", "bu il") `current_date` ilə ifadə olunur, buna görə gold cavab həmişə proqnozla eyni anda və eyni snapshot üzərində hesablanır.

## Hücum korpusları

- `adversarial_sql_v1.jsonl`: 33 zərərli SQL (yazma, DDL, imtiyaz, fayl, kataloq, DoS, scope pozuntusu) və gözlənilən nəticə (`blocked` və ya `scoped`).
- `adversarial_nl_v1.jsonl`: 15 təbii dildə hücum (prompt injection daxil), dil modeli ilə sınaq üçün.

## Genişləndirmə

Dəst `benchmark/build_dataset.py` skriptindən yaradılır; yeni sual əlavə edib skripti işə salın. Hər gold SQL-in bütün pipeline-dan (qoruyucu, scope-lu icra) keçdiyini və cavabın düzgün qiymətləndirildiyini `tests/integration/test_platform.py::test_oracle_answers_are_correct` avtomatik yoxlayır. Yeni sualın seed edilmiş bazada boş olmayan nəticə verdiyini əl ilə yoxlayın.

Few-shot nümunələri (`src/sorvia/nl2sql/examples.py`) test dəstindən ayrıca yazılıb və qiymətləndirilmir, ona görə nəticələrə "sızma" yoxdur.
