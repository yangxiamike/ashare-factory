from __future__ import annotations

from pathlib import Path

import yaml

from ashare_radar.news_intake import build_news_digest


def test_build_news_digest_runs_minimal_pipeline(tmp_path: Path) -> None:
    config_path = tmp_path / "news.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "relevance_keywords": ["降准", "科技", "半导体"],
                "keyword_weights": {"降准": 2.0, "科技": 1.5, "半导体": 1.8},
                "category_rules": {"macro": ["降准"], "technology": ["科技", "半导体"]},
                "category_weights": {"macro": 1.5, "technology": 1.2, "other": 1.0},
                "source_weights": {"mock": 1.0, "manual": 1.1},
                "mock_news": [
                    {
                        "title": " 央行降准预期升温 ",
                        "content": "科技成长方向活跃",
                        "source": "mock",
                        "tags": ["宏观"],
                    },
                    {
                        "title": "央行降准预期升温",
                        "content": "重复标题，应该被去重",
                        "source": "mock",
                    },
                    {
                        "title": "半导体景气回升",
                        "content": "算力链订单延续",
                        "source": "mock",
                    },
                    {
                        "title": "社区团购价格战复燃",
                        "content": "不相关，应该被过滤",
                        "source": "mock",
                    },
                ],
                "manual_news": [
                    {
                        "title": "手工补充：科技板块继续走强",
                        "content": "人工补录消息",
                        "source": "manual",
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    digest = build_news_digest("2026-06-08", config_path=config_path)

    assert digest["trade_date"] == "2026-06-08"
    assert digest["total_raw"] == 5
    assert digest["total_clean"] == 5
    assert digest["total_deduped"] == 4
    assert digest["total_relevant"] == 3
    assert [item["title"] for item in digest["items"]] == [
        "央行降准预期升温",
        "半导体景气回升",
        "手工补充：科技板块继续走强",
    ]
    assert digest["items"][0]["category"] == "macro"
    assert digest["items"][0]["score"] > digest["items"][1]["score"]
