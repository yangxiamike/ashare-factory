from __future__ import annotations


def build_forward_return_sql(horizons: tuple[int, ...]) -> str:
    expressions: list[str] = []
    for horizon in horizons:
        end_offset = horizon + 1
        expressions.append(
            f"""
            CASE
                WHEN LEAD(is_tradable, 1) OVER w
                     AND LEAD(is_tradable, {end_offset}) OVER w
                THEN LEAD(adj_close, {end_offset}) OVER w / LEAD(adj_close, 1) OVER w - 1
                ELSE NULL
            END AS fwd_{horizon}d
            """.strip()
        )
    return ",\n        ".join(expressions)
