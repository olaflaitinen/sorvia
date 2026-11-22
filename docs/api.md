# HTTP API

İnteraktiv sənəd (OpenAPI): `http://localhost:8000/docs`. Bütün `/v1` endpoint-ləri (login istisna olmaqla) `Authorization: Bearer <token>` tələb edir. Xətalar `{"code": "...", "message": "..."}` formatındadır.

## Autentifikasiya

| Metod | Yol | Kim | Təsvir |
|---|---|---|---|
| POST | `/v1/auth/token` | hamı | `{"username", "password"}`, JWT qaytarır |
| GET | `/v1/me` | daxil olmuş | cari istifadəçi |

## Suallar

| Metod | Yol | Kim | Təsvir |
|---|---|---|---|
| POST | `/v1/ask` | daxil olmuş | `{"question", "strategy"?}`. Cavab: `status` (`ok`, `blocked`, `error`, `timeout`), `sql`, `columns`, `rows`, `reason_code`, `message`, `relations`, `timings_ms` |
| GET | `/v1/queries?status=&limit=` | daxil olmuş | sorğu jurnalı; əczaçı yalnız özününkünü görür |
| POST | `/v1/queries/{id}/feedback` | sahibi, menecer, admin | `{"is_correct", "comment"?}`; real istifadədə dəqiqliyin ölçülməsi üçün |
| GET | `/v1/schema` | daxil olmuş | semantik qat: obyektlər və təsvirləri |

`reason_code` dəyərləri: `cannot_answer`, `not_a_query`, `multiple_statements`, `forbidden_construct`, `function_not_allowed`, `system_object`, `schema_not_allowed`, `unknown_relation`, `too_complex`, `cost_limit`, `timeout`, `insufficient_privilege`, `llm_unavailable`.

## Əməliyyatlar

| Metod | Yol | Kim | Təsvir |
|---|---|---|---|
| POST | `/v1/sales` | daxil olmuş | `{"employee_id", "items": [{"drug_id", "quantity"}], "customer_id"?, "prescription_id"?, "branch_id"?}`. Əczaçı üçün filial avtomatik özününküdür |
| POST | `/v1/transfers` | daxil olmuş | `{"to_branch_id", "batch_id", "quantity", "employee_id", "from_branch_id"?}` |
| GET | `/v1/stock/low` | daxil olmuş | minimumdan aşağı qalıq (RLS ilə) |
| GET | `/v1/stock/expiring` | daxil olmuş | 30 gündə vaxtı bitəcək partiyalar (RLS ilə) |
| GET | `/v1/batches/{id}/trace?at=` | daxil olmuş | partiyanın verilən anda yeri |
| POST | `/v1/analytics/refresh?full=` | menecer, admin | ulduz sxeminin yenilənməsi |

Biznes qaydası xətaları `409` ilə qaytarılır: `expired_batch`, `prescription_required`, `insufficient_stock`, `invalid_employee`, `immutable_record`.

## Monitorinq və özünü optimallaşdırma

| Metod | Yol | Kim | Təsvir |
|---|---|---|---|
| GET | `/v1/stats?days=` | menecer, admin | status üzrə say, orta və p95 gecikmə, bloklanma səbəbləri, istifadəçi rəyinə görə dəqiqlik |
| GET | `/v1/advisor/recommendations` | menecer, admin | indeks tövsiyələri |
| POST | `/v1/advisor/run` | admin | jurnal üzərində məsləhətçini işə salır |
| POST | `/v1/advisor/recommendations/{id}/apply` | admin | indeksi yaradır (mümkün olduqda `CONCURRENTLY`) |
| POST | `/v1/advisor/recommendations/{id}/reject` | admin | tövsiyəni rədd edir |

## Sağlamlıq

`GET /healthz` (proses canlıdır), `GET /readyz` (hər iki connection pool bazaya çatır).
