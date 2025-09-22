import clsx from "clsx";

interface EstimatingPanelProps {
  className?: string;
  orgId?: string | null;
  projectId?: string | null;
}

export function EstimatingPanel({ className, orgId, projectId }: EstimatingPanelProps) {
  return (
    <section
      className={clsx(
        "rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900",
        className,
      )}
    >
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Estimating workspace</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Configure rates, scopes, and costing references for upcoming bids.
          </p>
        </div>
        <span className="rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-600 dark:text-emerald-300">
          Beta
        </span>
      </header>

      <div className="space-y-3 text-sm text-slate-700 dark:text-slate-300">
        <p>
          <strong>Organization:</strong> {orgId ?? "Not selected"}
        </p>
        <p>
          <strong>Project code:</strong> {projectId ?? "No project"}
        </p>
        <p>
          The production build hydrates this panel with dynamic scopes, cost curves, and export templates. Until those APIs are
          wired, the placeholder summarizes the context pulled from the bootstrap payload.
        </p>
      </div>
    </section>
  );
}
