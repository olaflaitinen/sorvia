<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/sorvia-logo-horizontal-light.svg">
    <img src="assets/brand/sorvia-logo-horizontal.svg" alt="Sorvia" width="320">
  </picture>
</p>

<p align="center"><b>Soruş, aşkara çıxsın.</b></p>

# Sorvia

**Verilənlər bazasına Azərbaycan dilində sual ver, cavabı təhlükəsiz SQL ilə al.**

Sorvia təbii dildə verilən sualı PostgreSQL sorğusuna çevirən, həmin sorğunu üç müstəqil təhlükəsizlik qatından keçirən və bazanın özünü real iş yükünə görə optimallaşdıran platformadır. Demo sahəsi kimi 20 filiallı sintetik aptek şəbəkəsi (ŞəfaNet) istifadə olunur.

> *Sorvia* adı iki hissədən ibarətdir: *sor* (soruş) və *via* (yol), yəni "sualdan cavaba gedən yol".

---

## Elmi töhfələr

| № | Töhfə | Harada |
|---|---|---|
| 1 | **Azərbaycan dilində Text-to-SQL test dəsti**: 60 sual, hər birinin ingiliscə paralel tərcüməsi, düzgün SQL cavabı və çətinlik səviyyəsi | `benchmark/data/az_text2sql_v1.jsonl` |
| 2 | **Bazanın səviyyəsində təhlükəsizlik**: modelin yazdığı SQL etibarsız giriş sayılır. Filial məhdudiyyətini prompt yox, PostgreSQL özü (Row-Level Security və bir dəfəlik "scope ticket" protokolu) təmin edir | `db/migrations/V006__security.sql` |
| 3 | **Özünü optimallaşdıran baza**: sorğu jurnalından iş yükü toplanır, HypoPG ilə hipotetik indekslər yoxlanılır, tamah (greedy) alqoritmi ilə indeks tövsiyə edilir | `src/sorvia/advisor/` |

## Arxitektura

```mermaid
flowchart LR
    U[İstifadəçi: Azərbaycan dilində sual] --> R[Sxem axtarışı<br/>pgvector + FK genişlənməsi]
    R --> P[Prompt + few-shot nümunələr]
    P --> L[Dil modeli]
    L --> G{1. AST qoruyucu<br/>sqlglot}
    G -- rədd --> J[(sorvia.nl_query<br/>jurnal)]
    G -- keçdi --> C{2. Plan xərci<br/>EXPLAIN}
    C -- limitdən böyük --> J
    C -- keçdi --> E[3. Read-only tranzaksiya<br/>sorvia_reader rolu + RLS]
    E -- DB xətası --> L
    E --> A[Cavab: cədvəl + SQL]
    A --> J
    J --> X[İndeks məsləhətçisi<br/>HypoPG]
```

Ətraflı izah: [`docs/architecture.md`](docs/architecture.md).

## Nəyi göstərir (DBMS kursu baxımından)

- **Layihələndirmə:** 3NF/BCNF-ə qədər normallaşdırılmış 16 cədvəlli OLTP sxemi, ER diaqramı və normallaşdırmanın addım-addım əsaslandırılması ([`docs/database-design.md`](docs/database-design.md)).
- **Bütövlük:** PK, FK, UNIQUE, CHECK, generated column, aylara görə bölünmüş (partitioned) satış cədvəli.
- **Biznes qaydaları bazada:** vaxtı keçmiş partiyanın satışı, reseptsiz reseptli dərman və mənfi qalıq trigger-lərlə qadağandır. Xətalar xüsusi `SV001` - `SV005` SQLSTATE kodları ilə qaytarılır.
- **Tranzaksiyalar:** FEFO (ilk bitən ilk çıxır) ilə partiya seçimi, `FOR UPDATE`, deadlock-un qarşısını almaq üçün qlobal kilid sırası.
- **Temporal izlənmə:** dəyişməz hərəkət jurnalı (ledger) və `pharma.batch_location_at(batch, time)` funksiyası: "bu partiya keçən ay harada idi?".
- **Təhlükəsizlik:** üç ayrı rol, sütun səviyyəsində icazələr, `pgcrypto` ilə şifrələnmiş FİN, `security_invoker` view-lar, audit jurnalı.
- **Analitika:** Kimball ulduz sxemi (`analytics.fact_sales` və 4 ölçü cədvəli), inkremental ETL proseduru.
- **Performans:** B-tree, BRIN, partial və composite indekslər, partitioning, izolyasiya səviyyələrinin eksperimental müqayisəsi.

## Veb interfeys

`web/` qovluğunda React + Vite ilə yazılmış tətbiq:

- **Sual ver:** sual yazılır və ya nümunə seçilir; cavab cədvəl, qrafik və SQL kimi göstərilir, status və bloklanma səbəbi Azərbaycan dilində izah olunur, cavab qiymətləndirilə bilir.
- **Tarixçə:** bütün suallar, statusları və icra olunmuş SQL.
- **Əməliyyatlar:** az qalan dərmanlar, vaxtı bitən partiyalar, partiyanın istənilən andakı yeri (temporal izlənmə), yeni satış.
- **Məlumat xəritəsi:** semantik qat, yəni hər cədvəlin Azərbaycan dilində təsviri.
- **İdarəetmə (menecer, admin):** statistika, bloklanma səbəbləri, indeks məsləhətçisi (təhlil, tətbiq, rədd), analitik sxemin yenilənməsi.

Açıq və tünd rejim, mobil uyğunluq və brend token-ləri (`assets/brand/tokens.css`) daxildir.

## Tez başlanğıc (Docker)

```bash
git clone https://github.com/olaflaitinen/sorvia.git
cd sorvia
cp .env.example .env            # parolları dəyişin
docker compose up --build
```

Stack hazır olduqdan sonra veb interfeys və API `http://localhost:8000`, interaktiv API sənədləri isə `http://localhost:8000/docs` ünvanındadır. Vercel-də yerləşdirmə: [`docs/deployment.md`](docs/deployment.md). `SORVIA_DEMO_PASSWORD` təyin olunubsa, bu istifadəçilər yaradılır:

| İstifadəçi | Rol | Görə bildiyi |
|---|---|---|
| `admin` | admin | bütün filiallar, indeks məsləhətçisi |
| `menecer` | manager | bütün filiallar, statistika |
| `aysel.bak01` | pharmacist | yalnız BAK01 (ŞəfaNet Nizami) |
| `tural.gnc01` | pharmacist | yalnız GNC01 (ŞəfaNet Gəncə Mərkəz) |

Default rejim `SORVIA_LLM_PROVIDER=static`-dir: sistem açar tələb etmədən test dəstindəki suallara oflayn cavab verir. Real dil modeli üçün `SORVIA_LLM_PROVIDER=openai`, `SORVIA_LLM_BASE_URL` və `SORVIA_LLM_MODEL` təyin edin; OpenAI-uyğun istənilən endpoint (hosted API, vLLM, lokal Ollama) işləyir.

## Lokal inkişaf

Tələblər: Python 3.12+, PostgreSQL 16 və `pgvector`, `hypopg` genişlənmələri.

```bash
pip install -e ".[dev,experiments]"
export SORVIA_ADMIN_DSN=postgresql://postgres:postgres@localhost:5432/sorvia
export SORVIA_API_DB_PASSWORD=sorvia_api SORVIA_NL_DB_PASSWORD=sorvia_nl SORVIA_DEMO_PASSWORD=Demo-Pass-2026

sorvia migrate                       # 8 miqrasiya, checksum nəzarəti ilə
sorvia bootstrap-roles               # sorvia_api və sorvia_nl login rolları
sorvia seed --scale 1 --demo-users   # 50 000 satış, ~84 000 satış sətri
sorvia index-schema                  # semantik qatın embedding-ləri
sorvia serve
```

Terminaldan sual vermək:

```bash
sorvia ask "Bu il ən az gəlir gətirən filial hansıdır?" --user menecer
```

## API nümunəsi

```bash
TOKEN=$(curl -s localhost:8000/v1/auth/token -H 'content-type: application/json' \
  -d '{"username":"aysel.bak01","password":"Demo-Pass-2026"}' | jq -r .access_token)

curl -s localhost:8000/v1/ask -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"question":"Bu il miqdarca ən çox satılan 10 dərman"}' | jq
```

Bütün endpoint-lər: [`docs/api.md`](docs/api.md).

## Tədqiqat sualları və nəticələr

| Sual | Skript | Qısa nəticə (lokal ölçmə) |
|---|---|---|
| **RQ1** Sxem axtarışı lazımi cədvəlləri tapırmı? | `experiments/rq1_retrieval.py` | top-6 + FK genişlənməsi ilə Azərbaycan dilində sualların 91,7%-də bütün lazımi cədvəllər tapılır (genişlənmə olmadan 81,7%) |
| **RQ1** Hansı prompt strategiyası daha dəqiqdir? | `benchmark/run_text2sql.py` | Real dil modeli qoşulanda işə salınır; oracle yoxlaması 100% (qiymətləndiricinin düzgünlüyü) |
| **RQ2** Azərbaycan və ingilis dilləri arasında fərq | eyni skriptlər | Semantik qat Azərbaycan dilində olduğu üçün axtarış AZ suallarında xeyli yaxşıdır (91,7% və 71,7% əhatə) |
| **RQ3** Təhlükəsizlik qatlarının töhfəsi | `experiments/rq3_guardrails.py` | 33 hücumun 100%-i dayandırılır, 60 normal sorğuda səhv bloklama 0%. Yalnız DB qatı ilə 90,9%: metadata sızması (information_schema) qalır |
| **RQ4** İndeks məsləhətçisi gecikməni azaldırmı? | `experiments/rq4_index_advisor.py` | 5 indeks tövsiyəsi, əməliyyat sorğularının ümumi gecikməsi 40,5 ms-dən 17,6 ms-ə düşür (-57%) |
| S1 B-tree və BRIN | `experiments/s1_index_types.py` | BRIN təxminən 900 dəfə kiçikdir (0,02 MB və 21,4 MB), aylıq aralıqda sürəti B-tree ilə eynidir |
| S2 İzolyasiya səviyyələri | `experiments/s2_isolation.py` | READ COMMITTED-də read-modify-write 300 satışdan 244-ünü itirir; atomik şərtli UPDATE heç nə itirmir və SERIALIZABLE-dan 5 dəfə sürətlidir |
| S3 Partitioning və ulduz sxemi | `experiments/s3_partitioning_olap.py` | Ulduz sxemi hesabatları 1,8 - 5,6 dəfə sürətləndirir; 50 000 sətirdə partitioning planlaşdırma xərci səbəbindən hələ qazanc vermir |

Metodologiya, mühit və bütün cədvəllər: [`docs/experiments.md`](docs/experiments.md).

## Testlər

```bash
pytest -q                                            # yalnız unit testlər
SORVIA_TEST_ADMIN_DSN=postgresql://postgres:postgres@localhost:5432/postgres pytest -q   # + inteqrasiya
```

82 test: AST qoruyucusu, trigger-lər, FEFO, reseptlər, ledger, RLS və ticket protokolu, API, oracle rejimində bütün 60 benchmark sualı və indeks məsləhətçisi. CI hər push-da lint, mypy (strict), testlər və Docker build-i işə salır.

## Layihənin strukturu

```
db/migrations/        V001-V008: sxem, məntiq, view-lar, platforma, təhlükəsizlik, semantik qat, OLAP
src/sorvia/
  guard/              AST əsaslı SQL qoruyucusu (qat 1)
  executor.py         plan xərci (qat 2) və scope-lu read-only icra (qat 3)
  nl2sql/             embedding, sxem axtarışı, prompt, LLM klientləri, pipeline
  advisor/            HypoPG əsaslı indeks məsləhətçisi
  seed/               deterministik sintetik data generatoru
  api/                FastAPI tətbiqi
  evaluation.py       execution accuracy metrikləri
benchmark/            test dəsti, hücum korpusu, qiymətləndirmə skripti
experiments/          RQ1-RQ4 və S1-S3 eksperimentləri
web/                  veb interfeys (React + Vite)
api/, vercel.json     Vercel serverless yerləşdirməsi
docs/                 arxitektura, DB dizaynı, təhlükəsizlik, eksperimentlər, API, brend, yerləşdirmə
assets/brand/         loqo, ikon, favicon, rəng token-ləri (tokens.css)
```

## Brend

Brend bələdçisi: [`docs/brand.md`](docs/brand.md) və Figma faylı.

## Lisenziya və istinad

MIT lisenziyası. Elmi işdə istifadə üçün istinad məlumatı [`CITATION.cff`](CITATION.cff) faylındadır.
