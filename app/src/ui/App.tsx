import { go, useApp, type Tab } from "../store.ts";
import { Ask } from "./Ask.tsx";
import { Changes } from "./Changes.tsx";
import { Meds } from "./Meds.tsx";
import { Settings } from "./Settings.tsx";
import { Today } from "./Today.tsx";
import { Voice } from "./Voice.tsx";

const TABS: [Tab, string, string][] = [
  ["today", "Today", "🕒"],
  ["meds", "Medicines", "💊"],
  ["ask", "Ask", "💬"],
  ["voice", "Voice", "🎤"],
  ["changes", "Changes", "📝"],
];

export function App() {
  const s = useApp();
  if (!s.ready) return <main class="screen"><p class="busy">Loading…</p></main>;
  const Screen = { today: Today, meds: Meds, ask: Ask, voice: Voice, changes: Changes, settings: Settings }[s.tab];
  return (
    <>
      <header class="top">
        <span class="brand">MedLabel</span>
        <button class={`gear ${s.tab === "settings" ? "on" : ""}`} aria-label="Settings" aria-current={s.tab === "settings" ? "page" : undefined} onClick={() => go("settings")}>⚙︎ Settings</button>
      </header>
      <main class="screen" id="main"><Screen /></main>
      <nav class="tabs" aria-label="Screens">
        {TABS.map(([id, label, icon]) => (
          <button class={s.tab === id ? "on" : ""} aria-current={s.tab === id ? "page" : undefined} onClick={() => { go(id); scrollTo(0, 0); }}>
            <span aria-hidden="true">{icon}</span>{label}
          </button>
        ))}
      </nav>
    </>
  );
}
