# Yerləşdirmə

## Vercel + Neon (tövsiyə olunan)

Repoda hazır konfiqurasiya var: `vercel.json`, `api/index.py` (FastAPI serverless funksiya kimi) və `scripts/vercel-build.sh`.

1. Vercel-də **Add New Project** seçin və bu GitHub reposunu import edin. Framework preset: **Other**. Qalan parametrlər `vercel.json`-dan oxunur.
2. **Storage** bölməsindən **Neon Postgres** əlavə edib layihəyə qoşun. Vercel `DATABASE_URL` və `DATABASE_URL_UNPOOLED` dəyişənlərini avtomatik yaradır.
3. Əlavə gizli açar yazmaq lazım deyil. `DATABASE_URL` təyin olunduqda JWT açarı, FİN şifrələmə açarı və `sorvia_api`, `sorvia_nl` rollarının parolları ondan HMAC-SHA256 ilə serverdə törədilir. İstəsəniz, bunları açıq şəkildə təyin edə bilərsiniz:

| Dəyişən | Təyinat |
|---|---|
| `SORVIA_ENVIRONMENT` | `production` (zəif açarlarla işə düşməyi qadağan edir) |
| `SORVIA_JWT_SECRET`, `SORVIA_FIN_KEY` | törədilmiş açarların əvəzinə öz açarlarınız |
| `SORVIA_API_DB_PASSWORD`, `SORVIA_NL_DB_PASSWORD` | rolların parolları |
| `SORVIA_DEMO_PASSWORD` | demo istifadəçilərin parolu (default: `Sorvia-Demo-2026`) |
| `SORVIA_SHOW_DEMO_PASSWORD` | `false`: demo parolu giriş səhifəsində göstərilmir |
| `SORVIA_POOL_MIN_SIZE` | `0` (serverless üçün tövsiyə olunur) |

4. **Deploy**. Build zamanı `scripts/vercel-build.sh` bazanı avtomatik hazırlayır: miqrasiyalar, `sorvia_api` və `sorvia_nl` rolları, demo data (yalnız baza boşdursa) və semantik qat. Bu addımlar idempotentdir, hər deploy-da təhlükəsiz təkrarlanır.

Real dil modeli üçün əlavə olaraq `SORVIA_LLM_PROVIDER=openai`, `SORVIA_LLM_BASE_URL`, `SORVIA_LLM_MODEL` və `SORVIA_LLM_API_KEY` təyin edin. Bunlar olmadan sistem oflayn rejimdə işləyir və test dəstindəki 60 suala cavab verir.

### Neon üçün qeydlər

- Neon superuser icazəsi vermir. Seed buna görə trigger-ləri `ALTER TABLE ... DISABLE TRIGGER USER` ilə müvəqqəti söndürür, `session_replication_role` yalnız superuser olduqda istifadə olunur.
- Tətbiq bağlantıları Neon-un pooler ünvanından (`DATABASE_URL`), miqrasiyalar birbaşa ünvandan (`DATABASE_URL_UNPOOLED`) gedir. Pooler-in transaction rejimi üçün prepared statement-lər söndürülüb.
- `pgvector`, `hypopg`, `pgcrypto` və `pg_stat_statements` Neon-da mövcuddur.

## Docker

```bash
cp .env.example .env    # parolları dəyişin
docker compose up --build
```

Bir konteyner həm API-ni, həm veb interfeysi `http://localhost:8000` ünvanında təqdim edir.

## Lokal inkişaf

```bash
sorvia serve                       # API, :8000
npm --prefix web run dev           # veb interfeys, :5173 (API-yə proxy ilə)
```
