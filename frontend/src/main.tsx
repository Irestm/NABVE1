import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
// Self-hosted (no runtime network calls, same principle as
// design/fonts/PressStart2P-Regular.woff2's @font-face) — Fraunces for
// headings/titles (see theme.css's --font-heading), Inter for body/UI text
// (see --font-body), replacing the previous OS-default font stack so the
// app looks the same across Windows/Linux/Mac instead of picking up
// whatever each OS happens to substitute for "Inter" in the old fallback list.
import "@fontsource/fraunces/500.css";
import "@fontsource/fraunces/600.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root container not found");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
