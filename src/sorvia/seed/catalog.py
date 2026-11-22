"""Reference data for the synthetic pharmacy network "ŞəfaNet".

All brand and manufacturer names are fictional. Active ingredients, dosage
forms and prescription status are realistic so that questions and answers make
sense to a pharmacist.
"""

from __future__ import annotations

from dataclasses import dataclass

# code, name, city, address, traffic weight
BRANCHES: tuple[tuple[str, str, str, str, float], ...] = (
    ("BAK01", "ŞəfaNet Nizami", "Bakı", "Nizami küç. 45", 3.0),
    ("BAK02", "ŞəfaNet 28 May", "Bakı", "28 May küç. 12", 2.6),
    ("BAK03", "ŞəfaNet Gənclik", "Bakı", "Atatürk pr. 30", 2.4),
    ("BAK04", "ŞəfaNet Nərimanov", "Bakı", "Təbriz küç. 77", 2.0),
    ("BAK05", "ŞəfaNet Xətai", "Bakı", "Xətai pr. 18", 1.8),
    ("BAK06", "ŞəfaNet Yasamal", "Bakı", "Şərifzadə küç. 120", 1.7),
    ("BAK07", "ŞəfaNet Binəqədi", "Bakı", "Binəqədi şossesi 5", 1.4),
    ("BAK08", "ŞəfaNet Əhmədli", "Bakı", "Ə. Rəcəbli küç. 9", 1.3),
    ("SUM01", "ŞəfaNet Sumqayıt Mərkəz", "Sumqayıt", "Sülh küç. 3", 1.5),
    ("SUM02", "ŞəfaNet Sumqayıt 9-cu mkr", "Sumqayıt", "Nizami küç. 61", 1.0),
    ("GNC01", "ŞəfaNet Gəncə Mərkəz", "Gəncə", "Cavadxan küç. 22", 1.6),
    ("GNC02", "ŞəfaNet Gəncə Kəpəz", "Gəncə", "Şah İsmayıl Xətai pr. 40", 1.0),
    ("MNG01", "ŞəfaNet Mingəçevir", "Mingəçevir", "Heydər Əliyev pr. 14", 0.9),
    ("SHK01", "ŞəfaNet Şəki", "Şəki", "M. F. Axundzadə pr. 8", 0.8),
    ("LNK01", "ŞəfaNet Lənkəran", "Lənkəran", "Hüseyn Cavid küç. 6", 0.9),
    ("SHR01", "ŞəfaNet Şirvan", "Şirvan", "Rəsul Rza küç. 11", 0.7),
    ("NAX01", "ŞəfaNet Naxçıvan", "Naxçıvan", "Atatürk küç. 2", 0.8),
    ("QUB01", "ŞəfaNet Quba", "Quba", "Heydər Əliyev pr. 31", 0.6),
    ("QBL01", "ŞəfaNet Qəbələ", "Qəbələ", "Qəbələ şossesi 4", 0.5),
    ("XCM01", "ŞəfaNet Xaçmaz", "Xaçmaz", "Nizami küç. 19", 0.6),
)

POSITIONS = ("Əczaçı", "Kassir", "Filial meneceri", "Anbardar")

MALE_FIRST = ("Elvin", "Rauf", "Kamran", "Tural", "Orxan", "Nicat", "Ramil", "Fərid", "Elnur", "Səbuhi",
              "Anar", "Vüsal", "Rəşad", "Murad", "Emin", "Cavid", "Ruslan", "Samir", "Zaur", "İlkin")
FEMALE_FIRST = ("Aysel", "Leyla", "Günay", "Nərmin", "Səbinə", "Aynur", "Lalə", "Könül", "Fidan", "Nigar",
                "Xədicə", "Gülnar", "Ülviyyə", "Arzu", "Səadət", "Zəhra", "Mələk", "Aytən", "Türkan", "Sevinc")
LAST_STEMS = ("Məmmədov", "Əliyev", "Həsənov", "Hüseynov", "Quliyev", "İsmayılov", "Abbasov", "Rzayev",
              "Kərimov", "Cəfərov", "Babayev", "Nəsirov", "Səfərov", "Əhmədov", "Qasımov", "Vəliyev",
              "Orucov", "Şükürov", "Bayramov", "Musayev")

MANUFACTURERS: tuple[tuple[str, str], ...] = (
    ("Xəzər Farm", "Azərbaycan"), ("Abşeron Pharma", "Azərbaycan"), ("Kür Biotek", "Azərbaycan"),
    ("Anadolu Şifa", "Türkiyə"), ("Bosfor İlaç", "Türkiyə"), ("Tigris Pharma", "Türkiyə"),
    ("Rhein Medica", "Almaniya"), ("Alpen Pharm", "İsveçrə"), ("Danube Labs", "Avstriya"),
    ("Vistula Pharma", "Polşa"), ("Tisza Medic", "Macarıstan"), ("Seine Santé", "Fransa"),
    ("Thames BioScience", "Böyük Britaniya"), ("Ganga Generics", "Hindistan"), ("Dnipro Farm", "Ukrayna"),
    ("Volga Med", "Rusiya"), ("Adriatic Health", "Sloveniya"), ("Baltic Remedies", "Litva"),
    ("Nordic Cure", "Danimarka"), ("Kavkaz Farmatsevtika", "Gürcüstan"),
)

# name, parent name
CATEGORIES: tuple[tuple[str, str | None], ...] = (
    ("Antibiotiklər", None),
    ("Penisilinlər", "Antibiotiklər"),
    ("Makrolidlər", "Antibiotiklər"),
    ("Sefalosporinlər", "Antibiotiklər"),
    ("Ftorxinolonlar", "Antibiotiklər"),
    ("Ağrıkəsicilər və qızdırmasalıcılar", None),
    ("Qeyri-steroid iltihabəleyhinə", "Ağrıkəsicilər və qızdırmasalıcılar"),
    ("Ürək-damar preparatları", None),
    ("Antihipertenzivlər", "Ürək-damar preparatları"),
    ("Statinlər", "Ürək-damar preparatları"),
    ("Mədə-bağırsaq preparatları", None),
    ("Vitaminlər və minerallar", None),
    ("Allergiya əleyhinə", None),
    ("Soyuqdəymə və öskürək", None),
    ("Endokrinologiya", None),
    ("Antidiabetiklər", "Endokrinologiya"),
    ("Dermatologiya", None),
    ("Nevrologiya və psixiatriya", None),
    ("Oftalmologiya", None),
)

SPECIALTIES = ("Terapevt", "Pediatr", "Kardioloq", "Endokrinoloq", "Nevroloq", "Dermatoloq",
               "Oftalmoloq", "LOR", "Qastroenteroloq", "Ailə həkimi")
CLINICS = ("Mərkəzi Klinik Xəstəxana", "Şəhər Poliklinikası No 1", "Şəhər Poliklinikası No 5",
           "Respublika Diaqnostika Mərkəzi", "Gəncə Şəhər Xəstəxanası", "Sağlam Ailə Klinikası",
           "Medikal Plaza", "Uşaq Sağlamlıq Mərkəzi", "Kardiologiya Mərkəzi", "Göz Klinikası")


@dataclass(frozen=True)
class Ingredient:
    name: str
    category: str
    brands: tuple[str, ...]
    variants: tuple[tuple[str, str], ...]   # (dosage_form, strength)
    rx: bool
    base_price: float
    season: str | None = None               # "winter" | "spring" | None
    popularity: float = 1.0


INGREDIENTS: tuple[Ingredient, ...] = (
    Ingredient("amoxicillin", "Penisilinlər", ("Amoksin", "Flemoxa"),
               (("capsule", "500 mg"), ("tablet", "1000 mg"), ("powder", "250 mg/5 ml")), True, 6.5, "winter", 1.4),
    Ingredient("amoxicillin + clavulanic acid", "Penisilinlər", ("Amoklav", "Klavomed"),
               (("tablet", "875/125 mg"),), True, 14.0, "winter", 1.1),
    Ingredient("azithromycin", "Makrolidlər", ("Azitro", "Sumazin"),
               (("tablet", "500 mg"), ("capsule", "250 mg")), True, 9.0, "winter", 1.2),
    Ingredient("clarithromycin", "Makrolidlər", ("Klaromin",), (("tablet", "500 mg"),), True, 12.0, "winter", 0.6),
    Ingredient("cefuroxime", "Sefalosporinlər", ("Sefurin",), (("tablet", "500 mg"),), True, 11.0, "winter", 0.7),
    Ingredient("ceftriaxone", "Sefalosporinlər", ("Seftrion",), (("injection", "1 g"),), True, 3.2, "winter", 0.9),
    Ingredient("ciprofloxacin", "Ftorxinolonlar", ("Siproks",), (("tablet", "500 mg"),), True, 5.0, None, 0.7),
    Ingredient("levofloxacin", "Ftorxinolonlar", ("Levoks",), (("tablet", "500 mg"),), True, 8.0, None, 0.5),
    Ingredient("paracetamol", "Ağrıkəsicilər və qızdırmasalıcılar", ("Parasol", "Termofen"),
               (("tablet", "500 mg"), ("syrup", "120 mg/5 ml")), False, 1.2, "winter", 3.0),
    Ingredient("ibuprofen", "Qeyri-steroid iltihabəleyhinə", ("İbufen", "Nurolin"),
               (("tablet", "200 mg"), ("tablet", "400 mg"), ("syrup", "100 mg/5 ml")), False, 2.5, "winter", 2.6),
    Ingredient("diclofenac", "Qeyri-steroid iltihabəleyhinə", ("Diklonat",),
               (("tablet", "50 mg"), ("ointment", "1%")), False, 2.0, None, 1.3),
    Ingredient("ketorolac", "Qeyri-steroid iltihabəleyhinə", ("Ketanor",), (("tablet", "10 mg"),), True, 3.0, None, 0.8),
    Ingredient("metamizole", "Ağrıkəsicilər və qızdırmasalıcılar", ("Analgin-X",),
               (("tablet", "500 mg"),), False, 1.0, None, 1.5),
    Ingredient("amlodipine", "Antihipertenzivlər", ("Amlopin",), (("tablet", "5 mg"), ("tablet", "10 mg")),
               True, 3.5, None, 1.6),
    Ingredient("lisinopril", "Antihipertenzivlər", ("Lizinor",), (("tablet", "10 mg"),), True, 3.8, None, 1.1),
    Ingredient("losartan", "Antihipertenzivlər", ("Lozartin",), (("tablet", "50 mg"),), True, 6.0, None, 1.0),
    Ingredient("bisoprolol", "Antihipertenzivlər", ("Bisokor",), (("tablet", "5 mg"),), True, 4.2, None, 1.0),
    Ingredient("atorvastatin", "Statinlər", ("Atorvin",), (("tablet", "20 mg"), ("tablet", "40 mg")), True, 9.5, None, 1.2),
    Ingredient("rosuvastatin", "Statinlər", ("Rozustat",), (("tablet", "10 mg"),), True, 12.0, None, 0.8),
    Ingredient("acetylsalicylic acid", "Ürək-damar preparatları", ("Kardiosal",), (("tablet", "75 mg"),),
               False, 2.0, None, 1.5),
    Ingredient("omeprazole", "Mədə-bağırsaq preparatları", ("Omepral",), (("capsule", "20 mg"),), False, 3.0, None, 1.7),
    Ingredient("pantoprazole", "Mədə-bağırsaq preparatları", ("Pantaprim",), (("tablet", "40 mg"),), True, 7.0, None, 0.8),
    Ingredient("drotaverine", "Mədə-bağırsaq preparatları", ("Spazmolin",), (("tablet", "40 mg"),), False, 2.2, None, 1.4),
    Ingredient("loperamide", "Mədə-bağırsaq preparatları", ("Diaston",), (("capsule", "2 mg"),), False, 1.8, None, 0.9),
    Ingredient("mebeverine", "Mədə-bağırsaq preparatları", ("Mebispa",), (("capsule", "200 mg"),), True, 10.0, None, 0.5),
    Ingredient("ascorbic acid", "Vitaminlər və minerallar", ("Asvita",), (("tablet", "500 mg"), ("powder", "1 g")),
               False, 3.5, "winter", 1.8),
    Ingredient("cholecalciferol", "Vitaminlər və minerallar", ("D-Günəş",),
               (("drops", "500 IU/damcı"), ("tablet", "2000 IU")), False, 7.0, "winter", 1.5),
    Ingredient("multivitamin", "Vitaminlər və minerallar", ("Multivit Plus",), (("tablet", "30 tablet"),),
               False, 12.0, None, 1.0),
    Ingredient("magnesium + pyridoxine", "Vitaminlər və minerallar", ("MaqneB",), (("tablet", "470/5 mg"),),
               False, 8.0, None, 1.0),
    Ingredient("ferrous sulfate", "Vitaminlər və minerallar", ("Ferovit",), (("tablet", "100 mg"),), False, 6.0, None, 0.6),
    Ingredient("cetirizine", "Allergiya əleyhinə", ("Setrin",), (("tablet", "10 mg"), ("drops", "10 mg/ml")),
               False, 3.0, "spring", 1.6),
    Ingredient("loratadine", "Allergiya əleyhinə", ("Loradin",), (("tablet", "10 mg"),), False, 2.8, "spring", 1.3),
    Ingredient("desloratadine", "Allergiya əleyhinə", ("Deslor",), (("tablet", "5 mg"),), False, 5.5, "spring", 1.0),
    Ingredient("ambroxol", "Soyuqdəymə və öskürək", ("Ambrosan",), (("syrup", "15 mg/5 ml"), ("tablet", "30 mg")),
               False, 3.2, "winter", 1.8),
    Ingredient("acetylcysteine", "Soyuqdəymə və öskürək", ("Asetsin",), (("powder", "600 mg"),), False, 6.5, "winter", 1.1),
    Ingredient("xylometazoline", "Soyuqdəymə və öskürək", ("Rinoks",), (("spray", "0.1%"),), False, 2.9, "winter", 1.6),
    Ingredient("dextromethorphan", "Soyuqdəymə və öskürək", ("Tusifen",), (("syrup", "15 mg/5 ml"),),
               False, 4.0, "winter", 0.9),
    Ingredient("metformin", "Antidiabetiklər", ("Metforal",),
               (("tablet", "500 mg"), ("tablet", "850 mg"), ("tablet", "1000 mg")), True, 3.0, None, 1.5),
    Ingredient("gliclazide", "Antidiabetiklər", ("Diaglik",), (("tablet", "60 mg"),), True, 6.5, None, 0.8),
    Ingredient("insulin glargine", "Antidiabetiklər", ("Qlarin",), (("injection", "100 IU/ml"),), True, 38.0, None, 0.6),
    Ingredient("levothyroxine", "Endokrinologiya", ("Tiroksal",), (("tablet", "50 mcg"), ("tablet", "100 mcg")),
               True, 4.5, None, 0.9),
    Ingredient("clotrimazole", "Dermatologiya", ("Klotrim",), (("ointment", "1%"),), False, 2.4, None, 0.8),
    Ingredient("hydrocortisone", "Dermatologiya", ("Hidrokort",), (("ointment", "1%"),), False, 3.6, None, 0.7),
    Ingredient("sertraline", "Nevrologiya və psixiatriya", ("Sertalin",), (("tablet", "50 mg"),), True, 11.0, None, 0.6),
    Ingredient("gabapentin", "Nevrologiya və psixiatriya", ("Qabapen",), (("capsule", "300 mg"),), True, 14.0, None, 0.5),
    Ingredient("tobramycin", "Oftalmologiya", ("Tobrin",), (("drops", "0.3%"),), True, 6.8, None, 0.5),
    Ingredient("hypromellose", "Oftalmologiya", ("Göz Nəmi",), (("drops", "0.3%"),), False, 4.5, None, 0.8),
)

FORM_PRICE_FACTOR = {
    "tablet": 1.0, "capsule": 1.1, "syrup": 1.5, "injection": 1.0, "ointment": 1.3,
    "drops": 1.4, "spray": 1.2, "powder": 1.2,
}
