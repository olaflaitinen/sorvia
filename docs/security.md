# Təhlükəsizlik modeli

## Təhdid modeli

Dil modelinin yazdığı SQL **etibarsız girişdir**. Model səhv edə, prompt injection-a məruz qala və ya istifadəçinin pis niyyətli sualını yerinə yetirməyə çalışa bilər. Ona görə də Sorvia təhlükəsizliyi prompt-a deyil, bir-birindən asılı olmayan üç qata əsaslandırır. Hər qat təkbaşına bir hücum sinfini dayandırır, birlikdə isə dərin müdafiə (defense in depth) yaradır.

| Qat | Mexanizm | Dayandırdığı |
|---|---|---|
| 1. AST qoruyucu | sqlglot ilə sintaksis ağacı; bir ifadə, yalnız SELECT, icazəli sxem, cədvəl və funksiya siyahısı, `pg_*` identifikatorları qadağan, LIMIT məcburi | DML/DDL, `SELECT INTO`, `FOR UPDATE`, `pg_sleep`, `set_config`, fayl oxuma, sistem kataloqları, platforma cədvəlləri |
| 2. Plan xərci | `EXPLAIN` ilə optimizatorun təxmini xərci `SORVIA_MAX_PLAN_COST`-dan böyükdürsə icra yoxdur | Kartezian hasil kimi resurs tükəndirən sorğular |
| 3. Baza | ayrıca `sorvia_reader` rolu, `transaction_read_only`, `statement_timeout`, RLS, sütun icazələri | yazma cəhdləri, sonsuz rekursiya, başqa filialın datası, şifrəli şəxsi məlumat |

## Filial məhdudiyyəti: scope ticket protokolu

Problem: bir connection pool bütün istifadəçilərə xidmət edir, amma hər sorğu yalnız sahibinin filialını görməlidir. `SET sorvia.branch_id = 1` kimi sessiya dəyişəni təhlükəlidir, çünki modelin SQL-i `set_config(...)` ilə onu dəyişə bilər.

Həll:

1. API (`sorvia_app`) `sorvia.issue_scope_ticket(user_id)` çağırır. Funksiya istifadəçinin rolunu və filialını `sorvia.app_user`-dən özü oxuyur və 30 saniyəlik təsadüfi UUID qaytarır.
2. Reader connection eyni tranzaksiya daxilində `sorvia.redeem_scope_ticket(ticket)` çağırır. Ticket silinir (bir dəfəlik), scope isə `(backend_pid, transaction_id)` cütünə bağlanır.
3. RLS siyasətləri scope-u `SECURITY DEFINER` funksiyaları ilə oxuyur. Tranzaksiya bitən kimi scope etibarsızdır; ticket redeem etməmiş sessiya heç bir filial sətrini görmür (deny by default).

`sorvia_reader` rolu `session_scope` və `scope_ticket` cədvəllərini nə oxuya, nə yaza bilir. İnteqrasiya testləri bunu yoxlayır: ticket-siz reader 0 satış görür, ticket ikinci dəfə istifadə oluna bilmir, tranzaksiyadan sonra scope yox olur.

RLS-in aldadılmaması üçün əlavə tədbirlər:

- Bütün view-lar `security_invoker = true` ilə yaradılıb. Əks halda view sahibinin hüquqları ilə işləyir və RLS-dən yan keçir.
- Ulduz sxemindəki `analytics.fact_sales` də RLS ilə qorunur, yoxsa analitika "arxa qapı" olardı.
- Partition-lara birbaşa giriş icazəsi yoxdur; sorğular ana cədvəldən keçməlidir.
- Siyasətlərdə scope funksiyaları `(SELECT ...)` daxilində çağırılır ki, hər sətir üçün yox, sorğuda bir dəfə hesablansın (InitPlan).

## Şəxsi məlumat

- FİN kodu `pgp_sym_encrypt` ilə şifrəli (`fin_encrypted`) və axtarış üçün HMAC (`fin_hash`) kimi saxlanır. Açar `SORVIA_FIN_KEY` mühit dəyişənindədir, bazada deyil.
- `sorvia_reader` rolunun bu iki sütuna icazəsi yoxdur (sütun səviyyəsində `GRANT`).
- Audit trigger-i bu sütunları və parol heşini jurnala yazmır.

## Autentifikasiya

- Parollar scrypt ilə (N=2^14, r=8, p=1, 16 baytlıq salt) heşlənir. Məlum olmayan istifadəçi üçün də heş yoxlanılır ki, cavab vaxtı istifadəçinin mövcudluğunu açıqlamasın.
- JWT (HS256), qısa ömürlü (default 60 dəqiqə). Hər sual verildikdə istifadəçinin aktivliyi bazada yenidən yoxlanılır (`issue_scope_ticket`).
- `/v1/ask` üçün istifadəçi başına sürət limiti var.

## Ölçülmüş effektivlik (RQ3)

`experiments/rq3_guardrails.py` 33 hücumu iki konfiqurasiyada sınayır:

| Konfiqurasiya | Təhlükəsiz nəticə |
|---|---|
| Tam stack (3 qat) | 33 / 33 (100%) |
| Yalnız baza (qoruyucu və xərc yoxlaması söndürülüb) | 30 / 33 (90,9%) |

Yalnız baza qatında keçən hücumlar: `information_schema` və `pg_stat_activity` vasitəsilə metadata oxumaq, böyük kartezian hasilin icrası. Yazma cəhdlərinin, rol dəyişməsinin, fayl oxumanın və başqa filialın datasının hamısını baza təkbaşına dayandırır. Nəticə: AST qoruyucusu metadata sızmasının və resurs israfının qarşısını alır, baza isə qoruyucu səhv etsə belə zərərli yazmanı və data sızmasını dayandırır. 60 normal sorğuda səhv bloklama 0%-dir.
