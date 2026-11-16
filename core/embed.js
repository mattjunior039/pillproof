// Question embedding for retrieval, matching train/scripts/embed.py (bge-small-en-v1.5, q8 ONNX,
// CLS pooling, unit length). Label sentence embeddings are precomputed offline with embed.py
// ("<heading>: <sentence>"); only the question is embedded on the device.
//
// The transformers.js `pipeline` function is passed in, so this file has no import to resolve:
//   import { pipeline } from "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.2";
//   const embed = await makeQueryEmbedder(pipeline);
//   const sims = sentenceSims(await embed(question), labelVectors);

export const EMBED_MODEL = "Xenova/bge-small-en-v1.5";
export const QUERY_PREFIX = "Represent this sentence for searching relevant passages: ";

export async function makeQueryEmbedder(pipeline, options = {}) {
  const extract = await pipeline("feature-extraction", EMBED_MODEL, { dtype: "q8", ...options });
  return async (question) => {
    const out = await extract(QUERY_PREFIX + question, { pooling: "cls", normalize: true });
    return Float32Array.from(out.data);
  };
}

/** Cosine similarity of a unit-length query to each row of `vectors` (array of Float32Array). */
export function sentenceSims(query, vectors) {
  return vectors.map((v) => {
    let s = 0;
    for (let i = 0; i < v.length; i++) s += v[i] * query[i];
    return s;
  });
}
