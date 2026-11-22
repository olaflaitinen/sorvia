-- V007: semantic layer.
--
-- The data dictionary lives inside the database as COMMENT ON statements, in
-- Azerbaijani with English glosses and synonyms. `sorvia index-schema` reads
-- these comments from the catalog, embeds them and stores them in
-- sorvia.schema_doc, where the retriever finds the relevant tables for a
-- question. Keeping the dictionary in the catalog means it is versioned with
-- the schema and can never drift from it.

COMMENT ON SCHEMA pharma IS 'Aptek şəbəkəsinin əməliyyat (OLTP) bazası. Pharmacy network operational data.';
COMMENT ON SCHEMA analytics IS 'Analitik ulduz sxemi (OLAP). Star schema for reporting.';

COMMENT ON TABLE pharma.branch IS
'Filiallar: aptek şəbəkəsinin şöbələri, mağazaları. Sinonimlər: filial, aptek, şöbə, mağaza, branch, store. Şəhər (city) üzrə yerləşir: Bakı, Gəncə, Sumqayıt və s.';
COMMENT ON COLUMN pharma.branch.code IS 'Filial kodu, məsələn BAK01';
COMMENT ON COLUMN pharma.branch.city IS 'Filialın yerləşdiyi şəhər';
COMMENT ON COLUMN pharma.branch.opened_on IS 'Filialın açılış tarixi';

COMMENT ON TABLE pharma.job_position IS 'Vəzifələr: əczaçı, kassir, filial meneceri. Sinonimlər: vəzifə, position, role.';

COMMENT ON TABLE pharma.employee IS
'İşçilər, əməkdaşlar, əczaçılar, kassirlər. Sinonimlər: işçi, əməkdaş, əczaçı, satıcı, kassir, employee, staff. Hər işçi bir filiala bağlıdır.';
COMMENT ON COLUMN pharma.employee.salary IS 'Aylıq maaş, AZN';
COMMENT ON COLUMN pharma.employee.hired_on IS 'İşə qəbul tarixi';
COMMENT ON COLUMN pharma.employee.is_active IS 'İşçi hazırda işləyirmi';

COMMENT ON TABLE pharma.manufacturer IS 'İstehsalçılar: dərman istehsal edən şirkətlər və onların ölkəsi. Sinonimlər: istehsalçı, firma, şirkət, brend, manufacturer.';

COMMENT ON TABLE pharma.category IS
'Dərman kateqoriyaları: antibiotik, ağrıkəsici, vitamin, ürək-damar və s. Sinonimlər: kateqoriya, qrup, növ, category. parent_id ilə iyerarxiya.';

COMMENT ON TABLE pharma.drug IS
'Dərmanlar kataloqu. Sinonimlər: dərman, preparat, məhsul, mal, medicine, drug, product. Ticarət adı (trade_name), təsiredici maddə (active_ingredient), forma (tablet, sirop, iynə), doza (strength), qiymət (unit_price, AZN), reseptli olub-olmaması (requires_prescription).';
COMMENT ON COLUMN pharma.drug.trade_name IS 'Dərmanın ticarət adı';
COMMENT ON COLUMN pharma.drug.active_ingredient IS 'Təsiredici maddə, məsələn paracetamol, amoxicillin';
COMMENT ON COLUMN pharma.drug.dosage_form IS 'Dərman forması: tablet, capsule, syrup, injection, ointment, drops, spray, powder';
COMMENT ON COLUMN pharma.drug.requires_prescription IS 'true olduqda dərman yalnız reseptlə satılır (reseptli dərman)';
COMMENT ON COLUMN pharma.drug.unit_price IS 'Bir vahidin pərakəndə qiyməti, AZN';
COMMENT ON COLUMN pharma.drug.min_stock IS 'Filialda saxlanmalı minimum qalıq';

COMMENT ON TABLE pharma.batch IS
'Dərman partiyaları (seriya, lot). Sinonimlər: partiya, seriya, lot, batch. Hər partiyanın istehsal və son istifadə tarixi (expires_on) var. Vaxtı keçmiş dərman: expires_on < bugünkü tarix.';
COMMENT ON COLUMN pharma.batch.expires_on IS 'Son istifadə tarixi (yararlılıq müddətinin bitməsi)';

COMMENT ON TABLE pharma.stock IS
'Anbar qalığı: hər filialda hər partiyadan neçə ədəd var. Sinonimlər: qalıq, ehtiyat, anbar, stok, inventory, stock.';

COMMENT ON TABLE pharma.customer IS
'Müştərilər, alıcılar, xəstələr. Sinonimlər: müştəri, alıcı, xəstə, customer, client. Bonus balı (bonus_points) loyallıq proqramıdır. FİN kodu şifrəlidir və oxunmur.';
COMMENT ON COLUMN pharma.customer.bonus_points IS 'Toplanmış bonus balı';
COMMENT ON COLUMN pharma.customer.birth_year IS 'Doğum ili; yaş = cari il - birth_year';

COMMENT ON TABLE pharma.doctor IS 'Həkimlər: resept yazan həkimlər, klinikası və ixtisası. Sinonimlər: həkim, doktor, doctor.';

COMMENT ON TABLE pharma.prescription IS 'Reseptlər: həkimin müştəriyə yazdığı resept, verilmə və etibarlılıq tarixi. Sinonimlər: resept, prescription.';
COMMENT ON TABLE pharma.prescription_item IS 'Reseptdəki dərmanlar və miqdarları; dispensed_quantity verilmiş miqdardır.';

COMMENT ON TABLE pharma.sale IS
'Satışlar (çeklər). Sinonimlər: satış, çek, qəbz, alış, sifariş, sale, receipt. Hər satış bir filialda, bir işçi tərəfindən edilir. gross_amount ümumi məbləğ, discount_amount endirim, net_amount ödənilən məbləğ (gəlir, dövriyyə), AZN. sold_at satış vaxtı.';
COMMENT ON COLUMN pharma.sale.sold_at IS 'Satış tarixi və vaxtı';
COMMENT ON COLUMN pharma.sale.net_amount IS 'Endirimdən sonra ödənilən məbləğ, gəlir';

COMMENT ON TABLE pharma.sale_item IS
'Satış sətirləri: çekdə hansı partiyadan neçə ədəd, hansı qiymətə satılıb. Sinonimlər: satılan məhsullar, çek sətri, sale line.';

COMMENT ON TABLE pharma.stock_transfer IS 'Filiallar arası dərman köçürmələri. Sinonimlər: köçürmə, transfer, yerdəyişmə.';

COMMENT ON TABLE pharma.batch_movement IS
'Partiya hərəkətləri jurnalı: daxilolma, satış, köçürmə, silinmə. İzlənmə (traceability) üçün: partiya harada olub. reason: receipt, sale, transfer_in, transfer_out, write_off, adjustment.';

COMMENT ON VIEW pharma.v_drug_catalog IS 'Dərman kataloqu kateqoriya və istehsalçı adları ilə birlikdə. Dərman, kateqoriya, istehsalçı, ölkə sualları üçün rahatdır.';
COMMENT ON VIEW pharma.v_sale_lines IS
'Satış sətirləri bütün detallarla: tarix, filial, şəhər, dərman adı, kateqoriya, miqdar, məbləğ (line_amount). Ən çox satılan dərmanlar, kateqoriya üzrə satış, filial üzrə satış sualları üçün əsas mənbə.';
COMMENT ON VIEW pharma.v_stock_by_drug IS 'Filial və dərman üzrə yararlı (vaxtı keçməmiş) qalıq.';
COMMENT ON VIEW pharma.v_low_stock IS 'Qalığı minimumdan aşağı düşən dərmanlar, az qalan dərmanlar.';
COMMENT ON VIEW pharma.v_expiring_soon IS 'Yaxın 30 gündə vaxtı bitəcək partiyalar, son istifadə tarixi yaxınlaşan dərmanlar.';
COMMENT ON VIEW pharma.v_branch_monthly_revenue IS 'Filiallar üzrə aylıq gəlir, satış sayı, endirimlər. Aylıq dövriyyə, gəlir müqayisəsi.';
