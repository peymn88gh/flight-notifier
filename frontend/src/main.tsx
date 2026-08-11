import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/vazirmatn/wght.css";
import App from "./App";
import "./styles.css";

window.Telegram?.WebApp.ready();
window.Telegram?.WebApp.expand();

createRoot(document.getElementById("root")!).render(
  <StrictMode><App /></StrictMode>
);
