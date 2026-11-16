"""Run the `mlc_llm` CLI with a workaround for the macOS nightly wheels.

mlc-llm-nightly-cpu 0.26.dev6 + mlc-ai-nightly-cpu 0.26.dev246 segfault while
building Qwen3.5 (and any model using RNNState): TVMScript fails to parse the
`seq_id: T.int32 = ...` local bindings inside `RNNState.create_get_func` /
`create_set_func`, and printing that parse error crashes tvm-ffi. The
replacements below are the same copy kernels with the index loads inlined.

A second mismatch: `nn.Parameter.dtype` is now a `tvm.ir.PrimType`, which the
loader passes straight to `numpy.astype`. `_add_mapping` converts it to str.

Third, the TVM JIT in that wheel cannot run any compiled function on this Mac
(even a trivial add segfaults on llvm and metal), so the q4f16_1 quantize kernel
is replaced by an equivalent NumPy implementation. Its output is checked
against mlc-ai's official prebuilt shards by `compare_mlc_weights.py`.

Usage: python mlc_cli.py convert_weight ... | gen_config ... | compile ...
"""

import functools
import runpy
import sys

import numpy as np
import tvm
from tvm.script import tirx as T

from mlc_llm.loader import ExternMapping
from mlc_llm.nn.rnn_state import RNNState
from mlc_llm.quantization.group_quantization import GroupQuantize

_orig_add_mapping = ExternMapping.add_mapping


def _add_mapping(self, map_from, map_to, func):
    if isinstance(func, functools.partial) and "dtype" in func.keywords:
        func = functools.partial(
            func.func, *func.args, **{**func.keywords, "dtype": str(func.keywords["dtype"])}
        )
    _orig_add_mapping(self, map_from, map_to, func)


ExternMapping.add_mapping = _add_mapping


def _create_get_func(shape, dtype, max_batch_size, max_history, state_id):
    shape = list(shape)
    ndim = len(shape)

    @T.prim_func(s_tir=True)
    def f(
        var_storage: T.handle,
        var_seq_slot_ids: T.handle,
        var_history_slot_ids: T.handle,
        var_output: T.handle,
    ):
        batch_size = T.int32()
        T.func_attr({"global_symbol": f"rnn_state_get_{state_id}"})
        storage = T.match_buffer(var_storage, (max_batch_size, max_history, *shape), dtype)
        seq_slot_ids = T.match_buffer(var_seq_slot_ids, (batch_size,), "int32")
        history_slot_ids = T.match_buffer(var_history_slot_ids, (batch_size,), "int32")
        output = T.match_buffer(var_output, (batch_size, *shape), dtype)
        for i in range(batch_size):
            for s in T.grid(*shape):
                with T.sblock("copy"):
                    vi, *vs = T.axis.remap("S" * (ndim + 1), [i, *s])
                    T.buffer_store(
                        output,
                        T.BufferLoad(
                            storage, [seq_slot_ids[vi], history_slot_ids[vi], *vs]
                        ),
                        [vi, *vs],
                    )

    return f


def _create_set_func(shape, dtype, max_batch_size, max_history, state_id):
    shape = list(shape)
    ndim = len(shape)

    @T.prim_func(s_tir=True)
    def f(
        var_storage: T.handle,
        var_seq_slot_ids: T.handle,
        var_history_slot_ids: T.handle,
        var_data: T.handle,
    ):
        batch_size = T.int32()
        T.func_attr({"global_symbol": f"rnn_state_set_{state_id}"})
        storage = T.match_buffer(var_storage, (max_batch_size, max_history, *shape), dtype)
        seq_slot_ids = T.match_buffer(var_seq_slot_ids, (batch_size,), "int32")
        history_slot_ids = T.match_buffer(var_history_slot_ids, (batch_size,), "int32")
        data = T.match_buffer(var_data, (batch_size, *shape), dtype)
        for i in range(batch_size):
            for s in T.grid(*shape):
                with T.sblock("copy"):
                    vi, *vs = T.axis.remap("S" * (ndim + 1), [i, *s])
                    T.buffer_store(
                        storage,
                        T.BufferLoad(data, [vi, *vs]),
                        [
                            seq_slot_ids[vi],
                            (history_slot_ids[vi] + 1) % T.cast(max_history, "int32"),
                            *vs,
                        ],
                    )

    return f


def _numpy_quantize_weight(self, weight, axis=-1, output_transpose=False):
    """NumPy port of GroupQuantize._quantize (symmetric int4, groups along `axis`)."""
    w = weight.numpy()
    dtype = np.dtype(self.model_dtype)
    w = w.astype(dtype)
    axis = axis if axis >= 0 else w.ndim + axis
    w = np.moveaxis(w, axis, -1)
    k = w.shape[-1]
    gs, epb = self.group_size, self.num_elem_per_storage
    num_group = -(-k // gs)
    pad = num_group * gs - k
    if pad:
        w = np.concatenate([w, np.zeros((*w.shape[:-1], pad), dtype)], axis=-1)
    groups = w.reshape(*w.shape[:-1], num_group, gs)
    max_int = dtype.type(self.max_int_value)
    # Reproduces the numerics of the compiled TVM kernel bit-for-bit (verified
    # with compare_mlc_weights.py against mlc-ai's prebuilt shards): division by
    # a value is lowered to multiplication by its reciprocal in model dtype, the
    # multiply-add is fused (single rounding to f16), and round() is half away
    # from zero.
    scale = (np.abs(groups).max(axis=-1) * (dtype.type(1) / max_int)).astype(dtype)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        recip = (dtype.type(1) / scale).astype(np.float32)
        scaled = (groups.astype(np.float32) * recip[..., None] + np.float32(max_int)).astype(dtype)
        scaled = np.floor(scaled.astype(np.float32) + np.float32(0.5))
    # All-zero groups give 0 * inf = NaN; the compiled max(NaN, 0) yields 0.
    scaled = np.nan_to_num(scaled, nan=0)
    q = np.clip(scaled, 0, max_int * 2).astype(np.uint32)
    q = q.reshape(*w.shape[:-1], num_group * gs)[..., :k]
    num_storage = self.num_storage_per_group * num_group
    q = np.concatenate(
        [q, np.zeros((*q.shape[:-1], num_storage * epb - k), np.uint32)], axis=-1
    ).reshape(*q.shape[:-1], num_storage, epb)
    bits = int(self.quantize_dtype[3:])
    shifts = (np.arange(epb, dtype=np.uint32) * bits).astype(np.uint32)
    packed = np.bitwise_or.reduce(q << shifts, axis=-1).astype(np.uint32)
    packed = np.moveaxis(packed, -1, axis)
    scale = np.moveaxis(scale, -1, axis)
    if output_transpose:
        packed, scale = packed.T, scale.T
    dev = weight.device
    return [
        tvm.runtime.tensor(np.ascontiguousarray(packed), dev),
        tvm.runtime.tensor(np.ascontiguousarray(scale), dev),
    ]


RNNState.create_get_func = staticmethod(_create_get_func)
RNNState.create_set_func = staticmethod(_create_set_func)
GroupQuantize.quantize_weight = _numpy_quantize_weight

if __name__ == "__main__":
    sys.argv = ["mlc_llm"] + sys.argv[1:]
    runpy.run_module("mlc_llm", run_name="__main__", alter_sys=True)
