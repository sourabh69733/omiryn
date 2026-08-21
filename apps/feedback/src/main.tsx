import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { FeedbackApp } from "./FeedbackApp";
import "./styles.css";
import "./themes/playground-v1.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <FeedbackApp />
  </StrictMode>,
);
