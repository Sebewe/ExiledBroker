"""Tunable opportunity scores shared by the card turn-in and cross-market tools.

Each factor is turned into a percentile rank among the candidates (best = 1, worst =
1/n), so chaos amounts, percentages and counts combine on one scale and one outlier
can't dominate. The score is the weighted mean of those ranks, from 0 to 1.
"""

import polars as pl

# factor name -> (column, higher is better)
Factors = dict[str, tuple[str, bool]]


def rank_score(df: pl.DataFrame, factors: Factors, weights: dict[str, float]) -> pl.DataFrame:
    """Add `<factor>_rank` columns and a `score`, sorted best first.

    Negative weights count as 0; if every weight is 0 the score is null."""
    if df.is_empty():
        return df.with_columns(score=pl.lit(None, pl.Float64))
    n = df.height
    ranks = [
        # Rank 1 = best: the highest value when higher is better, else the lowest.
        ((n + 1 - pl.col(col).rank("average", descending=higher_better)) / n)
        .fill_null(0)
        .alias(f"{name}_rank")
        for name, (col, higher_better) in factors.items()
    ]
    out = df.with_columns(ranks)
    w = {name: max(weights.get(name, 0.0), 0.0) for name in factors}
    total = sum(w.values())
    if total == 0:
        return out.with_columns(score=pl.lit(None, pl.Float64))
    score = sum(pl.col(f"{name}_rank") * w[name] for name in factors) / total
    return out.with_columns(score=score).sort("score", descending=True)
