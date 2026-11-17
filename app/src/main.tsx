import { render } from "preact";
import { App } from "./ui/App.tsx";
import { init } from "./store.ts";
import "./styles.css";

render(<App />, document.getElementById("app")!);
init().catch((e) => {
  document.getElementById("app")!.textContent = `MedLabel could not start: ${e?.message || e}`;
});
