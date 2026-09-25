from src.prediction_experience import _score_binary


def test_score_binary_rejects_out_of_range_probability():
    pred = {"probability_side_a": 1.2, "probability_side_b": -0.2}
    try:
        _score_binary(pred, "A")
    except RuntimeError as exc:
        assert "INVALID_BINARY_PROBABILITIES:out_of_range" in str(exc)
    else:
        raise AssertionError("invalid probabilities must fail closed")


def test_score_binary_rejects_non_unit_probability_sum():
    pred = {"probability_side_a": 0.7, "probability_side_b": 0.2}
    try:
        _score_binary(pred, "A")
    except RuntimeError as exc:
        assert "INVALID_BINARY_PROBABILITIES:sum_not_one" in str(exc)
    else:
        raise AssertionError("non-unit probability sum must fail closed")


def test_score_binary_accepts_valid_probabilities():
    result = _score_binary(
        {"probability_side_a": 0.7, "probability_side_b": 0.3},
        "A",
    )
    assert result is not None
    assert result["predicted_outcome"] == "A"
    assert result["correct"] is True
