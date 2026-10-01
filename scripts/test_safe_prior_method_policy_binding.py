from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'src/future_predictor.py').read_text(encoding='utf-8')


def main():
    marker=SRC.index('def _safe_prior_binary(')
    end=SRC.index('def _safe_prior_f1(', marker)
    block=SRC[marker:end]
    assert 'method_policy=prediction_method_policy.select_method(' in block
    assert "'prediction_method_policy':method_policy" in block
    assert block.index('method_policy=prediction_method_policy.select_method(') < block.index("'prediction_method_policy':method_policy")
    assert "strategy='safe_prior'" in block
    print('safe-prior method-policy binding: PASS')


if __name__=='__main__':
    main()
