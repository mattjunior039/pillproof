// Python's notion of whitespace (str.isspace / str.strip / re "\s"), so the JS
// ports match datapipe exactly. JS \s and String.trim differ slightly (\x1c-\x1f,
// \x85, \ufeff).
export const PY_WS = "\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";

const LEAD = new RegExp(`^[${PY_WS}]+`);
const TRAIL = new RegExp(`[${PY_WS}]+$`);

export const pyStrip = (s) => s.replace(LEAD, "").replace(TRAIL, "");
export const pyRstrip = (s) => s.replace(TRAIL, "");
