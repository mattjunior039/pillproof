"""Chunked gated delta rule == mlx-lm's per-token reference (CPU, float32).

Run: ~/waicy-work/envs/mlx/bin/python -m pytest train/tests -q
"""

import sys
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mlx_lm.models.gated_delta import gated_delta_ops, normalize_qk  # noqa: E402

import chunked_gdn  # noqa: E402

mx.set_default_device(mx.cpu)


def _inputs(B, T, Hk, Hv, D, seed, correlated=False):
    mx.random.seed(seed)
    q = mx.random.normal((B, T, Hk, D))
    k = mx.random.normal((B, T, Hk, D))
    if correlated:  # aligned keys + slow decay (as in real Qwen3.5 layers) broke a power-series inverse
        k = mx.random.normal((1, 1, Hk, D)) + 0.3 * k
    v = mx.random.normal((B, T, Hv, D))
    q, k = normalize_qk(q, k, inv_scale=D**-0.5, eps=1e-6)
    a = mx.random.normal((B, T, Hv))
    beta = mx.sigmoid(mx.random.normal((B, T, Hv)) * 2 + (4 if correlated else 0))
    A_log = mx.log(mx.full((Hv,), 0.01) if correlated else mx.random.uniform(0.01, 16, (Hv,)))
    log_g = -mx.exp(A_log) * nn.softplus(a + 1.0)
    return q, k, v, log_g, beta


@pytest.mark.parametrize("T,Hk,Hv,correlated,init", [
    (150, 4, 4, False, False), (130, 2, 4, False, True), (200, 2, 2, True, False), (64, 2, 2, False, False),
])
def test_forward_matches_reference(T, Hk, Hv, correlated, init):
    q, k, v, log_g, beta = _inputs(2, T, Hk, Hv, 64, seed=T, correlated=correlated)
    state = mx.random.normal((2, Hv, 64, 64)) * 0.1 if init else None
    y0, s0 = gated_delta_ops(q, k, v, mx.exp(log_g), beta, state)
    y1, s1 = chunked_gdn.chunked_gated_delta(q, k, v, log_g, beta, state)
    assert mx.isfinite(y1).all().item()
    assert (mx.abs(y1 - y0).max() / mx.abs(y0).max()).item() < 1e-4
    assert (mx.abs(s1 - s0).max() / mx.abs(s0).max()).item() < 1e-4


def test_gradients_match_reference():
    q, k, v, log_g, beta = _inputs(1, 80, 2, 2, 32, seed=3)
    w = mx.random.normal(v.shape)

    def f(fn):
        return lambda q, k, v, b: (fn(q, k, v, b)[0] * w).sum()

    ref = mx.grad(f(lambda q, k, v, b: gated_delta_ops(q, k, v, mx.exp(log_g), b, None)), argnums=(0, 1, 2, 3))
    new = mx.grad(f(lambda q, k, v, b: chunked_gdn.chunked_gated_delta(q, k, v, log_g, b, None)), argnums=(0, 1, 2, 3))
    for g0, g1 in zip(ref(q, k, v, beta), new(q, k, v, beta)):
        assert (mx.abs(g1 - g0).max() / mx.abs(g0).max()).item() < 1e-4
