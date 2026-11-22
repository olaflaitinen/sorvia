# Verilənlər bazasının layihələndirilməsi

## 1. Sahə (domen)

ŞəfaNet 7 şəhərdə 20 filialı olan aptek şəbəkəsidir (sintetik data). Sistem dərmanların istehsalçıdan müştəriyə qədər hərəkətini izləyir: partiyanın daxil olması, filiallar arası köçürmə, reseptlə və ya reseptsiz satış, vaxtı keçmiş məhsulun silinməsi.

## 2. ER diaqramı (OLTP, `pharma` sxemi)

```mermaid
erDiagram
    BRANCH ||--o{ EMPLOYEE : "işləyir"
    JOB_POSITION ||--o{ EMPLOYEE : "vəzifə"
    CATEGORY ||--o{ CATEGORY : "alt kateqoriya"
    CATEGORY ||--o{ DRUG : "aiddir"
    MANUFACTURER ||--o{ DRUG : "istehsal edir"
    DRUG ||--o{ BATCH : "partiyalar"
    BRANCH ||--o{ STOCK : "saxlayır"
    BATCH ||--o{ STOCK : "qalıq"
    CUSTOMER ||--o{ PRESCRIPTION : "alır"
    DOCTOR ||--o{ PRESCRIPTION : "yazır"
    PRESCRIPTION ||--|{ PRESCRIPTION_ITEM : "ehtiva edir"
    DRUG ||--o{ PRESCRIPTION_ITEM : "dərman"
    BRANCH ||--o{ SALE : "satış edir"
    EMPLOYEE ||--o{ SALE : "rəsmiləşdirir"
    CUSTOMER |o--o{ SALE : "alıcı"
    PRESCRIPTION |o--o{ SALE : "əsasında"
    SALE ||--|{ SALE_ITEM : "sətirlər"
    BATCH ||--o{ SALE_ITEM : "satılan partiya"
    BRANCH ||--o{ STOCK_TRANSFER : "haradan / haraya"
    BATCH ||--o{ STOCK_TRANSFER : "köçürülən"
    BATCH ||--o{ BATCH_MOVEMENT : "hərəkətlər"
    BRANCH ||--o{ BATCH_MOVEMENT : "harada"

    DRUG {
        int drug_id PK
        text trade_name
        text active_ingredient
        smallint category_id FK
        smallint manufacturer_id FK
        text dosage_form
        text strength
        bool requires_prescription
        numeric unit_price
    }
    BATCH {
        int batch_id PK
        int drug_id FK
        text lot_number
        date manufactured_on
        date expires_on
    }
    STOCK {
        smallint branch_id PK
        int batch_id PK
        int quantity
    }
    SALE {
        bigint sale_id PK
        timestamptz sold_at PK
        smallint branch_id FK
        int employee_id FK
        int customer_id FK
        int prescription_id FK
        numeric gross_amount
        numeric discount_amount
        numeric net_amount
    }
    SALE_ITEM {
        bigint sale_id PK
        timestamptz sold_at PK
        smallint line_no PK
        int batch_id FK
        int quantity
        numeric unit_price
    }
    BATCH_MOVEMENT {
        bigint movement_id PK
        int batch_id FK
        smallint branch_id FK
        int quantity_delta
        enum reason
        timestamptz occurred_at
    }
```

`sorvia` sxemi (platforma): `app_user`, `scope_ticket`, `session_scope`, `schema_doc`, `nl_query`, `query_feedback`, `index_recommendation`. `audit.change_log` dəyişiklik tarixçəsini saxlayır.

## 3. Normallaşdırma

### Başlanğıc: bir böyük "satış qəbzi" cədvəli

Kağız çekdə olan hər şeyi bir cədvələ yazsaq:

```
QEBZ(qebz_no, tarix, filial_kodu, filial_adi, filial_seheri, isci_adi,
     musteri_fin, musteri_adi, [derman_adi, forma, doza, istehsalci, olke,
     kateqoriya, lot, son_tarix, miqdar, qiymet]*)
```

**1NF pozuntusu:** kvadrat mötərizədəki qrup təkrarlanır (bir çekdə bir neçə dərman). Təkrarlanan qrup ayrıca sətirlərə çıxarılır, açar `(qebz_no, setir_no)` olur.

### Funksional asılılıqlar

```
qebz_no            -> tarix, filial_kodu, isci_id, musteri_fin
filial_kodu        -> filial_adi, filial_seheri
musteri_fin        -> musteri_adi
(qebz_no, setir_no)-> lot, miqdar, qiymet
lot                -> derman_id, son_tarix
derman_id          -> derman_adi, forma, doza, istehsalci, kateqoriya
istehsalci         -> olke
```

**2NF:** `(qebz_no, setir_no)` açarlı cədvəldə `tarix`, `filial_kodu` yalnız `qebz_no`-dan asılıdır (qismən asılılıq). Ayrılır: `SALE(sale_id, ...)` və `SALE_ITEM(sale_id, line_no, ...)`.

**3NF:** `filial_kodu -> filial_adi`, `lot -> derman_id -> derman_adi`, `istehsalci -> olke` keçid (transitiv) asılılıqlarıdır. Ayrılır: `BRANCH`, `BATCH`, `DRUG`, `MANUFACTURER`, `CATEGORY`.

**BCNF:** Hər determinant namizəd açardır. Məsələn `BATCH`-da `(drug_id, lot_number)` alternativ açardır və `UNIQUE` ilə qorunur; `batch_id` süni açardır. `STOCK(branch_id, batch_id) -> quantity` tək asılılıqdır.

### Şüurlu istisnalar

| Yer | Niyə | Bütövlük necə qorunur |
|---|---|---|
| `sale.gross_amount` | Hər hesabatda sətirləri cəmləməmək üçün törəmə dəyər | Yalnız `sale_item_apply` trigger-i yeniləyir; test cəmin sətirlərə bərabər olduğunu yoxlayır |
| `sale.net_amount` | `gross - discount` | `GENERATED ALWAYS AS ... STORED`, əl ilə yazmaq mümkün deyil |
| `sale_item.sold_at` | Bölünmüş (partitioned) `sale` cədvəlinə FK üçün açarın hissəsi olmalıdır | Kompozit FK `(sale_id, sold_at)` |
| `analytics` sxemi | OLAP üçün denormallaşdırılmış ulduz sxemi | ETL yalnız OLTP-dən oxuyur; inteqrasiya testi cəmlərin üst-üstə düşdüyünü yoxlayır |

## 4. Bütövlük qaydaları

| Qayda | Mexanizm | Xəta kodu |
|---|---|---|
| Vaxtı keçmiş partiya satıla bilməz | `BEFORE INSERT` trigger, Bakı vaxtı ilə tarix | `SV001` |
| Reseptli dərman yalnız həmin müştərinin etibarlı və kifayət qədər miqdarı olan resepti ilə satılır | `BEFORE INSERT` trigger, `prescription_item.dispensed_quantity` artırılır | `SV002` |
| Qalıq mənfiyə düşə bilməz | Şərtli atomik `UPDATE ... WHERE quantity >= n` | `SV003` |
| Satışı yalnız həmin filialın aktiv işçisi edə bilər | Prosedur yoxlaması | `SV004` |
| Satış sətirləri və hərəkət jurnalı dəyişdirilə bilməz | `BEFORE UPDATE/DELETE` trigger | `SV005` |
| Qiymət, maaş, şəxsi məlumat dəyişiklikləri izlənir | `audit.log_change()`, FİN sütunları jurnaldan çıxarılır | |

## 5. Tranzaksiyalar və eyni vaxtda giriş

- `pharma.register_sale` partiyaları FEFO qaydası ilə seçir və onları `FOR UPDATE OF st` ilə həmişə eyni sırada (son tarix, sonra `batch_id`) kilidləyir. Eyni dərmanı satan iki kassa bir-birini gözləyir, deadlock yaranmır.
- `stock_transfer_apply` iki filialın qalıq sətirlərini `branch_id` artan sırası ilə kilidləyir; əks istiqamətli iki köçürmə deadlock-a düşmür.
- Read-modify-write əvəzinə atomik şərtli `UPDATE` seçilməsinin səbəbi eksperimentlə göstərilib (S2, `docs/experiments.md`).

## 6. Fiziki dizayn

| İndeks | Tip | Səbəb |
|---|---|---|
| `sale (branch_id, sold_at)` | B-tree, hər partition-da | Filial və dövr üzrə hesabatlar |
| `sale (customer_id) WHERE customer_id IS NOT NULL` | partial | Anonim satışlar (təxminən yarısı) indeksə düşmür |
| `batch (drug_id, expires_on)` | composite | FEFO seçimi bu sıra ilə gedir |
| `batch_movement (occurred_at)` | BRIN | Yalnız əlavə olunan, zamanla sıralı jurnal; S1-də BRIN B-tree-dən təxminən 900 dəfə kiçik çıxıb |
| `batch_movement (batch_id, occurred_at)` | composite | `batch_location_at` |

**Partitioning:** `pharma.sale` aylara görə bölünüb (`ensure_sale_partitions`). Köhnə ayları arxivləmək `DETACH PARTITION` ilə ani əməliyyatdır. S3 eksperimenti göstərir ki, 50 000 sətirdə bölmənin planlaşdırma xərci qazancdan böyükdür; bu, partitioning-in yalnız böyük həcmdə özünü doğrultduğunu göstərən nəticədir.

## 7. Temporal izlənmə

`batch_movement` dəyişməz jurnaldır (yalnız `INSERT`). İstənilən an üçün partiyanın yeri onun hərəkətlərinin cəmidir:

```sql
SELECT * FROM pharma.batch_location_at(42, timestamptz '2026-03-01 12:00+04');
```

Seed generatoru və inteqrasiya testi `stock` cədvəlinin hər `(filial, partiya)` cütü üçün jurnalın cəminə bərabər olduğunu yoxlayır.
