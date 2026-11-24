// Where a model's weights and WebGPU library come from: the Hugging Face release named in
// app/models.json (model_url / model_lib_url) when present, otherwise the local MLC build.
import type { ModelEntry } from "./device.ts";

export interface ModelSource { model: string; modelLib: string; remote: boolean }

export function modelSource(m: ModelEntry, modelBase: string, libBase: string, baseLib: string): ModelSource {
  if (m.model_url && m.model_lib_url) return { model: m.model_url.replace(/\/+$/, ""), modelLib: m.model_lib_url, remote: true };
  return { model: modelBase + m.mlc_dir, modelLib: libBase + baseLib.split("/").pop(), remote: false };
}
