import numpy as np

from src.f1_pairwise_oos import metric, build_pairwise_rows


def main():
    races = [{
        "season": "2025", "round": "1", "raceName": "Test",
        "Circuit": {"circuitId": "x"},
        "Results": [
            {"Driver": {"driverId": "a"}, "Constructor": {"constructorId": "c1"}, "position": "1", "grid": "1", "points": "25", "status": "Finished"},
            {"Driver": {"driverId": "b"}, "Constructor": {"constructorId": "c2"}, "position": "2", "grid": "2", "points": "18", "status": "Finished"},
            {"Driver": {"driverId": "c"}, "Constructor": {"constructorId": "c3"}, "position": "3", "grid": "3", "points": "15", "status": "Finished"},
        ],
    }, {
        "season": "2025", "round": "2", "raceName": "Test2",
        "Circuit": {"circuitId": "y"},
        "Results": [
            {"Driver": {"driverId": "a"}, "Constructor": {"constructorId": "c1"}, "position": "1", "grid": "1", "points": "25", "status": "Finished"},
            {"Driver": {"driverId": "b"}, "Constructor": {"constructorId": "c2"}, "position": "3", "grid": "3", "points": "15", "status": "Finished"},
            {"Driver": {"driverId": "c"}, "Constructor": {"constructorId": "c3"}, "position": "2", "grid": "2", "points": "18", "status": "Finished"},
        ],
    }]
    rows = build_pairwise_rows(races)
    assert len(rows) == 12
    assert all({"season", "round", "driver_a", "driver_b", "y", "x"} <= set(row) for row in rows)
    pairs = {(row["driver_a"], row["driver_b"]): (row["y"], row["x"]) for row in rows}
    for (a, b), (y, x) in pairs.items():
        if (b, a) in pairs:
            y2, x2 = pairs[(b, a)]
            assert y2 == 1 - y
            assert all(
                (not np.isfinite(v)) or (not np.isfinite(w)) or abs(v + w) < 1e-12
                for v, w in zip(x, x2)
            )
    assert metric([1, 0, 1], [.8, .2, .7])["logloss"] > 0
    print("F1_PAIRWISE_OOS_SMOKE=PASS")


if __name__ == "__main__":
    main()
