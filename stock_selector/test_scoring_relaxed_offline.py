"""Offline regression checks for v2 filtering with incomplete provider data."""

from stock_selector.strategies.scoring_engine import ScoringEngine


def test_missing_amount_does_not_reject_tencent_candidate():
    config = {
        'filters': {
            'liquidity': {'turnover_min': 2, 'amount_min': 0.2, 'volume_ratio_min': 0.8},
            'price': {'change_min': -2, 'change_max': 12, 'price_min': 1.5},
            'board': {'allow_st': False, 'allow_cyb': True, 'allow_kcb': True},
        },
        'signals': {},
        'output': {'min_score': 0},
    }
    candidate = {
        'code': '600000', 'name': '测试股票', 'price': 10,
        'change_pct': 0.5, 'turnover': 3, 'volume_ratio': 1,
        # Tencent quote rows have no amount field.
    }

    result = ScoringEngine(config).evaluate(candidate)

    assert result is not None
    assert result.passed


def test_false_boolean_signal_receives_no_score():
    engine = ScoringEngine({'signals': {}, 'output': {'min_score': 0}})

    score, signal = engine._evaluate_metric(
        {'volume_expansion': False},
        {'name': 'volume_expansion', 'enabled': True, 'score': 25},
    )

    assert score == 0
    assert signal is None
