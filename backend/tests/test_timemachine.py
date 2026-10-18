"""Машина времени 2.0: нет утечки будущего в признаках и в проверке «вне времени»."""
import math

import numpy as np

from app.ml import timemachine as tm


def test_series_features_ignore_years_after_cutoff():
    yearly = {2015: 2, 2016: 4, 2017: 10, 2018: 30, 2019: 5000, 2020: 90000}
    a = tm.series_features(yearly, 2019)
    b = tm.series_features({y: n for y, n in yearly.items() if y < 2019}, 2019)
    assert a == b  # всплеск 2019–2020 на признаки среза 2019 не влияет
    assert a["log_works_total"] == math.log1p(46) and a["age_years"] == 3.0  # первый год с ≥3 работами — 2016
    assert a["growth2"] > 0 and a["accel"] == (math.log1p(30) - math.log1p(10)) - (math.log1p(10) - math.log1p(4))


def test_yc_features_use_only_batches_before_cutoff():
    companies = [{"one_liner": "Vector database for AI", "batch": "Summer 2019"}, {"one_liner": "Vector database", "batch": "Winter 2021"},
                 {"one_liner": "Vector databases at scale", "batch": "Winter 2023"}]
    f = tm.yc_features(companies, "vector database", 2021)
    assert f == {"log_yc_total": math.log1p(1), "log_yc_recent2": math.log1p(1)}  # набор Winter 2021 — уже после 1 января 2021


def test_out_of_time_never_trains_on_same_cutoff(monkeypatch):
    seen = []
    real_fit = tm._fit

    def spy(X, y, C=0.3):
        seen.append(len(y))
        return real_fit(X, y, C)

    monkeypatch.setattr(tm, "_fit", spy)
    rng = np.random.default_rng(0)
    rows = [{"cutoff": c, "label": int(i % 2), "features": {f: float(rng.normal() + (i % 2)) for f in tm.TM_FEATURES}}
            for c, n in ((2016, 10), (2018, 12), (2020, 8)) for i in range(n)]
    p = tm.out_of_time(rows, tm.TM_FEATURES)
    assert seen == [20, 18, 22]  # для каждого года среза модель учится только на двух других
    assert p.shape == (30,) and ((p >= 0) & (p <= 1)).all()


def test_cases_are_unique_and_balanced():
    phrases = [c[0].lower() for c in tm.CASES]
    assert len(phrases) == len(set(phrases)) >= 100
    labels = [c[2] for c in tm.CASES]
    assert 0.35 < sum(labels) / len(labels) < 0.65
    assert {c[1] for c in tm.CASES} == {2016, 2018, 2020, 2021, 2022}
