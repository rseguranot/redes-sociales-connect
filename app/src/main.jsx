import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";
import { ConnectSessionGate } from "./AuthGate.jsx";
import "./styles.css";
import "./auth.css";
import { getBrand } from "./runtimeConfig";

const brand = getBrand();
document.documentElement.lang = "es";
document.title = `${brand.name} | Redes Sociales`;

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ConnectSessionGate>
      {(context) => <App context={context} />}
    </ConnectSessionGate>
  </React.StrictMode>,
);
