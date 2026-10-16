"""League catalogue presentation: featured leagues, regions, Korean names.

Pure lookups (no DB, no network) shared by ingestion (backfill priority) and
the API (categorisation). Anything not listed falls back to sensible defaults,
so a new league from the provider still shows up, just lower in the order.
"""

from __future__ import annotations

# (provider, league provider_id) -> rank (lower = shown first)
FEATURED: dict[tuple[str, str], int] = {
    ("api_football", "39"): 1,  # England Premier League
    ("api_football", "140"): 2,  # Spain La Liga
    ("api_football", "135"): 3,  # Italy Serie A
    ("api_football", "78"): 4,  # Germany Bundesliga
    ("api_football", "61"): 5,  # France Ligue 1
    ("api_football", "2"): 6,  # UEFA Champions League
    ("api_football", "3"): 7,  # UEFA Europa League
    ("api_football", "292"): 8,  # South Korea K League 1
    ("api_football", "98"): 9,  # Japan J1 League
    ("api_football", "88"): 10,  # Netherlands Eredivisie
    ("api_football", "94"): 11,  # Portugal Primeira Liga
    ("api_football", "40"): 12,  # England Championship
    ("api_football", "253"): 13,  # USA MLS
    ("api_football", "71"): 14,  # Brazil Serie A
    ("api_football", "307"): 15,  # Saudi Pro League
    ("api_football", "848"): 16,  # UEFA Conference League
    ("mock", "eng-1"): 1,
    ("mock", "esp-1"): 2,
    ("mock", "kor-1"): 3,
    ("mock", "eng-cup"): 4,
}

REGIONS = ("international", "europe", "asia", "south_america", "north_america", "africa", "oceania")
REGION_KO = {
    "international": "국제 대회",
    "europe": "유럽",
    "asia": "아시아",
    "south_america": "남미",
    "north_america": "북중미",
    "africa": "아프리카",
    "oceania": "오세아니아",
    "other": "기타",
}

_EUROPE = [
    "Albania",
    "Andorra",
    "Armenia",
    "Austria",
    "Azerbaijan",
    "Belarus",
    "Belgium",
    "Bosnia",
    "Bulgaria",
    "Croatia",
    "Cyprus",
    "Czech-Republic",
    "Denmark",
    "England",
    "Estonia",
    "Faroe-Islands",
    "Finland",
    "France",
    "Georgia",
    "Germany",
    "Gibraltar",
    "Greece",
    "Hungary",
    "Iceland",
    "Ireland",
    "Israel",
    "Italy",
    "Kazakhstan",
    "Kosovo",
    "Latvia",
    "Liechtenstein",
    "Lithuania",
    "Luxembourg",
    "Macedonia",
    "Malta",
    "Moldova",
    "Montenegro",
    "Netherlands",
    "Northern-Ireland",
    "Norway",
    "Poland",
    "Portugal",
    "Romania",
    "Russia",
    "San-Marino",
    "Scotland",
    "Serbia",
    "Slovakia",
    "Slovenia",
    "Spain",
    "Sweden",
    "Switzerland",
    "Turkey",
    "Ukraine",
    "Wales",
]
_ASIA = [
    "Australia",
    "Bahrain",
    "Bangladesh",
    "Cambodia",
    "China",
    "Chinese-Taipei",
    "Hong-Kong",
    "India",
    "Indonesia",
    "Iran",
    "Iraq",
    "Japan",
    "Jordan",
    "Kuwait",
    "Kyrgyzstan",
    "Laos",
    "Lebanon",
    "Macao",
    "Malaysia",
    "Mongolia",
    "Myanmar",
    "Nepal",
    "Oman",
    "Pakistan",
    "Palestine",
    "Philippines",
    "Qatar",
    "Saudi-Arabia",
    "Singapore",
    "South-Korea",
    "Syria",
    "Tajikistan",
    "Thailand",
    "Turkmenistan",
    "United-Arab-Emirates",
    "Uzbekistan",
    "Vietnam",
    "Yemen",
]
_SOUTH_AMERICA = "Argentina Bolivia Brazil Chile Colombia Ecuador Paraguay Peru Uruguay Venezuela"
_NORTH_AMERICA = [
    "Canada",
    "Costa-Rica",
    "Cuba",
    "Dominican-Republic",
    "El-Salvador",
    "Guatemala",
    "Haiti",
    "Honduras",
    "Jamaica",
    "Mexico",
    "Nicaragua",
    "Panama",
    "Trinidad-And-Tobago",
    "USA",
]
_AFRICA = [
    "Algeria",
    "Angola",
    "Benin",
    "Botswana",
    "Burkina-Faso",
    "Burundi",
    "Cameroon",
    "Congo",
    "Congo-DR",
    "Egypt",
    "Ethiopia",
    "Gabon",
    "Gambia",
    "Ghana",
    "Guinea",
    "Ivory-Coast",
    "Kenya",
    "Libya",
    "Mali",
    "Mauritania",
    "Morocco",
    "Mozambique",
    "Namibia",
    "Niger",
    "Nigeria",
    "Rwanda",
    "Senegal",
    "South-Africa",
    "Sudan",
    "Tanzania",
    "Togo",
    "Tunisia",
    "Uganda",
    "Zambia",
    "Zimbabwe",
]
_OCEANIA = ["Fiji", "New-Zealand", "Papua-New-Guinea"]

_REGION_OF: dict[str, str] = {}
for _region, _names in (
    ("europe", _EUROPE),
    ("asia", _ASIA),  # AFC: Australia plays in Asia
    ("south_america", _SOUTH_AMERICA.split()),
    ("north_america", _NORTH_AMERICA),
    ("africa", _AFRICA),
    ("oceania", _OCEANIA),
):
    for _n in _names:
        _REGION_OF[_n.replace("-", " ").lower()] = _region
_REGION_OF["world"] = "international"

COUNTRY_KO = {
    "World": "국제",
    "England": "잉글랜드",
    "Spain": "스페인",
    "Italy": "이탈리아",
    "Germany": "독일",
    "France": "프랑스",
    "Netherlands": "네덜란드",
    "Portugal": "포르투갈",
    "Belgium": "벨기에",
    "Scotland": "스코틀랜드",
    "Turkey": "튀르키예",
    "Austria": "오스트리아",
    "Switzerland": "스위스",
    "Greece": "그리스",
    "Denmark": "덴마크",
    "Sweden": "스웨덴",
    "Norway": "노르웨이",
    "Poland": "폴란드",
    "Russia": "러시아",
    "Ukraine": "우크라이나",
    "Croatia": "크로아티아",
    "Serbia": "세르비아",
    "Czech Republic": "체코",
    "Czech-Republic": "체코",
    "South Korea": "대한민국",
    "South-Korea": "대한민국",
    "Japan": "일본",
    "China": "중국",
    "Australia": "호주",
    "Saudi Arabia": "사우디아라비아",
    "Saudi-Arabia": "사우디아라비아",
    "Qatar": "카타르",
    "United Arab Emirates": "아랍에미리트",
    "United-Arab-Emirates": "아랍에미리트",
    "Thailand": "태국",
    "Vietnam": "베트남",
    "India": "인도",
    "Iran": "이란",
    "Brazil": "브라질",
    "Argentina": "아르헨티나",
    "Chile": "칠레",
    "Colombia": "콜롬비아",
    "Uruguay": "우루과이",
    "Mexico": "멕시코",
    "USA": "미국",
    "Canada": "캐나다",
    "Egypt": "이집트",
    "Morocco": "모로코",
    "South Africa": "남아프리카공화국",
    "South-Africa": "남아프리카공화국",
    "Nigeria": "나이지리아",
}


def region_of(country: str) -> str:
    return _REGION_OF.get(country.replace("-", " ").lower(), "other")


def country_ko(country: str) -> str:
    return COUNTRY_KO.get(country, country.replace("-", " "))


def featured_rank(provider: str, provider_id: str) -> int | None:
    return FEATURED.get((provider, provider_id))
