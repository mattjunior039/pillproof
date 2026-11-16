"""Chunked (WY-form) gated delta rule for training Qwen3.5 with MLX.

In training mode mlx-lm runs Qwen3.5's linear-attention layers (GatedDeltaNet)
as a Python loop over tokens (`gated_delta_ops`). Autodiff then keeps a
[heads x 128 x 128] state per token per layer, about 18 GB for a single
1,000-token example, and each step is ~16 s. This module computes the same
recurrence chunk by chunk with matrix products (the algorithm used by
flash-linear-attention's `chunk_gated_delta_rule`):

    per step:  S = g*S;  S = S + beta*(v - S k) k^T;  y = S q      (S: [Dv, Dk])

Within a chunk of C tokens (log-decays G = cumsum(log g)):
    A   = strict_lower((beta*K) K^T * exp(G_i - G_j))
    T   = (I + A)^-1                        (unit lower-triangular; see _unit_lower_inv)
    U   = T (beta*V),   W = T (beta*K*exp(G))
    Vn  = U - W S0^T
    Y   = (Q*exp(G)) S0^T + lower_incl_diag(Q K^T * exp(G_i - G_j)) Vn
    S1  = exp(G_C) S0 + Vn^T (K*exp(G_C - G))

Only chunk-boundary states are kept, and everything is differentiable MLX ops.
`patch()` swaps it in for the training path only (use_kernel=False, no mask);
inference keeps mlx-lm's Metal kernel.
"""

import mlx.core as mx
import mlx.nn as nn

CHUNK = 64


def _unit_lower_inv(a: mx.array, c: int) -> mx.array:
    """(I + A)^-1 for strictly lower-triangular A ([..., c, c]), c a power of two.

    Blocked recursive doubling: the inverse of [[L1, 0], [L21, L2]] is
    [[T1, 0], [-T2 L21 T1, T2]], so diagonal blocks of size 1, 2, 4, ... c are built
    in log2(c) batched-matmul levels. Every factor is itself a (bounded) block of the
    true inverse, so this is as stable as forward substitution. (The shortcut
    (I - A)(I + A^2)(I + A^4)... is exact in theory but powers of A overflow on real
    Qwen3.5 keys and produce NaN.)
    """
    lead = a.shape[:-2]
    t = mx.ones(lead + (c, 1, 1), dtype=a.dtype)  # inverse diagonal blocks of size s
    s = 1
    while s < c:
        nb = c // (2 * s)
        blocks = a.reshape(lead + (nb, 2 * s, nb, 2 * s))
        sel = mx.eye(nb, dtype=a.dtype)[:, None, :, None]
        diag = (blocks * sel).sum(axis=-2)  # [..., nb, 2s, 2s] diagonal blocks of A
        l21 = diag[..., s:, :s]
        t1, t2 = t[..., 0::2, :, :], t[..., 1::2, :, :]
        low = -(t2 @ l21 @ t1)
        top = mx.concatenate([t1, mx.zeros_like(t1)], axis=-1)
        bot = mx.concatenate([low, t2], axis=-1)
        t = mx.concatenate([top, bot], axis=-2)
        s *= 2
    return t.reshape(lead + (c, c))


def chunked_gated_delta(q, k, v, log_g, beta, state=None, chunk: int = CHUNK):
    """q, k: [B,T,Hk,Dk] (already normalized, q pre-scaled); v: [B,T,Hv,Dv];
    log_g, beta: [B,T,Hv]; state: [B,Hv,Dv,Dk] or None. Returns (y [B,T,Hv,Dv], state)."""
    B, T, Hk, Dk = q.shape
    Hv, Dv = v.shape[-2:]
    dtype = q.dtype
    if (rep := Hv // Hk) > 1:
        q = mx.repeat(q, rep, -2)
        k = mx.repeat(k, rep, -2)
    f32 = mx.float32
    # -> [B, H, T, D]
    q, k, v = (x.transpose(0, 2, 1, 3).astype(f32) for x in (q, k, v))
    log_g = log_g.transpose(0, 2, 1).astype(f32)
    beta = beta.transpose(0, 2, 1).astype(f32)
    pad = (-T) % chunk
    if pad:
        q, k, v = (mx.pad(x, [(0, 0), (0, 0), (0, pad), (0, 0)]) for x in (q, k, v))
        log_g = mx.pad(log_g, [(0, 0), (0, 0), (0, pad)])
        beta = mx.pad(beta, [(0, 0), (0, 0), (0, pad)])
    n = (T + pad) // chunk
    q, k, v = (x.reshape(B, Hv, n, chunk, -1) for x in (q, k, v))
    log_g = log_g.reshape(B, Hv, n, chunk)
    beta = beta.reshape(B, Hv, n, chunk)

    G = mx.cumsum(log_g, axis=-1)  # [B,H,n,C]
    idx = mx.arange(chunk)
    incl = idx[:, None] >= idx[None, :]
    strict = idx[:, None] > idx[None, :]
    diff = G[..., :, None] - G[..., None, :]
    decay = mx.exp(mx.where(incl, diff, -mx.inf))  # 0 above the diagonal

    kb = k * beta[..., None]
    vb = v * beta[..., None]
    A = mx.where(strict, (kb @ k.swapaxes(-1, -2)) * decay, 0.0)
    Tm = _unit_lower_inv(A, chunk)
    U = Tm @ vb  # [B,H,n,C,Dv]
    W = Tm @ (kb * mx.exp(G)[..., None])  # [B,H,n,C,Dk]
    attn = mx.where(incl, (q @ k.swapaxes(-1, -2)) * decay, 0.0)  # [B,H,n,C,C]
    qg = q * mx.exp(G)[..., None]
    g_last = G[..., -1]  # [B,H,n]
    k_tail = k * mx.exp(g_last[..., None] - G)[..., None]

    # State as [Dk, Dv] for the chunk algebra.
    S = mx.zeros((B, Hv, Dk, Dv), f32) if state is None else state.astype(f32).swapaxes(-1, -2)
    ys = []
    for i in range(n):
        v_new = U[:, :, i] - W[:, :, i] @ S
        ys.append(qg[:, :, i] @ S + attn[:, :, i] @ v_new)
        S = S * mx.exp(g_last[:, :, i])[..., None, None] + k_tail[:, :, i].swapaxes(-1, -2) @ v_new
    y = mx.stack(ys, axis=2).reshape(B, Hv, n * chunk, Dv)[:, :, :T]
    return y.transpose(0, 2, 1, 3).astype(dtype), S.swapaxes(-1, -2)


def patch():
    """Use the chunked form for Qwen3.5 linear-attention layers in training mode."""
    from mlx_lm.models import gated_delta, qwen3_5

    original = qwen3_5.gated_delta_update

    def update(q, k, v, a, b, A_log, dt_bias, state=None, mask=None, *, use_kernel=True,
               lower_bound=None, allow_neg_eigval=False):
        if use_kernel or mask is not None or lower_bound is not None:
            return original(q, k, v, a, b, A_log, dt_bias, state, mask, use_kernel=use_kernel,
                            lower_bound=lower_bound, allow_neg_eigval=allow_neg_eigval)
        beta = mx.sigmoid(b)
        if allow_neg_eigval:
            beta = beta * 2.0
        log_g = -mx.exp(A_log.astype(mx.float32)) * nn.softplus(a + dt_bias)
        return chunked_gated_delta(q, k, v, log_g, beta, state)

    qwen3_5.gated_delta_update = update
    return gated_delta
