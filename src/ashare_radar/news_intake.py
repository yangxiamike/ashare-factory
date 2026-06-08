from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path("configs") / "ashare_radar" / "news.yaml"


@dataclass(frozen=True)
class NewsRecord:
    trade_date: str
    title: str
    content: str
    source: str
    tags: tuple[str, ...] = ()


def _coerce_trade_date(value: str | date) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(value).isoformat()


def _normalize_space(text: str) -> str:
    return " ".join(text.replace("\n", " ").replace("\t", " ").split())


def _clean_text(text: str) -> str:
    return _normalize_space(text).strip(" -:：,，。；;")


def _normalize_source(value: str | None) -> str:
    return _clean_text(value or "unknown").lower()


def _ensure_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def load_news_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"news config must be a mapping: {path}")
    return payload


def clean_news_items(items: list[dict[str, Any]], trade_date: str | date) -> list[dict[str, Any]]:
    normalized_trade_date = _coerce_trade_date(trade_date)
    cleaned: list[dict[str, Any]] = []
    for item in items:
        title = _clean_text(str(item.get("title", "")))
        content = _clean_text(str(item.get("content", item.get("summary", ""))))
        if not title:
            continue
        record = NewsRecord(
            trade_date=str(item.get("trade_date") or normalized_trade_date),
            title=title,
            content=content,
            source=_normalize_source(item.get("source")),
            tags=tuple(_clean_text(str(tag)).lower() for tag in _ensure_sequence(item.get("tags")) if str(tag).strip()),
        )
        cleaned.append(
            {
                "trade_date": record.trade_date,
                "title": record.title,
                "content": record.content,
                "source": record.source,
                "tags": list(record.tags),
            }
        )
    return cleaned


def dedup_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = (_normalize_space(item["title"]).lower(), _normalize_source(item.get("source")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def filter_relevant_news(items: list[dict[str, Any]], keywords: list[str]) -> list[dict[str, Any]]:
    keyword_list = [_clean_text(keyword).lower() for keyword in keywords if str(keyword).strip()]
    if not keyword_list:
        return items

    relevant: list[dict[str, Any]] = []
    for item in items:
        haystack = " ".join([item["title"], item.get("content", ""), " ".join(item.get("tags", []))]).lower()
        matched = [keyword for keyword in keyword_list if keyword in haystack]
        if not matched:
            continue
        relevant.append({**item, "matched_keywords": matched})
    return relevant


def structure_news_items(
    items: list[dict[str, Any]],
    category_rules: dict[str, list[str]],
    source_weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    normalized_rules = {
        category: [_clean_text(keyword).lower() for keyword in keywords if str(keyword).strip()]
        for category, keywords in category_rules.items()
    }
    normalized_source_weights = {str(key).lower(): float(value) for key, value in (source_weights or {}).items()}
    structured: list[dict[str, Any]] = []
    for item in items:
        haystack = " ".join([item["title"], item.get("content", ""), " ".join(item.get("tags", []))]).lower()
        category = "other"
        category_hits: list[str] = []
        for candidate, keywords in normalized_rules.items():
            matched = [keyword for keyword in keywords if keyword in haystack]
            if matched:
                category = candidate
                category_hits = matched
                break
        structured.append(
            {
                **item,
                "category": category,
                "category_hits": category_hits,
                "source_weight": normalized_source_weights.get(item["source"], 1.0),
            }
        )
    return structured


def rank_news_items(
    items: list[dict[str, Any]],
    keyword_weights: dict[str, float] | None = None,
    category_weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    normalized_keyword_weights = {str(key).lower(): float(value) for key, value in (keyword_weights or {}).items()}
    normalized_category_weights = {str(key).lower(): float(value) for key, value in (category_weights or {}).items()}

    ranked: list[dict[str, Any]] = []
    for item in items:
        keyword_score = sum(normalized_keyword_weights.get(keyword, 1.0) for keyword in item.get("matched_keywords", []))
        category_score = normalized_category_weights.get(str(item.get("category", "other")).lower(), 1.0)
        score = round(keyword_score * category_score * float(item.get("source_weight", 1.0)), 4)
        ranked.append({**item, "score": score})

    return sorted(
        ranked,
        key=lambda item: (
            -float(item["score"]),
            item["title"],
        ),
    )


def build_news_digest(
    trade_date: str | date,
    *,
    config_path: str | Path | None = None,
    manual_news: list[dict[str, Any]] | None = None,
    mock_news: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config = load_news_config(config_path)
    normalized_trade_date = _coerce_trade_date(trade_date)
    raw_items = [
        *_ensure_sequence(config.get("mock_news")),
        *_ensure_sequence(config.get("manual_news")),
        *_ensure_sequence(mock_news),
        *_ensure_sequence(manual_news),
    ]
    cleaned = clean_news_items(raw_items, normalized_trade_date)
    deduped = dedup_news_items(cleaned)
    filtered = filter_relevant_news(deduped, _ensure_sequence(config.get("relevance_keywords")))
    structured = structure_news_items(
        filtered,
        config.get("category_rules", {}),
        source_weights=config.get("source_weights", {}),
    )
    ranked = rank_news_items(
        structured,
        keyword_weights=config.get("keyword_weights", {}),
        category_weights=config.get("category_weights", {}),
    )
    return {
        "trade_date": normalized_trade_date,
        "total_raw": len(raw_items),
        "total_clean": len(cleaned),
        "total_deduped": len(deduped),
        "total_relevant": len(ranked),
        "items": ranked,
    }
