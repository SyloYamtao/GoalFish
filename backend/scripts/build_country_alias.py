#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
import unicodedata
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ALIAS = REPO_ROOT / "backend/app/services/external_data/country_alias.yaml"
SEEDS_DIR = REPO_ROOT / "data/external/seeds"
SEED_ALIAS = SEEDS_DIR / "country_alias.yaml"
INTL_RESULTS_SEED = SEEDS_DIR / "intl_results.csv"
NATIONAL_ELO_SEED = SEEDS_DIR / "national_elo.tsv"
FIFA_RANKING_SEED = SEEDS_DIR / "fifa_ranking.csv"
USER_AGENT = "GoalFish-Prediction/0.1"

FIFA_CODES_URL = "https://en.wikipedia.org/wiki/List_of_FIFA_country_codes"
INTL_RESULTS_URL = (
    "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
)
ELO_WORLD_URL = "https://eloratings.net/World.tsv"
ELO_TEAMS_URL = "https://eloratings.net/en.teams.tsv"
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"


ZH_OVERRIDES = {
    "ARG": "阿根廷",
    "AUS": "澳大利亚",
    "AUT": "奥地利",
    "BEL": "比利时",
    "BIH": "波黑",
    "BRA": "巴西",
    "CAN": "加拿大",
    "CIV": "科特迪瓦",
    "COD": "刚果民主共和国",
    "COL": "哥伦比亚",
    "CPV": "佛得角",
    "CRO": "克罗地亚",
    "CUW": "库拉索",
    "CZE": "捷克",
    "ECU": "厄瓜多尔",
    "EGY": "埃及",
    "ENG": "英格兰",
    "ESP": "西班牙",
    "FRA": "法国",
    "GER": "德国",
    "GHA": "加纳",
    "HAI": "海地",
    "IRN": "伊朗",
    "IRQ": "伊拉克",
    "JOR": "约旦",
    "JPN": "日本",
    "KOR": "韩国",
    "KSA": "沙特阿拉伯",
    "MAR": "摩洛哥",
    "MEX": "墨西哥",
    "NED": "荷兰",
    "NOR": "挪威",
    "NZL": "新西兰",
    "PAN": "巴拿马",
    "PAR": "巴拉圭",
    "POR": "葡萄牙",
    "QAT": "卡塔尔",
    "RSA": "南非",
    "SCO": "苏格兰",
    "SEN": "塞内加尔",
    "SUI": "瑞士",
    "SWE": "瑞典",
    "TUN": "突尼斯",
    "TUR": "土耳其",
    "URU": "乌拉圭",
    "USA": "美国",
    "UZB": "乌兹别克斯坦",
}

MANUAL_ALIASES = {
    "BIH": {
        "canonical_en": "Bosnia and Herzegovina",
        "fifa_md": ["Bosnia And Herzegovina"],
        "fm": ["Bosnia and Herzegovina"],
        "intl_results": ["Bosnia and Herzegovina", "Bosnia-Herzegovina"],
        "national_elo": ["Bosnia and Herzegovina", "Bosnia-Herzegovina", "BA"],
    },
    "CIV": {
        "canonical_en": "Côte d'Ivoire",
        "fifa_md": ["Côte D'Ivoire", "Cote D Ivoire"],
        "fm": ["Ivory Coast", "Cote d'Ivoire"],
        "intl_results": ["Ivory Coast", "Côte d'Ivoire", "Cote D Ivoire"],
        "national_elo": ["Ivory Coast", "Côte d'Ivoire", "CI"],
        "fifa_ranking": ["Côte d'Ivoire", "Cote d'Ivoire"],
    },
    "COD": {
        "canonical_en": "Congo DR",
        "fifa_md": ["Congo DR"],
        "fm": ["Democratic Republic of Congo", "DR Congo"],
        "intl_results": ["DR Congo", "Congo DR", "Democratic Republic of Congo", "Zaire"],
        "national_elo": ["DR Congo", "Democratic Republic of Congo", "CD", "ZR"],
    },
    "CPV": {
        "canonical_en": "Cabo Verde",
        "fifa_md": ["Cabo Verde"],
        "fm": ["Cape Verde Islands", "Cape Verde"],
        "intl_results": ["Cape Verde", "Cabo Verde"],
        "national_elo": ["Cape Verde", "Cabo Verde", "CV"],
        "fifa_ranking": ["Cabo Verde", "Cape Verde"],
    },
    "CUW": {
        "canonical_en": "Curaçao",
        "fifa_md": ["Curaçao", "Curacao"],
        "fm": ["Curaçao", "Curacao"],
        "intl_results": ["Curaçao", "Curacao", "Netherlands Antilles"],
        "national_elo": ["Curaçao", "Curacao", "CW", "AN"],
    },
    "CZE": {
        "canonical_en": "Czechia",
        "fifa_md": ["Czechia"],
        "fm": ["Czechia", "Czech Republic"],
        "intl_results": ["Czechia", "Czech Republic", "Czechoslovakia"],
        "national_elo": ["Czechia", "Czech Republic", "CZ", "CS"],
    },
    "ENG": {
        "canonical_en": "England",
        "national_elo": ["England", "EN"],
    },
    "IRN": {
        "canonical_en": "Iran",
        "fifa_md": ["IR Iran"],
        "fm": ["Iran"],
        "intl_results": ["Iran", "Iran (Islamic Republic of)"],
        "national_elo": ["Iran", "IR Iran", "IR"],
    },
    "IRL": {
        "canonical_en": "Republic of Ireland",
        "fifa_md": ["Republic of Ireland", "Ireland"],
        "fm": ["Republic of Ireland", "Ireland"],
        "intl_results": ["Republic of Ireland", "Ireland"],
        "national_elo": ["Republic of Ireland", "Ireland", "IE"],
    },
    "KOR": {
        "canonical_en": "Korea Republic",
        "fifa_md": ["Korea Republic"],
        "fm": ["South Korea"],
        "intl_results": ["South Korea", "Korea Republic", "Korea South"],
        "national_elo": ["South Korea", "Korea Republic", "KR"],
        "fifa_ranking": ["Korea Republic", "South Korea"],
    },
    "KSA": {
        "canonical_en": "Saudi Arabia",
        "national_elo": ["Saudi Arabia", "SA"],
    },
    "NED": {
        "canonical_en": "Netherlands",
        "national_elo": ["Netherlands", "NL", "Holland"],
    },
    "NIR": {
        "canonical_en": "Northern Ireland",
        "national_elo": ["Northern Ireland", "ND"],
    },
    "RSA": {
        "canonical_en": "South Africa",
        "national_elo": ["South Africa", "ZA"],
    },
    "SCO": {
        "canonical_en": "Scotland",
        "national_elo": ["Scotland", "SF"],
    },
    "TUR": {
        "canonical_en": "Türkiye",
        "fifa_md": ["Türkiye", "Turkey"],
        "fm": ["Türkiye", "Turkey"],
        "intl_results": ["Turkey", "Türkiye"],
        "national_elo": ["Turkey", "Türkiye", "TR"],
    },
    "USA": {
        "canonical_en": "United States",
        "fifa_md": ["USA", "United States"],
        "fm": ["United States", "USA"],
        "intl_results": ["United States", "USA", "United States of America"],
        "national_elo": ["United States", "USA", "US"],
    },
    "WAL": {
        "canonical_en": "Wales",
        "national_elo": ["Wales", "WA"],
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-network", action="store_true")
    args = parser.parse_args()

    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    aliases = build_aliases(skip_network=args.skip_network)
    write_alias_yaml(aliases, BACKEND_ALIAS)
    shutil.copyfile(BACKEND_ALIAS, SEED_ALIAS)

    if not args.skip_network:
        build_intl_results_seed(aliases)
        build_national_elo_seed()
    build_fifa_ranking_seed(aliases)

    print(f"wrote {BACKEND_ALIAS} ({len(aliases)} countries)")
    print(f"wrote {SEED_ALIAS}")
    if INTL_RESULTS_SEED.exists():
        print(f"wrote {INTL_RESULTS_SEED} ({count_rows(INTL_RESULTS_SEED)} rows)")
    if NATIONAL_ELO_SEED.exists():
        print(f"wrote {NATIONAL_ELO_SEED} ({count_rows(NATIONAL_ELO_SEED)} rows)")


def build_aliases(*, skip_network: bool = False) -> dict[str, dict[str, Any]]:
    fifa_rows = read_fifa_code_rows(skip_network=skip_network)
    aliases: dict[str, dict[str, Any]] = {}
    for row in fifa_rows:
        iso3 = row["code"]
        country = row["country"]
        aliases[iso3] = {
            "canonical_zh": ZH_OVERRIDES.get(iso3, country),
            "canonical_en": country,
            "fifa_md": [country],
            "intl_results": [country],
            "fm": [country],
            "national_elo": [country],
            "fifa_ranking": [country],
        }

    apply_local_team_metadata(aliases)
    apply_manual_aliases(aliases)
    if not skip_network:
        add_zh_langlinks(aliases)
        apply_local_team_metadata(aliases)
        add_elo_aliases(aliases)
        add_intl_results_aliases(aliases)

    return {iso3: normalize_entry(entry) for iso3, entry in sorted(aliases.items())}


def read_fifa_code_rows(*, skip_network: bool) -> list[dict[str, str]]:
    if skip_network and BACKEND_ALIAS.exists():
        existing = yaml.safe_load(BACKEND_ALIAS.read_text(encoding="utf-8"))
        return [
            {"code": iso3, "country": entry["canonical_en"]}
            for iso3, entry in existing.items()
        ]

    html = http_get(FIFA_CODES_URL).text
    tables = pd.read_html(StringIO(html))
    rows: list[dict[str, str]] = []
    for table in tables[:4]:
        for record in table.to_dict("records"):
            code = clean_code(record.get("Code"))
            country = clean_country(record.get("Country"))
            if code and country:
                rows.append({"code": code, "country": country})
    if len(rows) < 211:
        raise RuntimeError(f"Expected at least 211 FIFA members, got {len(rows)}")
    return rows[:211]


def apply_local_team_metadata(aliases: dict[str, dict[str, Any]]) -> None:
    path = REPO_ROOT / "data/wc2026_team_metadata.csv"
    if not path.exists():
        return
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            iso3 = row["team_iso3"]
            if iso3 not in aliases:
                aliases[iso3] = {
                    "canonical_zh": row["team_zh"],
                    "canonical_en": row["team_fifa"],
                }
            aliases[iso3]["canonical_zh"] = row["team_zh"]
            aliases[iso3]["canonical_en"] = row["team_fifa"]
            add_alias(aliases[iso3], "fifa_md", row["team_fifa"])
            add_alias(aliases[iso3], "intl_results", row["team_fifa"])
            add_alias(aliases[iso3], "fifa_ranking", row["team_fifa"])


def apply_manual_aliases(aliases: dict[str, dict[str, Any]]) -> None:
    for iso3, override in MANUAL_ALIASES.items():
        aliases.setdefault(
            iso3,
            {
                "canonical_zh": ZH_OVERRIDES.get(iso3, iso3),
                "canonical_en": override.get("canonical_en", iso3),
            },
        )
        entry = aliases[iso3]
        if "canonical_en" in override:
            entry["canonical_en"] = override["canonical_en"]
        if iso3 in ZH_OVERRIDES:
            entry["canonical_zh"] = ZH_OVERRIDES[iso3]
        for source, values in override.items():
            if source == "canonical_en":
                continue
            for value in values:
                add_alias(entry, source, value)
                if source != "fifa_md":
                    add_alias(entry, "intl_results", value)


def add_zh_langlinks(aliases: dict[str, dict[str, Any]]) -> None:
    titles = [str(entry["canonical_en"]) for entry in aliases.values()]
    zh_by_input: dict[str, str] = {}
    for chunk in chunks(titles, 50):
        response = requests.get(
            WIKIPEDIA_API_URL,
            params={
                "action": "query",
                "prop": "langlinks",
                "titles": "|".join(chunk),
                "lllang": "zh",
                "lllimit": "max",
                "format": "json",
                "redirects": "1",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()["query"]
        normalized = {
            item["from"]: item["to"] for item in payload.get("normalized", [])
        }
        redirects = {item["from"]: item["to"] for item in payload.get("redirects", [])}
        zh_by_title = {}
        for page in payload.get("pages", {}).values():
            langlinks = page.get("langlinks") or []
            if langlinks:
                zh_by_title[page["title"]] = langlinks[0]["*"]
        for title in chunk:
            resolved = normalized.get(title, title)
            resolved = redirects.get(resolved, resolved)
            zh = zh_by_title.get(resolved)
            if zh:
                zh_by_input[title] = zh

    for entry in aliases.values():
        zh = zh_by_input.get(str(entry["canonical_en"]))
        if zh:
            entry["canonical_zh"] = zh


def add_elo_aliases(aliases: dict[str, dict[str, Any]]) -> None:
    lookup = alias_lookup(aliases)
    for line in http_get(ELO_TEAMS_URL).text.splitlines():
        if not line.strip() or "_loc" in line.split("\t", 1)[0]:
            continue
        parts = line.split("\t")
        elo_code, names = parts[0], parts[1:]
        iso3 = None
        for name in names:
            iso3 = lookup.get(normalize_key(name))
            if iso3:
                break
        if not iso3:
            continue
        entry = aliases[iso3]
        add_alias(entry, "national_elo", elo_code)
        for name in names:
            add_alias(entry, "national_elo", name)


def add_intl_results_aliases(aliases: dict[str, dict[str, Any]]) -> None:
    lookup = alias_lookup(aliases)
    df = pd.read_csv(StringIO(http_get(INTL_RESULTS_URL).text), usecols=["home_team", "away_team"])
    teams = sorted(set(df["home_team"].dropna()) | set(df["away_team"].dropna()))
    for team in teams:
        iso3 = lookup.get(normalize_key(team))
        if iso3:
            add_alias(aliases[iso3], "intl_results", team)


def build_intl_results_seed(aliases: dict[str, dict[str, Any]]) -> None:
    lookup = alias_lookup(aliases)
    df = pd.read_csv(StringIO(http_get(INTL_RESULTS_URL).text))
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "home_score", "away_score"])
    df = df[df["date"] >= pd.Timestamp("2014-01-01")]
    df = df[~df["tournament"].str.contains("Friendly", case=False, na=False)]
    home_ok = df["home_team"].apply(lambda value: normalize_key(value) in lookup)
    away_ok = df["away_team"].apply(lambda value: normalize_key(value) in lookup)
    df = df[home_ok & away_ok].copy()
    before_2020 = df[df["date"] < pd.Timestamp("2020-01-01")].tail(400)
    since_2020 = df[df["date"] >= pd.Timestamp("2020-01-01")].tail(1200)
    seed = pd.concat([before_2020, since_2020], ignore_index=True)
    if len(seed) < 800:
        raise RuntimeError(f"intl_results seed too small: {len(seed)}")
    seed["date"] = seed["date"].dt.strftime("%Y-%m-%d")
    seed.to_csv(INTL_RESULTS_SEED, index=False)


def build_national_elo_seed() -> None:
    response = http_get(ELO_WORLD_URL)
    NATIONAL_ELO_SEED.write_text(response.content.decode("utf-8"), encoding="utf-8")


def build_fifa_ranking_seed(aliases: dict[str, dict[str, Any]]) -> None:
    with FIFA_RANKING_SEED.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "rank_date",
                "country",
                "rank",
                "points",
                "confederation",
                "total_points",
            ],
        )
        writer.writeheader()
        for rank, entry in enumerate(list(aliases.values())[:50], start=1):
            writer.writerow(
                {
                    "rank_date": "2026-06-12",
                    "country": entry["canonical_en"],
                    "rank": rank,
                    "points": "",
                    "confederation": "",
                    "total_points": "",
                }
            )


def write_alias_yaml(aliases: dict[str, dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            aliases,
            allow_unicode=True,
            sort_keys=True,
            default_flow_style=False,
            width=100,
        ),
        encoding="utf-8",
    )


def normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "canonical_zh": entry.get("canonical_zh") or entry.get("canonical_en"),
        "canonical_en": entry.get("canonical_en"),
    }
    for source in ["fifa_md", "intl_results", "fm", "national_elo", "fifa_ranking"]:
        values = entry.get(source, [])
        deduped = unique(values)
        if deduped:
            normalized[source] = deduped
    return normalized


def alias_lookup(aliases: dict[str, dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for iso3, entry in aliases.items():
        values = [iso3, entry.get("canonical_en"), entry.get("canonical_zh")]
        for source in ["fifa_md", "intl_results", "fm", "national_elo", "fifa_ranking"]:
            values.extend(entry.get(source, []))
        for value in values:
            key = normalize_key(str(value))
            if key and key not in lookup:
                lookup[key] = iso3
    return lookup


def add_alias(entry: dict[str, Any], source: str, value: str) -> None:
    if not value:
        return
    entry.setdefault(source, [])
    if value not in entry[source]:
        entry[source].append(value)


def unique(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if isinstance(values, str):
        values = [values]
    for value in values or []:
        text = str(value).strip()
        key = normalize_key(text)
        if text and key not in seen:
            out.append(text)
            seen.add(key)
    return out


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def clean_code(value: Any) -> str | None:
    match = re.search(r"[A-Z]{3}", str(value or ""))
    return match.group(0) if match else None


def clean_country(value: Any) -> str | None:
    text = re.sub(r"\[[^\]]+\]", "", str(value or "")).strip()
    return text or None


def normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.replace("&", " and ")
    ascii_value = re.sub(r"['`´’‘]", "", ascii_value)
    ascii_value = re.sub(r"[^a-zA-Z0-9]+", " ", ascii_value)
    return re.sub(r"\s+", " ", ascii_value).strip().lower()


def http_get(url: str) -> requests.Response:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response


def count_rows(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for line in handle if line.strip()) - 1


if __name__ == "__main__":
    csv.field_size_limit(sys.maxsize)
    main()
