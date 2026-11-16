"""mlx_lm.lora with a memory-light loss for --mask-prompt training.

It also swaps in a chunked GatedDeltaNet for training (see chunked_gdn.py); without
it Qwen3.5 training runs a per-token loop that needs ~18 GB per 1,000-token example.

Qwen3.5 has a 248k-token vocabulary. The stock loss computes logits for every
position (batch x ~1,000 tokens x 248k floats), which runs out of GPU memory at
batch size 2 on a 24 GB Mac, even though only the ~40 answer tokens carry loss.
This launcher computes logits only at the target positions:

    hidden = backbone(inputs)                  # (B, L, D)
    hidden = hidden[target positions]          # (B, K, D), K = longest target in batch
    logits = tied_embedding.as_linear(hidden)  # (B, K, V)

Everything else (data loading, chat template, LoRA layers, optimizer, schedule,
checkpoints, adapter_config.json) is stock mlx_lm.lora. The loss value equals the
stock masked loss, except that the stock mask also scores one padding token after
the end of each example (steps <= length); this one stops at the last real token.

Usage (repo root):
    ~/waicy-work/envs/mlx/bin/python train/scripts/lora_train.py -c train/configs/lora_2b.yaml
"""

import sys
from functools import partial

import mlx.core as mx
import mlx.nn as nn
import numpy as np
from mlx_lm import lora
from mlx_lm.tuner import trainer

import chunked_gdn

chunked_gdn.patch()

PAD_K = 16


def _text_model(model):
    return model.language_model if hasattr(model, "language_model") else model


def target_loss(model, batch, lengths, gidx):
    inputs, targets = batch[:, :-1], batch[:, 1:]
    tm = _text_model(model)
    hidden = tm.model(inputs)
    hidden = mx.take_along_axis(hidden, gidx[..., None], axis=1)
    if tm.args.tie_word_embeddings:
        logits = tm.model.embed_tokens.as_linear(hidden)
    else:
        logits = tm.lm_head(hidden)
    tgt = mx.take_along_axis(targets, gidx, axis=1)
    pos = gidx + 1  # 1-based position of the predicted token in `batch`
    mask = mx.logical_and(pos >= lengths[:, 0:1], pos <= lengths[:, 1:] - 1)
    ce = nn.losses.cross_entropy(logits, tgt) * mask
    ntoks = mask.sum()
    return ce.astype(mx.float32).sum() / ntoks, ntoks


def target_batches(dataset, batch_size, max_seq_length, loop=False, seed=None, comm_group=None):
    """Stock batches plus a (B, K) index of the input positions whose next token is a target."""
    for batch, lengths in trainer.iterate_batches(dataset, batch_size, max_seq_length, loop, seed, comm_group):
        ln = np.array(lengths)
        offs, ends = ln[:, 0], ln[:, 1]
        n_tgt = np.maximum(ends - offs, 1)
        k = int(PAD_K * -(-int(n_tgt.max()) // PAD_K))
        width = batch.shape[1] - 1
        start = np.maximum(offs - 1, 0)
        gidx = np.minimum(start[:, None] + np.arange(k)[None, :], width - 1).astype(np.int32)
        yield batch, lengths, mx.array(gidx)


lora.train = partial(trainer.train, loss=target_loss, iterate_batches=target_batches)
lora.evaluate = partial(trainer.evaluate, loss=target_loss, iterate_batches=target_batches)

if __name__ == "__main__":
    sys.exit(lora.main())
