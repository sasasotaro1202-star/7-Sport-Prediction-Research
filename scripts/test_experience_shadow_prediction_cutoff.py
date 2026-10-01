from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'src/future_predictor.py').read_text(encoding='utf-8')


def main():
    # Both binary future-prediction lanes must bind experience to the
    # target prediction cutoff, never wall-clock generation time.
    marker=SRC.index('def _safe_prior_binary(')
    f1=SRC.index('def _safe_prior_f1(', marker)
    safe_block=SRC[marker:f1]
    main_marker=SRC.index('def predict_sport(')
    main_block=SRC[main_marker:]
    assert 'experience_learning.shadow_signal(\n            cutoff,s,' in safe_block
    assert 'experience_learning.shadow_signal(\n            cutoff,s,' in main_block
    assert 'experience_learning.shadow_signal(\n            now,s,' not in safe_block
    assert 'experience_learning.shadow_signal(\n            now,s,' not in main_block
    print('experience shadow prediction-cutoff PIT binding: PASS')


if __name__=='__main__':
    main()
