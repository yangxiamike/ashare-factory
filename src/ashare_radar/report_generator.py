from __future__ import annotations

from pathlib import Path

from ashare_radar.models import (
    IndustryStrengthRankingResult,
    MarketTemperatureResult,
    StyleFactorRankingResult,
)


def generate_market_radar_report(
    trade_date: str,
    market_temperature: MarketTemperatureResult,
    style_ranking: StyleFactorRankingResult,
    industry_ranking: IndustryStrengthRankingResult,
    news_digest: dict | None = None,
) -> str:
    lines: list[str] = [
        f"# A股 Market Radar - {trade_date}",
        "",
        "## 市场温度",
        f"- 状态：`{market_temperature.state}`",
        f"- 分数：`{market_temperature.score}`",
        f"- 平均涨跌幅：`{market_temperature.metrics['average_return']:.4f}%`",
        f"- 中位数涨跌幅：`{market_temperature.metrics['median_return']:.4f}%`",
        f"- 成交额 / 近5日均值：`{_format_optional(market_temperature.metrics['amount_ratio_5d'])}`",
        f"- 上涨 / 下跌家数：`{market_temperature.metrics['up_count']}` / `{market_temperature.metrics['down_count']}`",
        f"- 涨停 / 跌停家数：`{market_temperature.metrics['up_limit_count']}` / `{market_temperature.metrics['down_limit_count']}`",
        "",
        "## 风格收益排名",
    ]
    for row in style_ranking.rankings:
        lines.append(
            (
                f"- `{row.factor_name}:{row.bucket_name}` "
                f"mean=`{row.mean_return:.4f}%` "
                f"median=`{row.median_return:.4f}%` "
                f"count=`{row.stock_count}`"
            )
        )

    lines.extend(["", "## 行业强弱"])
    lines.extend(_section_lines("强势 Top 5", industry_ranking.top))
    lines.extend(_section_lines("弱势 Bottom 5", industry_ranking.bottom))
    lines.extend(_section_lines("放量 Top 5", industry_ranking.volume_leaders))
    lines.extend(
        [
            "",
            "## 行业扩散度",
            f"- 行业数量：`{industry_ranking.breadth['industry_count']}`",
            f"- 上涨行业占比：`{industry_ranking.breadth['positive_industry_ratio']:.4f}`",
            f"- 下跌行业占比：`{industry_ranking.breadth['negative_industry_ratio']:.4f}`",
            f"- 行业收益中位数：`{industry_ranking.breadth['median_industry_return']:.4f}%`",
        ]
    )
    if news_digest is not None:
        lines.extend(["", "## 新闻脉络"])
        lines.append(
            (
                f"- 原始 / 清洗 / 去重 / 相关：`{news_digest['total_raw']}` / "
                f"`{news_digest['total_clean']}` / `{news_digest['total_deduped']}` / "
                f"`{news_digest['total_relevant']}`"
            )
        )
        for item in news_digest.get("items", []):
            lines.append(
                f"- `[{item['category']}]` score=`{item['score']:.2f}` {item['title']} ({item['source']})"
            )
    return "\n".join(lines)


def render_daily_report(
    trade_date: str,
    market_temperature: MarketTemperatureResult,
    style_ranking: StyleFactorRankingResult,
    industry_ranking: IndustryStrengthRankingResult,
    news_digest: dict | None = None,
) -> str:
    return generate_market_radar_report(
        trade_date=trade_date,
        market_temperature=market_temperature,
        style_ranking=style_ranking,
        industry_ranking=industry_ranking,
        news_digest=news_digest,
    )


def write_daily_report(
    trade_date: str,
    report_text: str,
    report_path: str | Path | None = None,
) -> Path:
    target = Path(report_path or Path("reports") / "ashare_radar" / f"{trade_date}.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report_text, encoding="utf-8")
    return target


def _section_lines(title: str, rows: list) -> list[str]:
    lines = [f"### {title}"]
    for row in rows:
        lines.append(
            (
                f"- `{row.industry_name}` "
                f"mean=`{row.mean_return:.4f}%` "
                f"median=`{row.median_return:.4f}%` "
                f"amount_ratio_5d=`{_format_optional(row.amount_ratio_5d)}` "
                f"count=`{row.stock_count}`"
            )
        )
    return lines + [""]


def _format_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"
