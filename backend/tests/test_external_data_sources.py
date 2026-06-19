from app.services.external_data import IntlResults, NationalElo, TeamNameNormalizer


def test_intl_results_offline():
    source = IntlResults()

    df = source.as_fit_dataframe(offline=True)

    assert len(df) >= 800
    assert list(df.columns) == [
        "date",
        "home_iso3",
        "away_iso3",
        "home_score",
        "away_score",
        "neutral",
    ]
    assert df["home_iso3"].notna().all()
    assert df["away_iso3"].notna().all()


def test_intl_results_cutoff_prevents_leakage():
    source = IntlResults()

    df = source.as_fit_dataframe(
        start_date="2014-01-01",
        cutoff_date="2020-01-01",
        offline=True,
    )

    assert len(df) > 0
    assert df["date"].max() < "2020-01-01"


def test_elo_fetch_and_parse():
    source = NationalElo()

    path = source.fetch(offline=True)
    df = source.as_dataframe()

    assert path.exists()
    assert "team_iso3" in df.columns
    assert "elo_rating" in df.columns
    assert len(df) >= 50
    assert df["team_iso3"].notna().all()


def test_external_source_fingerprint_from_offline_seed():
    source = NationalElo()

    source.fetch(offline=True)
    fingerprint = source.fingerprint()

    assert fingerprint["source"] == "national_elo"
    assert fingerprint["url_used"].startswith("seed://")
    assert fingerprint["row_count"] >= 50
    assert len(fingerprint["sha256_first_kb"]) == 64


def test_team_normalizer_wc2026_mappings():
    norm = TeamNameNormalizer()

    assert norm.to_iso3("Korea Republic", source="fifa_md") == "KOR"
    assert norm.to_iso3("South Korea", source="fm") == "KOR"
    assert norm.to_iso3("IR Iran", source="fifa_md") == "IRN"
    assert norm.to_iso3("Cabo Verde", source="fifa_md") == "CPV"
    assert norm.to_iso3("Cape Verde Islands", source="fm") == "CPV"
    assert norm.to_iso3("Côte D'Ivoire", source="fifa_md") == "CIV"
    assert norm.to_iso3("Ivory Coast", source="fm") == "CIV"
    assert norm.to_iso3("波黑") == "BIH"


def test_team_normalizer_does_not_match_markdown_extension_as_country_alias():
    norm = TeamNameNormalizer()

    assert norm.to_iso3("突尼斯赛前信息报告.md") == "TUN"
    assert norm.to_iso3("赛前信息报告.md") is None


def test_team_normalizer_alias_file_covers_fifa_members():
    norm = TeamNameNormalizer()

    assert len(norm.alias_map) >= 211
    assert norm.to_canonical_zh("KOR") == "韩国"
    assert norm.to_iso3("Cote D Ivoire", source=None) == "CIV"
