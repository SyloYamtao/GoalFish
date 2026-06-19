"""Football match context extraction for Step2 modeling."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .external_data.team_name_normalizer import TeamNameNormalizer
from .llm_budget import LLMCallLedger


EXTRACTOR_VERSION = "v1"
FEATURE_FLAG_ENV = "GOALFISH_USE_FOOTBALL_DATA_EXTRACTOR"

_COMPETITION_META_KEYS = (
    "tournament",
    "stage",
    "knockout",
    "neutral_venue",
    "host_country_iso3",
)

_STAGE_ALIASES = {
    "group": "group",
    "group_stage": "group",
    "小组赛": "group",
    "round_of_16": "round_of_16",
    "last_16": "round_of_16",
    "16强": "round_of_16",
    "十六强": "round_of_16",
    "八分之一决赛": "round_of_16",
    "quarter_final": "quarter_final",
    "quarterfinal": "quarter_final",
    "quarter-final": "quarter_final",
    "四分之一决赛": "quarter_final",
    "八强": "quarter_final",
    "semi_final": "semi_final",
    "semifinal": "semi_final",
    "semi-final": "semi_final",
    "半决赛": "semi_final",
    "final": "final",
    "决赛": "final",
    "third_place": "third_place",
    "third-place": "third_place",
    "三四名": "third_place",
    "季军赛": "third_place",
}

_KNOCKOUT_STAGES = {"round_of_16", "quarter_final", "semi_final", "third_place", "final"}

_WORLD_CUP_2026_HOST_HINTS = {
    "CAN": (
        "canada",
        "加拿大",
        "toronto",
        "多伦多",
        "vancouver",
        "温哥华",
        "bc place",
    ),
    "MEX": (
        "mexico city",
        "ciudad de mexico",
        "ciudad de méxico",
        "guadalajara",
        "瓜达拉哈拉",
        "monterrey",
        "蒙特雷",
        "estadio akron",
        "akron stadium",
        "mexico city stadium",
        "guadalajara stadium",
        "monterrey stadium",
        "estadio ciudad de mexico",
        "estadio ciudad de méxico",
    ),
    "USA": (
        "united states",
        "usa",
        "美国",
        "atlanta",
        "亚特兰大",
        "boston",
        "波士顿",
        "dallas",
        "达拉斯",
        "houston",
        "休斯顿",
        "kansas city",
        "堪萨斯城",
        "los angeles",
        "洛杉矶",
        "miami",
        "迈阿密",
        "new york",
        "new jersey",
        "纽约",
        "新泽西",
        "philadelphia",
        "费城",
        "san francisco",
        "bay area",
        "旧金山",
        "seattle",
        "西雅图",
        "atlanta stadium",
        "boston stadium",
        "dallas stadium",
        "houston stadium",
        "kansas city stadium",
        "los angeles stadium",
        "miami stadium",
        "new york new jersey stadium",
        "philadelphia stadium",
        "san francisco bay area stadium",
        "seattle stadium",
    ),
}

_COMMON_PLAYER_TEAM_HINTS = {
    "内马尔": "BRA",
    "neymar": "BRA",
    "neymar jr": "BRA",
    "梅西": "ARG",
    "messi": "ARG",
    "lionel messi": "ARG",
}


@dataclass
class ExtractedMatchContext:
    home_iso3: str
    away_iso3: str
    home_name_zh: str
    away_name_zh: str
    competition_meta: dict
    key_narratives: list[str]
    injury_reports: list[dict]
    tactical_notes: list[dict]
    extracted_by: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FootballDataExtractor:
    """Extract structured match context with LLM first, regex fallback second."""

    def __init__(
        self,
        *,
        llm_client: Any | None = None,
        normalizer: TeamNameNormalizer | None = None,
    ):
        self._llm_client = llm_client
        self._normalizer = normalizer or TeamNameNormalizer()
        self._raw_alias_index = _build_raw_alias_index(self._normalizer)
        self._mention_aliases = sorted(
            self._raw_alias_index.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )

    def extract(
        self,
        *,
        prediction_requirement: str | None = None,
        graph_id: str | None = None,
        llm_ledger: LLMCallLedger | None = None,
        req: str | None = None,
    ) -> ExtractedMatchContext:
        if llm_ledger is None:
            raise ValueError("llm_ledger is required")

        source_text = prediction_requirement if prediction_requirement is not None else req
        source_text = source_text or ""
        if not _env_flag_enabled(FEATURE_FLAG_ENV):
            return self._regex_fallback(source_text)

        budget = _ledger_budget(llm_ledger)
        if not getattr(budget, "enable_llm_data_extraction", False):
            return self._regex_fallback(source_text)

        messages = self._build_prompt(
            prediction_requirement=source_text,
            graph_id=graph_id or "",
        )
        try:
            with llm_ledger.acquire(
                role="data_extractor",
                prompt_version=EXTRACTOR_VERSION,
                prompt=messages,
            ) as call:
                if call.cached:
                    result = call.result
                else:
                    started = time.perf_counter()
                    result = self._llm().chat_json(
                        messages=messages,
                        temperature=0.0,
                        max_tokens=2000,
                    )
                    latency_ms = round((time.perf_counter() - started) * 1000)
                    call.complete(result, tokens=0, cost=0.0, latency_ms=latency_ms)

            return self._context_from_mapping(result, source_text=source_text, extracted_by="llm")
        except Exception as exc:
            llm_ledger.record_failure(
                role="data_extractor",
                reason="llm_extraction_failed",
                fallback="regex_fallback",
                error=str(exc),
            )
            return self._regex_fallback(source_text)

    def _llm(self) -> Any:
        if self._llm_client is None:
            from app.utils.llm_client import LLMClient

            self._llm_client = LLMClient()
        return self._llm_client

    def _build_prompt(self, *, prediction_requirement: str, graph_id: str) -> list[dict[str, str]]:
        schema = {
            "type": "object",
            "required": [
                "home_iso3",
                "away_iso3",
                "home_name_zh",
                "away_name_zh",
                "competition_meta",
                "key_narratives",
                "injury_reports",
                "tactical_notes",
            ],
            "properties": {
                "home_iso3": {"type": "string", "description": "Home team FIFA/ISO3 code, e.g. BRA"},
                "away_iso3": {"type": "string", "description": "Away team FIFA/ISO3 code, e.g. ARG"},
                "home_name_zh": {"type": "string"},
                "away_name_zh": {"type": "string"},
                "competition_meta": {
                    "type": "object",
                    "properties": {
                        "tournament": {"type": ["string", "null"]},
                        "stage": {
                            "enum": [
                                "group",
                                "round_of_16",
                                "quarter_final",
                                "semi_final",
                                "third_place",
                                "final",
                                None,
                            ]
                        },
                        "knockout": {"type": "boolean"},
                        "neutral_venue": {"type": "boolean"},
                        "host_country_iso3": {"type": ["string", "null"]},
                    },
                },
                "key_narratives": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recent form, stakes, star players, matchup context.",
                },
                "injury_reports": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Each item should include player, team_iso3, status, evidence_span when possible.",
                },
                "tactical_notes": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Each item should include team_iso3 and note.",
                },
            },
        }
        return [
            {
                "role": "system",
                "content": (
                    "你是足球比赛数据抽取器。只输出合法 JSON object。"
                    "从用户需求、图谱标识和上下文中抽取结构化比赛上下文；"
                    "未知值使用 null 或空数组，不要编造事实。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"graph_id: {graph_id}\n"
                    f"JSON schema: {schema}\n\n"
                    f"prediction_requirement:\n{prediction_requirement}"
                ),
            },
        ]

    def _context_from_mapping(
        self,
        payload: Any,
        *,
        source_text: str,
        extracted_by: str,
    ) -> ExtractedMatchContext:
        if not isinstance(payload, Mapping):
            raise ValueError("LLM extraction result must be a JSON object")

        fallback_home, fallback_away = self._resolve_team_pair(source_text)
        home_iso3 = (
            _clean_iso3(payload.get("home_iso3"))
            or self._resolve_team_name(str(payload.get("home_name_zh") or ""))
            or fallback_home
        )
        away_iso3 = (
            _clean_iso3(payload.get("away_iso3"))
            or self._resolve_team_name(str(payload.get("away_name_zh") or ""))
            or fallback_away
        )

        competition_payload = payload.get("competition_meta") or payload.get("competition") or {}
        competition_meta = self._normalize_competition_meta(
            competition_payload,
            source_text,
            home_iso3=home_iso3,
            away_iso3=away_iso3,
        )

        return ExtractedMatchContext(
            home_iso3=home_iso3 or "",
            away_iso3=away_iso3 or "",
            home_name_zh=str(payload.get("home_name_zh") or self._canonical_zh(home_iso3) or ""),
            away_name_zh=str(payload.get("away_name_zh") or self._canonical_zh(away_iso3) or ""),
            competition_meta=competition_meta,
            key_narratives=_string_list(payload.get("key_narratives") or payload.get("narratives")),
            injury_reports=_dict_list(payload.get("injury_reports") or payload.get("injuries_suspensions")),
            tactical_notes=_dict_list(payload.get("tactical_notes")),
            extracted_by=extracted_by,
        )

    def _regex_fallback(self, source_text: str) -> ExtractedMatchContext:
        home_iso3, away_iso3 = self._resolve_team_pair(source_text)
        return ExtractedMatchContext(
            home_iso3=home_iso3 or "",
            away_iso3=away_iso3 or "",
            home_name_zh=self._canonical_zh(home_iso3) or "",
            away_name_zh=self._canonical_zh(away_iso3) or "",
            competition_meta=self._infer_competition_meta(
                source_text,
                home_iso3=home_iso3,
                away_iso3=away_iso3,
            ),
            key_narratives=_extract_key_narratives(source_text),
            injury_reports=self._extract_injury_reports(source_text, home_iso3, away_iso3),
            tactical_notes=_extract_tactical_notes(source_text, home_iso3, away_iso3),
            extracted_by="regex_fallback",
        )

    def _resolve_team_pair(self, text: str) -> tuple[str | None, str | None]:
        explicit_pair = self._resolve_explicit_pair(text)
        if explicit_pair != (None, None):
            return explicit_pair

        mentions = self._find_team_mentions(text)
        if len(mentions) >= 2:
            return mentions[0][1], mentions[1][1]
        if len(mentions) == 1:
            return mentions[0][1], None
        return None, None

    def _resolve_explicit_pair(self, text: str) -> tuple[str | None, str | None]:
        patterns = [
            r"(?P<home>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z .'\-]{1,40}?)\s*(?:vs\.?|VS|v\.?|对阵|对)\s*(?P<away>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z .'\-]{1,40})",
            r"(?P<home>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z .'\-]{1,40}?)\s+[0-9]\s*[-:：]\s*[0-9]\s+(?P<away>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z .'\-]{1,40})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            home = self._resolve_team_name(_trim_team_fragment(match.group("home")))
            away = self._resolve_team_name(_trim_team_fragment(match.group("away")))
            if home and away and home != away:
                return home, away
        return None, None

    def _resolve_team_name(self, value: str) -> str | None:
        candidate = _trim_team_fragment(value)
        if not candidate:
            return None

        direct = self._raw_alias_index.get(candidate.casefold())
        if direct:
            return direct

        direct = self._raw_alias_index.get(candidate)
        if direct:
            return direct

        iso3 = _clean_iso3(candidate)
        if iso3 and iso3 in self._normalizer.alias_map:
            return iso3

        normalized = self._normalizer.to_iso3(candidate)
        if normalized:
            return normalized

        mentions = self._find_team_mentions(candidate)
        return mentions[0][1] if mentions else None

    def _find_team_mentions(self, text: str) -> list[tuple[int, str]]:
        if not text:
            return []

        mentions_by_iso3: dict[str, int] = {}
        for alias, iso3 in self._mention_aliases:
            position = _find_alias_position(text, alias)
            if position < 0:
                continue
            current = mentions_by_iso3.get(iso3)
            if current is None or position < current:
                mentions_by_iso3[iso3] = position

        return sorted((position, iso3) for iso3, position in mentions_by_iso3.items())

    def _canonical_zh(self, iso3: str | None) -> str | None:
        if not iso3:
            return None
        return self._normalizer.to_canonical_zh(iso3)

    def _normalize_competition_meta(
        self,
        payload: Any,
        source_text: str,
        *,
        home_iso3: str | None = None,
        away_iso3: str | None = None,
    ) -> dict[str, Any]:
        inferred = self._infer_competition_meta(source_text, home_iso3=home_iso3, away_iso3=away_iso3)
        if not isinstance(payload, Mapping):
            return inferred

        normalized = dict(inferred)
        for key in _COMPETITION_META_KEYS:
            if key in payload:
                normalized[key] = payload[key]

        normalized["stage"] = _normalize_stage(normalized.get("stage"))
        if normalized["stage"] == "group":
            normalized["knockout"] = False
        else:
            normalized["knockout"] = bool(normalized.get("knockout")) or normalized["stage"] in _KNOCKOUT_STAGES
        normalized["neutral_venue"] = bool(normalized.get("neutral_venue"))
        normalized["host_country_iso3"] = (
            infer_2026_world_cup_host_country(source_text, home_iso3=home_iso3, away_iso3=away_iso3)
            or _clean_iso3(normalized.get("host_country_iso3"))
        )
        return normalized

    def _infer_competition_meta(
        self,
        text: str,
        *,
        home_iso3: str | None = None,
        away_iso3: str | None = None,
    ) -> dict[str, Any]:
        stage = _infer_stage(text)
        knockout = stage in _KNOCKOUT_STAGES or bool(re.search(r"淘汰赛|knockout", text or "", re.I))
        if stage == "group":
            knockout = False
        return {
            "tournament": _infer_tournament(text),
            "stage": stage,
            "knockout": knockout,
            "neutral_venue": bool(re.search(r"中立场|中立球场|neutral venue|neutral site", text or "", re.I)),
            "host_country_iso3": infer_2026_world_cup_host_country(text, home_iso3=home_iso3, away_iso3=away_iso3),
        }

    def _extract_injury_reports(
        self,
        text: str,
        home_iso3: str | None,
        away_iso3: str | None,
    ) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        chinese_pattern = re.compile(
            r"(?:^|[，,。；;\s])(?P<player>[\u4e00-\u9fffA-Za-z·.'-]{1,24}?)(?P<status>因伤缺席|受伤|伤缺|停赛)"
        )
        for match in chinese_pattern.finditer(text):
            player = match.group("player").strip()
            status_text = match.group("status")
            status = "suspended" if "停赛" in status_text else "injured"
            evidence = f"{player}{status_text}"
            key = (player, status)
            if key in seen:
                continue
            seen.add(key)
            reports.append(
                {
                    "player": player,
                    "team_iso3": _infer_player_team(player, home_iso3, away_iso3),
                    "status": status,
                    "evidence_span": evidence,
                }
            )

        english_pattern = re.compile(
            r"(?:^|[,\.;\s])(?P<player>[A-Z][A-Za-z'.-]*(?:\s+[A-Z][A-Za-z'.-]*){0,3})\s+"
            r"(?P<status>injured|out injured|out with injury|suspended|doubtful)",
            re.I,
        )
        for match in english_pattern.finditer(text):
            player = match.group("player").strip()
            raw_status = match.group("status").lower()
            if raw_status == "doubtful":
                status = "doubtful"
            elif raw_status == "suspended":
                status = "suspended"
            else:
                status = "injured"
            evidence = f"{player} {match.group('status')}"
            key = (player.casefold(), status)
            if key in seen:
                continue
            seen.add(key)
            reports.append(
                {
                    "player": player,
                    "team_iso3": _infer_player_team(player, home_iso3, away_iso3),
                    "status": status,
                    "evidence_span": evidence,
                }
            )

        return reports


MatchDataExtractor = FootballDataExtractor


def _ledger_budget(llm_ledger: LLMCallLedger) -> Any:
    budget = getattr(llm_ledger, "budget", None)
    if budget is not None:
        return budget
    return getattr(llm_ledger, "_budget", None)


def _env_flag_enabled(name: str) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return True
    return raw_value.strip().lower() not in {"0", "false", "no", "off", "n"}


def _build_raw_alias_index(normalizer: TeamNameNormalizer) -> dict[str, str]:
    index: dict[str, str] = {}
    for iso3, entry in normalizer.alias_map.items():
        if not isinstance(entry, Mapping):
            continue
        values: list[Any] = [iso3, entry.get("canonical_en"), entry.get("canonical_zh")]
        for key, raw_values in entry.items():
            if key in {"canonical_en", "canonical_zh"}:
                continue
            values.extend(_iter_values(raw_values))
        for value in values:
            if value is None:
                continue
            alias = str(value).strip()
            if not alias:
                continue
            if len(alias) <= 2 and not _contains_cjk(alias):
                continue
            index.setdefault(alias, iso3)
            index.setdefault(alias.casefold(), iso3)

    index.update(
        {
            "美国": "USA",
            "英格兰": "ENG",
            "德国": "GER",
            "韩国": "KOR",
            "朝鲜": "PRK",
        }
    )
    return index


def _iter_values(values: object) -> Iterable[object]:
    if values is None:
        return []
    if isinstance(values, list):
        return values
    return [values]


def _find_alias_position(text: str, alias: str) -> int:
    if _contains_cjk(alias):
        return text.find(alias)
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", re.I)
    match = pattern.search(text)
    return match.start() if match else -1


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _clean_iso3(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text if re.fullmatch(r"[A-Z]{3}", text) else None


def _trim_team_fragment(value: str) -> str:
    text = (value or "").strip(" \t\r\n=,，。;；:：()[]【】")
    text = re.sub(r"^#{1,6}\s*", "", text).strip()
    text = re.sub(r"\.(?:md|markdown|txt|pdf|docx?|rtf|html?)\s*$", "", text, flags=re.I).strip()
    text = re.split(
        r"\s*(?:赛前信息报告|赛前报告|赛前情报|信息报告|分析报告|预测报告|赛事报告|前瞻报告|报告|前瞻|"
        r"世界杯|欧洲杯|美洲杯|亚洲杯|非洲杯|半决赛|四分之一决赛|八分之一决赛|决赛|小组赛)",
        text,
        maxsplit=1,
    )[0]
    text = re.split(
        r"\s+(?:match preview|preview|analysis|report|World Cup|Euro|Copa America|Asian Cup|"
        r"semi[- ]?final|quarter[- ]?final|round of 16|final|group stage)\b",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    return text.strip(" \t\r\n=,，。;；:：()[]【】")


def _normalize_stage(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _STAGE_ALIASES.get(text) or _STAGE_ALIASES.get(text.lower().replace(" ", "_"))


def _infer_stage(text: str) -> str | None:
    if not text:
        return None
    if re.search(r"(?:赛事阶段|比赛阶段|match\s*\d+|group\s+[a-lk])[^。\n\r]{0,80}(?:小组赛|group stage|\bgroup\b)", text, re.I):
        return "group"
    checks = [
        (r"小组赛|group stage|\bgroup\b", "group"),
        (r"半决赛|semi[- ]?final|semifinal", "semi_final"),
        (r"四分之一决赛|quarter[- ]?final|quarterfinal|八强", "quarter_final"),
        (r"八分之一决赛|round of 16|last 16|16强|十六强", "round_of_16"),
        (r"三四名|季军赛|third[- ]?place", "third_place"),
        (r"决赛|final", "final"),
    ]
    for pattern, stage in checks:
        if re.search(pattern, text, re.I):
            return stage
    return None


def _infer_tournament(text: str) -> str | None:
    if not text:
        return None
    tournament_patterns = [
        (r"世界杯|World Cup|FIFA World Cup", "世界杯"),
        (r"欧洲杯|Euro|UEFA European Championship", "欧洲杯"),
        (r"美洲杯|Copa America", "美洲杯"),
        (r"亚洲杯|Asian Cup", "亚洲杯"),
        (r"非洲杯|Africa Cup of Nations|AFCON", "非洲杯"),
    ]
    for pattern, tournament in tournament_patterns:
        if re.search(pattern, text, re.I):
            return tournament
    return None


def infer_2026_world_cup_host_country(
    text: str | None,
    *,
    home_iso3: str | None = None,
    away_iso3: str | None = None,
) -> str | None:
    """Infer the local 2026 World Cup host country from venue/city hints."""

    lowered = str(text or "").casefold()
    if not lowered:
        return None
    if not any(token in lowered for token in ("2026", "world cup", "世界杯", "fifa")):
        return None

    matches: list[tuple[int, int, str]] = []
    for iso3, hints in _WORLD_CUP_2026_HOST_HINTS.items():
        for hint in hints:
            position = lowered.find(hint.casefold())
            if position >= 0:
                matches.append((position, -len(hint), iso3))
    if not matches:
        participant_hosts = {
            iso3
            for iso3 in (_clean_iso3(home_iso3), _clean_iso3(away_iso3))
            if iso3 in _WORLD_CUP_2026_HOST_HINTS
        }
        return next(iter(participant_hosts)) if len(participant_hosts) == 1 else None
    return sorted(matches)[0][2]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dict_list(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _extract_key_narratives(text: str) -> list[str]:
    narratives: list[str] = []
    for part in re.split(r"[。；;,\n]", text or ""):
        candidate = part.strip()
        if not candidate:
            continue
        if re.search(r"伤|停赛|状态|火热|关键|重要|半决赛|决赛|世界杯|injur|suspend|hot|form|semi|final", candidate, re.I):
            narratives.append(candidate)
        if len(narratives) >= 6:
            break
    return narratives


def _extract_tactical_notes(
    text: str,
    home_iso3: str | None,
    away_iso3: str | None,
) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    patterns = [
        (r"高位逼抢|high press(?:ing)?", "high_press"),
        (r"防守反击|counter[- ]?attack", "counter_attack"),
        (r"控球|possession", "possession"),
        (r"定位球|set[- ]?piece", "set_piece"),
    ]
    for pattern, style in patterns:
        match = re.search(pattern, text or "", re.I)
        if not match:
            continue
        notes.append(
            {
                "team_iso3": _nearest_team_iso3(text, match.start(), home_iso3, away_iso3),
                "style": style,
                "note": match.group(0),
            }
        )
    return notes


def _nearest_team_iso3(
    text: str,
    position: int,
    home_iso3: str | None,
    away_iso3: str | None,
) -> str | None:
    if home_iso3 and away_iso3:
        return home_iso3 if position <= len(text) / 2 else away_iso3
    return home_iso3 or away_iso3


def _infer_player_team(
    player: str,
    home_iso3: str | None,
    away_iso3: str | None,
) -> str | None:
    key = re.sub(r"\s+", " ", player.strip().casefold())
    hinted = _COMMON_PLAYER_TEAM_HINTS.get(key) or _COMMON_PLAYER_TEAM_HINTS.get(player.strip())
    if hinted in {home_iso3, away_iso3}:
        return hinted
    return hinted or home_iso3
