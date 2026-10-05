import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./ui/App";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/legacy-app.css";
import "./styles/onboarding.css";
import "./styles/vibe.css";
import "./styles/brand-theme.css";
import "./styles/states.css";

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App />
  </StrictMode>
);
