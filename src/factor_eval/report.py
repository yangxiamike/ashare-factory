"""Standard report plots for factor evaluation results."""

from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

from factor_eval.runner import EvalResult
from factor_utils import rebalance_cumulative_returns

COLORS = {
    "blue": "#4E79A7",
    "teal": "#2A9D8F",
    "green": "#59A14F",
    "orange": "#F28E2B",
    "red": "#E15759",
    "purple": "#B07AA1",
    "gray": "#6B7280",
}
QUANTILE_5 = [COLORS["blue"], COLORS["teal"], COLORS["gray"], COLORS["orange"], COLORS["green"]]

plt.rcParams.update(
    {
        "figure.dpi": 120,
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "figure.titlesize": 13,
        "legend.fontsize": 9,
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "axes.edgecolor": "#D0D5DD",
        "grid.color": "#D9DEE7",
        "grid.linewidth": 0.8,
    }
)


def plot_distribution(result: EvalResult) -> plt.Figure:
    fig, axes = plt.subplots(1, 4, figsize=(18, 4))
    cols = ["factor_raw", "factor_zscore", "factor_size_neutral", result.factor_col]
    labels = ["Raw", "Z-score", "Size-Neutral", "Industry+Size-Neutral"]
    plot_colors = [COLORS["blue"], COLORS["orange"], COLORS["green"], COLORS["purple"]]
    sample = result.df[result.df["universe"]]

    for ax, col, label, color in zip(axes, cols, labels, plot_colors):
        vals = sample[col].dropna()
        ax.hist(vals, bins=40, color=color, alpha=0.82, edgecolor="white", linewidth=0.5)
        ax.axvline(vals.mean(), color=COLORS["red"], linestyle="--", linewidth=1.2, label="Mean")
        ax.axvline(vals.median(), color="#111827", linestyle="-", linewidth=0.9, label="Median")
        ax.set_title(f"{label}\nmean={vals.mean():.3f}  std={vals.std():.3f}")
        ax.legend(frameon=False, fontsize=8)

    fig.suptitle(
        f"Factor Distribution — {result.factor_name} ({result.universe})",
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    return fig


def plot_ic(result: EvalResult) -> plt.Figure:
    ic_df = result.ic_df.copy()
    ic_df["cum_ic"] = ic_df["rank_ic"].cumsum()
    ic_df["rolling_20"] = ic_df["rank_ic"].rolling(20, min_periods=5).mean()
    fig, axes = plt.subplots(2, 2, figsize=(16, 8))

    ax = axes[0, 0]
    ax.bar(ic_df["trade_date"], ic_df["rank_ic"], color=COLORS["blue"], alpha=0.55, width=1.5)
    ax.plot(ic_df["trade_date"], ic_df["rolling_20"], color=COLORS["orange"], linewidth=2, label="20d rolling")
    ax.axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    ax.set_title("Rank IC - Daily")
    ax.legend()

    ax = axes[0, 1]
    ax.plot(ic_df["trade_date"], ic_df["cum_ic"], color=COLORS["green"], linewidth=1.8)
    ax.fill_between(ic_df["trade_date"], 0, ic_df["cum_ic"], color=COLORS["green"], alpha=0.16)
    ax.axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    ax.set_title("Cumulative IC")

    ax = axes[1, 0]
    ax.hist(ic_df["rank_ic"], bins=25, color=COLORS["blue"], alpha=0.78, edgecolor="white")
    ax.axvline(0, color=COLORS["gray"], linestyle="--", linewidth=1)
    ax.axvline(
        ic_df["rank_ic"].mean(),
        color=COLORS["orange"],
        linewidth=2,
        label=f"mean={ic_df['rank_ic'].mean():.4f}",
    )
    ax.set_title("IC Distribution")
    ax.legend()

    ax = axes[1, 1]
    selected = result.ic_decay_df[result.ic_decay_df["horizon"].isin([1, 5, 20])]
    x = np.arange(len(selected))
    bars = ax.bar(x, selected["mean_ic"], color=[COLORS["blue"], COLORS["orange"], COLORS["green"]], width=0.5)
    ax.bar_label(bars, fmt="%.4f")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h}d" for h in selected["horizon"]])
    ax.axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    ax.set_title("Mean IC by Horizon")

    fig.suptitle(f"IC Analysis — {result.factor_name} ({result.universe})", fontweight="bold", y=1.01)
    fig.tight_layout()
    return fig


def plot_ic_decay(result: EvalResult) -> plt.Figure:
    decay = result.ic_decay_df
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(decay["horizon"], decay["mean_ic"], color=COLORS["blue"], linewidth=2, marker="o")
    ax.fill_between(
        decay["horizon"],
        decay["mean_ic"] - decay["std_ic"],
        decay["mean_ic"] + decay["std_ic"],
        color=COLORS["blue"],
        alpha=0.15,
    )
    ax.axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    half_life = f"{result.half_life}d" if result.half_life else ">20d"
    ax.set_title(f"IC Decay by Horizon\nHalf-life: {half_life}")
    ax.set_xlabel("Forward Horizon (days)")
    ax.set_ylabel("Mean Rank IC")
    fig.tight_layout()
    return fig


def plot_quantile_returns(result: EvalResult) -> plt.Figure:
    q_summary = result.quantile_summary.set_index("quantile")
    q_pivot = result.quantile_returns_daily.pivot(
        index="trade_date", columns="quantile", values="avg_return"
    ).sort_index()
    q_cum = rebalance_cumulative_returns(q_pivot, step=5)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    ax = axes[0]
    bars = ax.bar(
        q_summary.index.astype(str),
        q_summary["mean_return"],
        color=QUANTILE_5,
        edgecolor="white",
        linewidth=0.8,
    )
    for bar, val in zip(bars, q_summary["mean_return"]):
        offset = 0.0002 if val >= 0 else -0.0002
        va = "bottom" if val >= 0 else "top"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            val + offset,
            f"{val:.4%}",
            ha="center",
            va=va,
            fontsize=9,
        )
    ax.axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    ax.set_title("Mean fwd_5d Return by Quantile")
    ax.set_xlabel("Quantile (1=Low, 5=High)")

    ax = axes[1]
    for q in range(1, 6):
        if q in q_cum.columns:
            ax.plot(
                q_cum.index,
                q_cum[q],
                color=QUANTILE_5[q - 1],
                linewidth=2.0 if q in (1, 5) else 1.6,
                alpha=0.96,
                label=f"Q{q}",
            )
    ax.axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    ax.set_title("Cumulative Return by Quantile")
    ax.legend(ncol=5, fontsize=8, frameon=True)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    fig.suptitle(
        f"Quantile Returns — {result.factor_name} ({result.universe})",
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    return fig


def plot_long_short(result: EvalResult) -> plt.Figure:
    ls = result.long_short_df
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    ax = axes[0]
    colors = [COLORS["green"] if value >= 0 else COLORS["red"] for value in ls["spread"]]
    ax.bar(ls["trade_date"], ls["spread"], color=colors, alpha=0.62, width=1.5)
    ax.axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    ax.set_title(f"Daily Spread\nmean={result.long_short_summary['mean_spread']:.4%}")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    ax = axes[1]
    ax.plot(ls["trade_date"], ls["cum_spread"], color=COLORS["green"], linewidth=2)
    ax.fill_between(ls["trade_date"], 0, ls["cum_spread"], color=COLORS["green"], alpha=0.16)
    ax.axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    ax.set_title(f"Cumulative Spread\nfinal={result.long_short_summary['cum_return']:.4%}")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    fig.suptitle(
        f"Long-Short (Q5-Q1) — {result.factor_name} ({result.universe})",
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    return fig


def plot_yearly_perf(result: EvalResult) -> plt.Figure:
    yearly = result.yearly_perf
    fig, axes = plt.subplots(1, 3, figsize=(16, 4))

    axes[0].bar(yearly["year"].astype(str), yearly["mean_ic"], color=COLORS["blue"], width=0.55)
    axes[0].axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    axes[0].set_title("Mean IC by Year")

    axes[1].bar(yearly["year"].astype(str), yearly["cum_return_q5"], color=COLORS["green"], width=0.55)
    axes[1].axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    axes[1].set_title("Q5 Cumulative Return by Year")
    axes[1].yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    axes[2].plot(
        yearly["year"].astype(str), yearly["win_rate"], color=COLORS["orange"], marker="o", linewidth=2
    )
    axes[2].axhline(0.5, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    axes[2].set_title("IC Win Rate by Year")
    axes[2].yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    fig.suptitle(
        f"Yearly Performance — {result.factor_name} ({result.universe})",
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    return fig


def plot_monthly_ic_heatmap(result: EvalResult) -> plt.Figure:
    """Monthly mean IC heatmap — reveals seasonal IC patterns."""
    monthly_ic = result.monthly_ic
    fig, ax = plt.subplots(figsize=(12, max(3, len(monthly_ic) * 0.6)))
    sns.heatmap(
        monthly_ic,
        annot=True,
        fmt=".3f",
        cmap="RdBu_r",
        center=0,
        linewidths=0.5,
        ax=ax,
        cbar_kws={"label": "Mean Rank IC"},
        xticklabels=[f"{m}月" for m in monthly_ic.columns],
    )
    ax.set_title(
        f"Monthly IC Heatmap — {result.factor_name} ({result.universe})",
        fontweight="bold",
    )
    ax.set_xlabel("Month")
    ax.set_ylabel("Year")
    fig.tight_layout()
    return fig


def plot_regression_test(result: EvalResult) -> plt.Figure:
    """Plot regression-based factor return and t-value diagnostics.

    Uses factor_utils.compute_factor_return_t internally to get per-period
    factor return and t-value, then plots them alongside a t-value histogram.
    """
    from factor_utils import compute_factor_return_t

    research_sample = result.df[result.df["universe"]]
    reg_df, _ = compute_factor_return_t(
        research_sample, result.factor_col, "fwd_5d"
    )

    fig, axes = plt.subplots(1, 3, figsize=(18, 4))

    ax = axes[0]
    ax.bar(
        reg_df["trade_date"],
        reg_df["factor_return"],
        color=[COLORS["green"] if v >= 0 else COLORS["red"] for v in reg_df["factor_return"]],
        alpha=0.6,
        width=1.5,
    )
    ax.axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    ax.set_title(f"Factor Return (OLS beta)\nmean={reg_df['factor_return'].mean():.5f}")

    ax = axes[1]
    ax.bar(reg_df["trade_date"], reg_df["t_value"], color=COLORS["blue"], alpha=0.55, width=1.5)
    ax.axhline(2, color=COLORS["orange"], linestyle="--", linewidth=1, label="|t|=2")
    ax.axhline(-2, color=COLORS["orange"], linestyle="--", linewidth=1)
    ax.axhline(0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    mean_abs_t = reg_df["t_value"].abs().mean()
    pct_gt_2 = (reg_df["t_value"].abs() > 2).mean()
    ax.set_title(f"t-Value per Period\nmean|t|={mean_abs_t:.2f}  |t|>2={pct_gt_2:.1%}")
    ax.legend(fontsize=8)

    ax = axes[2]
    ax.hist(reg_df["t_value"], bins=25, color=COLORS["blue"], alpha=0.78, edgecolor="white")
    ax.axvline(0, color=COLORS["gray"], linestyle="--", linewidth=1)
    ax.axvline(
        reg_df["t_value"].mean(),
        color=COLORS["orange"],
        linewidth=2,
        label=f"mean t={reg_df['t_value'].mean():.2f}",
    )
    ax.set_title("t-Value Distribution")
    ax.legend()

    fig.suptitle(
        f"Regression-Based Factor Test — {result.factor_name} ({result.universe})",
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    return fig


def plot_backtest(result: EvalResult) -> plt.Figure:
    """Plot Q5 long-only backtest: equity curve + drawdown."""
    bt = result.backtest_df
    if bt.empty:
        fig, ax = plt.subplots(figsize=(8, 2))
        ax.text(0.5, 0.5, "No backtest data", ha="center", va="center")
        return fig

    fig, axes = plt.subplots(1, 3, figsize=(18, 4.5))

    ax = axes[0]
    ax.plot(bt["trade_date"], bt["gross_equity"], color=COLORS["blue"], linewidth=1.8, label="Gross")
    ax.plot(bt["trade_date"], bt["net_equity"], color=COLORS["green"], linewidth=2.0, label="Net")
    ax.axhline(1.0, color=COLORS["gray"], linestyle="--", linewidth=0.8)
    ax.set_title("Q5 Backtest Equity")
    ax.legend(frameon=True)

    ax = axes[1]
    ax.fill_between(bt["trade_date"], bt["drawdown"], 0, color=COLORS["red"], alpha=0.18)
    ax.plot(bt["trade_date"], bt["drawdown"], color=COLORS["red"], linewidth=1.6)
    ax.set_title(f"Drawdown (max={bt['drawdown'].min():.2%})")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    ax = axes[2]
    ax.bar(bt["trade_date"], bt["turnover"], color=COLORS["purple"], alpha=0.6, width=2)
    ax.axhline(bt["turnover"].mean(), color=COLORS["orange"], linestyle="--",
               label=f"mean={bt['turnover'].mean():.1%}")
    ax.set_title("Turnover per Rebalance")
    ax.legend(fontsize=8)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))

    fig.suptitle(
        f"Research Backtest (Q5 Long-Only) — {result.factor_name} ({result.universe})",
        fontweight="bold",
        y=1.02,
    )
    fig.tight_layout()
    return fig


def plot_scorecard(result: EvalResult) -> pd.io.formats.style.Styler:
    def row_style(row: pd.Series) -> list[str]:
        base = "color: #111827; border-color: #E5E7EB;"
        if row["Judgement"] == "Pass":
            bg = "background-color: #D1FAE5;"
        elif row["Judgement"] == "Weak":
            bg = "background-color: #FEE2E2;"
        elif row["Judgement"] == "Review":
            bg = "background-color: #FEF3C7;"
        else:
            bg = "background-color: #F8FAFC;"
        return [bg + base for _ in row]

    return (
        result.scorecard.style.apply(row_style, axis=1)
        .set_table_styles(
            [
                {
                    "selector": "th",
                    "props": [
                        ("background-color", "#111827"),
                        ("color", "#F9FAFB"),
                        ("border-color", "#374151"),
                    ],
                },
                {
                    "selector": "td",
                    "props": [("font-weight", "500"), ("border-color", "#E5E7EB")],
                },
            ]
        )
        .hide(axis="index")
    )
