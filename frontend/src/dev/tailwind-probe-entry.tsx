import React from "react";
import ReactDOM from "react-dom/client";
import "../index.css";
import { TailwindProbe } from "../components/dev/TailwindProbe";

const root = document.getElementById("root") as HTMLElement;

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <div className="space-y-6 bg-slate-50 p-6 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <TailwindProbe />
    </div>
  </React.StrictMode>
);
