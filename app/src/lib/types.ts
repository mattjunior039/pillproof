export type Passage = [string, string[]];

/** Which label is used for a medicine (plan §3 item 8). */
export interface LabelMeta {
  splId: string;
  setId: string;
  manufacturer: string;
  /** YYYYMMDD, openFDA effective_time. */
  effective: string;
  /** Name used on the "Drug:" line of the prompt. */
  title: string;
  brandNames: string[];
  genericNames: string[];
  hasPatient: boolean;
  fetched: number;
}

export interface StoredLabel {
  splId: string;
  meta: LabelMeta;
  passages: Passage[];
  /** chunk.ts CHUNKER version the passages were made with (absent = 1). */
  chunker?: number;
  /** One embedding per sentence, in LabelIndex unit order; absent until computed. */
  vectors?: Float32Array[];
}

export interface Med {
  id: string;
  rxcui: string;
  /** RxNorm product name, e.g. "atorvastatin 20 MG Oral Tablet". */
  name: string;
  ingredient: string;
  strength: string;
  form: string;
  brand?: string;
  /** "HH:MM", 24-hour. */
  times: string[];
  label?: LabelMeta;
  labelError?: string;
  created: number;
}
