"""Price based recognition of common chart patterns.

This module deliberately reports geometric candidates only. Pattern matches are
not trading signals; volume, trend context and confirmation should be assessed
separately.
"""
from typing import Dict, Optional

import numpy as np
import pandas as pd


def _turning_points(values: np.ndarray, order: int, kind: str):
    points = []
    for i in range(order, len(values) - order):
        window = values[i - order:i + order + 1]
        if kind == "low" and values[i] == np.nanmin(window):
            points.append(i)
        elif kind == "high" and values[i] == np.nanmax(window):
            points.append(i)
    # Collapse flat extrema to their middle observation.
    deduped = []
    for point in points:
        if deduped and point - deduped[-1] <= order:
            prev = deduped[-1]
            if (kind == "low" and values[point] < values[prev]) or (kind == "high" and values[point] > values[prev]):
                deduped[-1] = point
        else:
            deduped.append(point)
    return deduped


def detect_pattern(
    hist: pd.DataFrame,
    pattern: str,
    price_col: str = "收盘",
    order: int = 3,
    tolerance_pct: float = 4.0,
    min_separation: int = 5,
    max_lookback: int = 100,
) -> Dict:
    """Detect a recent double bottom/top, head-and-shoulders, triangle or rectangle.

    Returns ``{"matched": bool, "pattern": ..., "reason": ..., "metrics": {...}}``.
    A pattern is considered recent when its final pivot is within ``max_lookback``
    bars of the latest bar. ``price_col`` defaults to the project's Chinese close
    column; standard ``close`` is also accepted as a convenience.
    """
    supported = {"double_bottom", "double_top", "head_shoulders", "triangle", "rectangle"}
    if pattern not in supported:
        raise ValueError("unsupported pattern: %s" % pattern)
    col = price_col if price_col in hist.columns else ("close" if "close" in hist.columns else price_col)
    if col not in hist.columns or len(hist) < max(12, order * 4 + 5):
        return {"matched": False, "pattern": pattern, "reason": "insufficient price history", "metrics": {}}
    prices = pd.to_numeric(hist[col], errors="coerce").dropna().to_numpy(dtype=float)
    if len(prices) < max(12, order * 4 + 5) or not np.isfinite(prices).all() or (prices <= 0).any():
        return {"matched": False, "pattern": pattern, "reason": "invalid price history", "metrics": {}}
    prices = prices[-max_lookback:]
    highs, lows = _turning_points(prices, order, "high"), _turning_points(prices, order, "low")
    metrics: Dict = {}
    matched = False
    reason = "no qualifying geometry"

    if pattern in ("double_bottom", "double_top"):
        pts = lows if pattern == "double_bottom" else highs
        if len(pts) >= 2:
            a, b = pts[-2:]
            similarity = abs(prices[a] / prices[b] - 1) * 100
            separation = b - a
            between = prices[a:b + 1]
            neckline = float(np.max(between) if pattern == "double_bottom" else np.min(between))
            breakout = (prices[-1] - neckline) / neckline * 100 if pattern == "double_bottom" else (neckline - prices[-1]) / neckline * 100
            matched = separation >= min_separation and similarity <= tolerance_pct
            reason = "similar separated pivots" if matched else "pivot spacing or similarity outside limits"
            metrics = {"first_pivot": float(prices[a]), "second_pivot": float(prices[b]),
                       "pivot_similarity_pct": float(similarity), "separation_bars": separation,
                       "neckline": neckline, "neckline_breakout_pct": float(breakout)}
    elif pattern == "head_shoulders":
        if len(highs) >= 3:
            a, b, c = highs[-3:]
            shoulder_diff = abs(prices[a] / prices[c] - 1) * 100
            head_margin = (prices[b] / max(prices[a], prices[c]) - 1) * 100
            matched = b - a >= min_separation and c - b >= min_separation and shoulder_diff <= tolerance_pct and head_margin >= tolerance_pct
            metrics = {"left_shoulder": float(prices[a]), "head": float(prices[b]), "right_shoulder": float(prices[c]),
                       "shoulder_similarity_pct": float(shoulder_diff), "head_margin_pct": float(head_margin)}
            reason = "three-peak geometry" if matched else "shoulders or head separation outside limits"
    elif pattern in ("triangle", "rectangle"):
        # Fit recent high/low envelopes; requiring multiple pivots avoids classifying
        # arbitrary monotonic price movement as a formation.
        start = max(0, len(prices) - min(max_lookback, 40))
        segment = prices[start:]
        h = [i for i in highs if i >= start]
        l = [i for i in lows if i >= start]
        if len(h) >= 2 and len(l) >= 2 and len(segment) >= 20:
            hs = np.polyfit(np.asarray(h, float), prices[h], 1)
            ls = np.polyfit(np.asarray(l, float), prices[l], 1)
            scale = float(np.mean(segment))
            high_slope, low_slope = float(hs[0] / scale * len(segment) * 100), float(ls[0] / scale * len(segment) * 100)
            if pattern == "triangle":
                matched = high_slope < -0.25 and low_slope > 0.25
            else:
                matched = abs(high_slope) <= tolerance_pct and abs(low_slope) <= tolerance_pct
            metrics = {"upper_slope_pct_window": high_slope, "lower_slope_pct_window": low_slope,
                       "window_bars": len(segment)}
            reason = "converging boundaries" if matched and pattern == "triangle" else ("approximately parallel boundaries" if matched else "boundaries do not fit pattern")
    return {"matched": bool(matched), "pattern": pattern, "reason": reason, "metrics": metrics}


def detect_patterns(hist: pd.DataFrame, **kwargs) -> Dict[str, Dict]:
    """Return results for all supported pattern types."""
    return {name: detect_pattern(hist, name, **kwargs) for name in
            ("double_bottom", "double_top", "head_shoulders", "triangle", "rectangle")}
