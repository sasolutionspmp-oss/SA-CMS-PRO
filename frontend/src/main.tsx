import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { TailwindProbe } from "./components/dev/TailwindProbe";

const root = document.getElementById("root") as HTMLElement;
const showProbe = import.meta.env.DEV || import.meta.env.VITE_TAILWIND_PROBE === "1";

const app = (
  <React.StrictMode>
    {showProbe ? (
      <div className="space-y-6 bg-slate-50 p-6 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
        <TailwindProbe />
        <App />
      </div>
    ) : (
      <App />
    )}
  </React.StrictMode>
);

ReactDOM.createRoot(root).render(app);
