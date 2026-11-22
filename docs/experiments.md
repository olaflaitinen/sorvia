# Eksperimentlər

Bütün eksperimentlər təkrarlana bilən skriptlərdir. Hər işə salma `experiments/results/<ad>/<vaxt>/` qovluğunda CSV, JSON xülasə, mühit məlumatı (`environment.json`) və qrafik (PNG) yaradır.

## Mühit və data

Aşağıdakı rəqəmlər bu mühitdə ölçülüb: 2 vCPU, Linux x86_64, PostgreSQL 16.15, `shared_buffers=128MB`, `work_mem=4MB`, Python 3.13. Data: `sorvia seed --scale 1 --seed 42` (20 filial, 74 dərman, 643 partiya, 16 000 müştəri, 50 000 satış, ~84 000 satış sətri, ~87 000 jurnal hərəkəti, 254 köçürmə). Başqa kompüterdə mütləq rəqəmlər fərqli olacaq, amma nisbətlər və nəticələr eyni istiqamətdə olmalıdır. Hesabatda öz ölçdüyünüz rəqəmləri istifadə edin.

Gecikmə serverin `EXPLAIN (ANALYZE)` ilə ölçdüyü planlaşdırma + icra vaxtıdır (şəbəkə daxil deyil). Hər sorğu bir neçə isinmə icrasından sonra N dəfə ölçülür və median götürülür.

---

## RQ1: Sxem axtarışı lazımi cədvəlləri tapırmı?

**Metod.** 60 benchmark sualının hər biri üçün düzgün SQL-in istifadə etdiyi cədvəllər (gold relations) AST qoruyucusu ilə çıxarılır. Axtarışın seçdiyi obyektlər bu çoxluqla müqayisə olunur. Dil modeli lazım deyil.

- **recall:** tapılan gold cədvəllərin payı (orta);
- **əhatə (coverage):** bütün gold cədvəllərin tapıldığı sualların payı. Əhatə yoxdursa, model düzgün SQL yaza bilməz.

`python experiments/rq1_retrieval.py`

| Dil | FK genişlənməsi | top-k | Recall | Əhatə | Promptdakı obyekt sayı |
|---|---|---|---|---|---|
| AZ | yox | 2 | 0,671 | 0,533 | 2,0 |
| AZ | yox | 6 | 0,903 | 0,817 | 6,0 |
| AZ | **var** | **6** | **0,967** | **0,917** | 9,5 |
| AZ | var | 8 | 0,967 | 0,917 | 11,2 |
| EN | yox | 6 | 0,533 | 0,417 | 6,0 |
| EN | var | 6 | 0,794 | 0,717 | 9,1 |
| EN | var | 8 | 0,863 | 0,783 | 10,9 |

**Nəticələr.**
1. FK genişlənməsi əhatəni k=6-da 81,7%-dən 91,7%-ə qaldırır. Suallar adətən join tərəfdaşını (`branch`, `drug`) açıq adlandırmır, onu sxemin öz qrafı verir.
2. k=6-dan sonra əhatə artmır, prompt isə böyüyür. Default `SORVIA_RETRIEVAL_TOP_K=6` buna görə seçilib.
3. Semantik qat Azərbaycan dilində yazıldığı üçün leksik (hashing n-gram) embedding ingilis suallarında xeyli zəifdir. Bu, RQ2 üçün ilk nəticədir: çoxdilli embedding modeli (`SORVIA_EMBEDDING_PROVIDER=openai`) və ya ikidilli `COMMENT` ilə fərqin azalması gözlənilir.

## RQ1 və RQ2: Strategiya və dil üzrə dəqiqlik

**Metod.** `python benchmark/run_text2sql.py --strategies full_schema retrieval retrieval_fewshot --langs az en`

Hər sual real pipeline-dan keçir (axtarış, prompt, model, qoruyucu, scope-lu icra, təmir). Gold SQL eyni istifadəçi ilə eyni snapshot üzərində icra olunur. Metriklər `src/sorvia/evaluation.py`-dədir:

- **EX strict:** nəticə sətirləri multiset kimi bərabərdir (gold-da sıralama varsa, sıra da nəzərə alınır);
- **EX relaxed:** gold-un bütün sütunları proqnozda var, əlavə izahedici sütunlar cəzalandırılmır.

**Yoxlama.** `SORVIA_LLM_PROVIDER=static` (oracle) ilə bütün 120 sual (60 AZ + 60 EN) 100% düzgün qiymətləndirilir. Bu, pipeline-ın və qiymətləndiricinin düzgünlüyünü göstərir və hər CI işində avtomatik yoxlanılır.

**Real model ilə nəticələr.** `SORVIA_LLM_PROVIDER=openai`, `SORVIA_LLM_BASE_URL` və `SORVIA_LLM_MODEL` (lazım olsa `SORVIA_LLM_API_KEY`) təyin edib skripti işə salın; `summary.csv` aşağıdakı cədvəli doldurur:

| Strategiya | Dil | EX strict | EX relaxed | Təmir sayı | Median gecikmə |
|---|---|---|---|---|---|
| full_schema | az | | | | |
| retrieval | az | | | | |
| retrieval_fewshot | az | | | | |
| retrieval_fewshot | en | | | | |

## RQ3: Təhlükəsizlik qatlarının töhfəsi

**Metod.** 33 hücum SQL-i (`benchmark/data/adversarial_sql_v1.jsonl`) BAK01 əczaçısı adından iki konfiqurasiyada icra olunur: tam stack və yalnız baza (qoruyucu və xərc yoxlaması söndürülüb). "Scoped" tipli hücumlar (başqa filialın satışlarını oxumaq) yalnız öz filialını görürsə uğursuz sayılır. Səhv bloklama 60 normal gold sorğu ilə ölçülür.

`python experiments/rq3_guardrails.py` (dil modeli ilə təbii dildə hücumlar üçün `--nl`)

| Göstərici | Nəticə |
|---|---|
| Tam stack ilə təhlükəsiz | **33 / 33 (100%)** |
| Yalnız baza ilə təhlükəsiz | 30 / 33 (90,9%) |
| Qoruyucunun özünün dayandırdığı | 26 / 33 (78,8%) |
| Normal sorğularda səhv bloklama | **0 / 60 (0%)** |

Tam stack-də hücumların qatlar üzrə bölgüsü: AST qoruyucusu 26, baza icazələri 2 (`SELECT *` və `fin_hash` müştəri cədvəlində), plan xərci 1 (kartezian hasil), `statement_timeout` 1 (sonsuz rekursiya), RLS 3 (başqa filialın datası süzülür, yalnız öz filialı görünür).

**Nəticə.** Baza təkbaşına bütün yazma, rol dəyişmə, fayl oxuma və filiallar arası sızma cəhdlərini dayandırır, amma metadata oxumaya (`information_schema`, `pg_stat_activity`) və resurs israfına icazə verir. AST qoruyucusu bu boşluğu bağlayır. Qatlar bir-birini təkrarlamır, tamamlayır.

## RQ4: İndeks məsləhətçisi

**Metod.** İş yükü: 60 analitik gold sorğu + 40 əməliyyat sorğusu (həkimin reseptləri, işçinin son 30 gündəki satışları, adla müştəri axtarışı, dərmanı olan reseptlər). Gecikmə tövsiyədən əvvəl və sonra ölçülür (5 təkrar, median).

`python experiments/rq4_index_advisor.py --runs 5`

Tövsiyə olunan indekslər (`objective=relative`):

| İndeks | Təxmini qazanc |
|---|---|
| `prescription (doctor_id)` | 9,3% |
| `sale (employee_id, sold_at)` (bütün partition-larda) | 8,7% |
| `customer (first_name, last_name)` | 6,9% |
| `prescription_item (drug_id, prescription_id)` | 7,0% |
| `customer (bonus_points)` | 1,4% |

| İş yükü | Əvvəl (ms, cəm) | Sonra (ms, cəm) | Dəyişmə |
|---|---|---|---|
| Əməliyyat (40 sorğu) | 40,5 | 17,6 | **-57%** |
| Analitik (60 sorğu) | 4 419 | 4 369 | -1% |

**Nəticələr.**
1. Məsləhətçi əl ilə nəzərdə tutulmamış, amma real iş yükündə vacib olan dörd indeksi tapdı və əməliyyat sorğularının gecikməsini iki dəfədən çox azaltdı.
2. Analitik sorğular tam cədvəl aqreqasiyalarıdır; indeks onlara kömək etmir. Məsləhətçi bunu düzgün qiymətləndirir: heç bir indeks onlar üçün tövsiyə olunmur.
3. **Məqsəd funksiyası vacibdir.** `objective=total` (xərclərin cəmi) ilə bir neçə ağır analitik sorğu cəmə hakim olur və ucuz, amma tez-tez işləyən axtarışlar üçün yalnız bir indeks tövsiyə edilir. `relative` (hər sorğunun nisbi yaxşılaşmasının ortası) hər sorğuya bərabər çəki verir.

## S1: B-tree və BRIN

1 000 000 sətirlik, zamana görə sıralı cədvəl (`lab.events`). `python experiments/s1_index_types.py --rows 1000000`

| Konfiqurasiya | İndeks həcmi | 1 saat | 1 gün | 1 həftə | 1 ay |
|---|---|---|---|---|---|
| indekssiz | | 26,4 ms | 24,9 ms | 25,2 ms | 29,1 ms |
| B-tree | 21,4 MB | 0,04 ms | 0,45 ms | 3,18 ms | 13,2 ms |
| BRIN (128 səhifə) | 0,02 MB | 0,88 ms | 1,85 ms | 4,30 ms | 13,3 ms |
| BRIN (32 səhifə) | 0,02 MB | 0,27 ms | 0,71 ms | 3,15 ms | 12,2 ms |

**Nəticə.** Zamana görə sıralı, yalnız əlavə olunan data üçün BRIN B-tree-dən təxminən 900 dəfə kiçikdir; dar aralıqlarda bir az yavaş, geniş aralıqlarda isə eyni sürətdədir. Buna görə `batch_movement.occurred_at` üçün BRIN seçilib.

## S2: Eyni vaxtda satış və izolyasiya səviyyələri

6 işçi axını, hər biri 50 dəfə eyni qalıq sətrindən 1 ədəd satır (cəmi 300). `python experiments/s2_isolation.py --workers 6 --ops 50`

| Strategiya | İtirilmiş yeniləmə | Serializasiya xətası | Satış/san |
|---|---|---|---|
| read-modify-write, READ COMMITTED | **244** | 0 | 2 031 |
| read-modify-write, REPEATABLE READ | 0 | 1 181 | 375 |
| read-modify-write, SERIALIZABLE | 0 | 1 187 | 331 |
| atomik şərtli `UPDATE`, READ COMMITTED | **0** | 0 | **1 626** |

**Nəticə.** Ən sürətli variant yanlışdır: 300 satışdan 244-ü itir (lost update). Yüksək izolyasiya səviyyələri düzgündür, amma çoxlu təkrar cəhd tələb edir və 5 dəfə yavaşdır. Sorvia-nın trigger-lərində istifadə olunan atomik şərtli `UPDATE` həm düzgün, həm də sürətlidir.

## S3: Partitioning və ulduz sxemi

`python experiments/s3_partitioning_olap.py`

**Partition pruning** (50 000 satış, aylıq bölmələr və bölünməmiş surət):

| Aralıq | Bölünmüş | Bölünməmiş |
|---|---|---|
| 1 gün | 2,47 ms | 0,10 ms |
| 1 ay | 2,80 ms | 0,56 ms |
| 1 rüb | 5,99 ms | 2,23 ms |

**Nəticə (mənfi, amma vacib).** Bu həcmdə partitioning yavaşdır: predikat `now()` istifadə etdiyi üçün bölmələr icra vaxtı süzülür və 48 bölmənin planlaşdırma xərci qazancdan böyük olur. Partitioning sorğu sürəti üçün deyil, böyük həcmdə saxlama idarəsi (köhnə ayların `DETACH`, `VACUUM` miqyası) üçün seçilir. Böyük miqyasda (`--scale 20` və yuxarı) təkrarlamaq tövsiyə olunur.

**Ulduz sxemi və 3NF:**

| Hesabat | 3NF (OLTP) | Ulduz sxemi | Sürətlənmə |
|---|---|---|---|
| Filial üzrə aylıq gəlir | 99,3 ms | 33,4 ms | 3,0x |
| Kateqoriya üzrə satış | 41,1 ms | 23,1 ms | 1,8x |
| Şəhər və istehsalçı ölkəsi üzrə satış | 206,6 ms | 36,8 ms | 5,6x |
| Həftəsonu payı | 61,8 ms | 19,1 ms | 3,2x |

**Nəticə.** Join sayı artdıqca ulduz sxeminin üstünlüyü böyüyür (5 join olan hesabatda 5,6 dəfə).

## Təhlükəli nəticə çıxarmamaq üçün

- Ölçmələr bir maşında, isti keşlə aparılıb; soyuq keş və disk I/O ayrıca araşdırılmayıb.
- Sintetik data real şəbəkənin paylanmasını yalnız təxmini əks etdirir (həftə günləri, mövsümlük, populyarlıq).
- Benchmark 60 sualdan ibarətdir; statistik etibarlılıq üçün genişləndirilməlidir (`benchmark/build_dataset.py`).
