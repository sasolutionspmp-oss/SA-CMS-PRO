import clsx from "clsx";
import {
  CheckCircle2,
  CircleDashed,
  ClipboardList,
  Loader2,
  Plus,
  RefreshCcw,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  adjustEstimatorScenario,
  createEstimatorScenario,
  fetchEstimatorSummary,
  mineEstimatorScope,
  updateWbsItem,
  type EstimatorSummary,
  type Scenario,
  type WbsItem,
} from "../../api";

export interface EstimatingPanelProps {
  className?: string;
  orgId: string;
  projectId: string;
}

const panelClasses = "rounded-2xl border border-border-subtle bg-surface-elevated shadow-panel";

function formatCurrency(value: number): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value < 1000 ? 0 : 0,
  }).format(value);
}

function collectTotals(
  totals: Scenario["totals"],
  prefix = "",
  acc: Array<{ label: string; value: number }> = [],
): Array<{ label: string; value: number }> {
  if (!totals) {
    return acc;
  }
  if (typeof totals === "number") {
    acc.push({ label: prefix || "Total", value: totals });
    return acc;
  }
  Object.entries(totals).forEach(([key, value]) => {
    const nextLabel = prefix ? `${prefix} · ${key}` : key;
    if (typeof value === "number") {
      acc.push({ label: nextLabel, value });
    } else if (value && typeof value === "object") {
      collectTotals(value as Scenario["totals"], nextLabel, acc);
    }
  });
  return acc;
}

export function EstimatingPanel({ className, orgId, projectId }: EstimatingPanelProps): JSX.Element {
  const [summary, setSummary] = useState<EstimatorSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mining, setMining] = useState(false);
  const [creatingScenario, setCreatingScenario] = useState(false);
  const [savingScenario, setSavingScenario] = useState(false);
  const [scenarioName, setScenarioName] = useState("Copilot scenario");
  const [activeScenarioId, setActiveScenarioId] = useState<string | null>(null);
  const [scenarioTitle, setScenarioTitle] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function hydrate() {
      try {
        setLoading(true);
        setError(null);
        const payload = await fetchEstimatorSummary(orgId, projectId);
        if (cancelled) {
          return;
        }
        setSummary(payload);
        const firstScenario = payload.scenarios[0];
        setActiveScenarioId(firstScenario ? firstScenario.id : null);
        setScenarioTitle(firstScenario ? firstScenario.name : "");
      } catch (cause) {
        if (!cancelled) {
          const message = cause instanceof Error ? cause.message : "Unable to load estimator summary";
          setError(message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    if (orgId && projectId) {
      hydrate();
    }

    return () => {
      cancelled = true;
    };
  }, [orgId, projectId]);

  useEffect(() => {
    const scenario = summary?.scenarios.find((entry) => entry.id === activeScenarioId);
    setScenarioTitle(scenario ? scenario.name : "");
  }, [summary, activeScenarioId]);

  const activeScenario = useMemo(
    () => summary?.scenarios.find((scenario) => scenario.id === activeScenarioId) ?? null,
    [summary, activeScenarioId],
  );

  const scopeAccepted = summary?.wbs.filter((item) => item.accepted).length ?? 0;

  const scenarioTotals = useMemo(() => {
    if (!activeScenario) {
      return [];
    }
    return collectTotals(activeScenario.totals);
  }, [activeScenario]);

  const handleRefresh = async () => {
    try {
      setLoading(true);
      const payload = await fetchEstimatorSummary(orgId, projectId);
      setSummary(payload);
      if (payload.scenarios.length > 0) {
        setActiveScenarioId(payload.scenarios[0].id);
      }
      toast.success("Estimator synchronized");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Unable to refresh estimator";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  const handleMineScope = async () => {
    try {
      setMining(true);
      const items = await mineEstimatorScope(orgId, projectId);
      setSummary((previous) => {
        if (previous) {
          return { ...previous, wbs: items };
        }
        return {
          org_id: orgId,
          project_id: projectId,
          wbs: items,
          rates: [],
          scenarios: [],
        };
      });
      toast.success(`Scope mined for ${items.length} segments`);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Scope mining failed";
      setError(message);
      toast.error(message);
    } finally {
      setMining(false);
    }
  };

  const toggleItemAcceptance = async (item: WbsItem) => {
    const next = !item.accepted;
    setSummary((previous) => {
      if (!previous) {
        return previous;
      }
      return {
        ...previous,
        wbs: previous.wbs.map((entry) => (entry.id === item.id ? { ...entry, accepted: next } : entry)),
      };
    });

    try {
      const updated = await updateWbsItem(item.id, { accepted: next });
      setSummary((previous) => {
        if (!previous) {
          return previous;
        }
        return {
          ...previous,
          wbs: previous.wbs.map((entry) => (entry.id === updated.id ? updated : entry)),
        };
      });
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Unable to update WBS item";
      toast.error(message);
      setSummary((previous) => {
        if (!previous) {
          return previous;
        }
        return {
          ...previous,
          wbs: previous.wbs.map((entry) => (entry.id === item.id ? item : entry)),
        };
      });
    }
  };

  const handleScenarioSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = scenarioName.trim();
    if (!trimmed) {
      toast.error("Enter a scenario name");
      return;
    }
    try {
      setCreatingScenario(true);
      const scenario = await createEstimatorScenario({ org_id: orgId, project_id: projectId, name: trimmed });
      setSummary((previous) => {
        if (previous) {
          return { ...previous, scenarios: [...previous.scenarios, scenario] };
        }
        return {
          org_id: orgId,
          project_id: projectId,
          wbs: [],
          rates: [],
          scenarios: [scenario],
        };
      });
      setActiveScenarioId(scenario.id);
      setScenarioName("Copilot scenario");
      toast.success("Scenario created");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Unable to create scenario";
      toast.error(message);
    } finally {
      setCreatingScenario(false);
    }
  };

  const handleScenarioRename = async () => {
    if (!activeScenario) {
      return;
    }
    const trimmed = scenarioTitle.trim();
    if (!trimmed || trimmed === activeScenario.name) {
      return;
    }
    try {
      setSavingScenario(true);
      const updated = await adjustEstimatorScenario(activeScenario.id, { name: trimmed });
      setSummary((previous) => {
        if (!previous) {
          return previous;
        }
        return {
          ...previous,
          scenarios: previous.scenarios.map((scenario) => (scenario.id === updated.id ? updated : scenario)),
        };
      });
      toast.success("Scenario renamed");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Unable to update scenario";
      toast.error(message);
    } finally {
      setSavingScenario(false);
    }
  };

  const headerActions = (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={handleRefresh}
        className="inline-flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1.5 text-xs font-semibold text-text-secondary shadow-panel transition hover:-translate-y-0.5 hover:bg-surface-muted"
      >
        <RefreshCcw className="h-3.5 w-3.5" /> Sync summary
      </button>
      <button
        type="button"
        onClick={handleMineScope}
        disabled={mining}
        className="inline-flex items-center gap-2 rounded-full border border-accent/50 bg-accent px-3 py-1.5 text-xs font-semibold text-accent-contrast shadow-panel transition hover:-translate-y-0.5 hover:bg-accent/90 disabled:opacity-60"
      >
        {mining ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} Mine scope
      </button>
    </div>
  );

  return (
    <section className={clsx("space-y-6", className)}>
      <header className={clsx(panelClasses, "p-6 sm:p-8")} aria-label="Estimator overview">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-text-tertiary">Estimating Copilot</p>
            <h2 className="mt-2 text-xl font-semibold text-text-primary">Scenario planning workspace</h2>
            <p className="mt-1 max-w-2xl text-sm text-text-secondary">
              Mine work breakdown segments, align rate cards, and collaborate with the estimating copilot to evolve pricing scenarios before committing exports downstream.
            </p>
          </div>
          {headerActions}
        </div>
        <div className="mt-6 grid gap-4 text-xs text-text-secondary sm:grid-cols-3">
          <div className="rounded-xl border border-border-subtle bg-surface px-4 py-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-text-tertiary">Scope accepted</p>
            <p className="mt-1 text-lg font-semibold text-text-primary">
              {scopeAccepted} / {summary?.wbs.length ?? 0}
            </p>
          </div>
          <div className="rounded-xl border border-border-subtle bg-surface px-4 py-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-text-tertiary">Rate entries</p>
            <p className="mt-1 text-lg font-semibold text-text-primary">{summary?.rates.length ?? 0}</p>
          </div>
          <div className="rounded-xl border border-border-subtle bg-surface px-4 py-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-text-tertiary">Scenarios</p>
            <p className="mt-1 text-lg font-semibold text-text-primary">{summary?.scenarios.length ?? 0}</p>
          </div>
        </div>
        {error ? <p className="mt-4 text-sm text-danger">{error}</p> : null}
        {loading ? (
          <div className="mt-6 inline-flex items-center gap-3 text-sm text-text-secondary">
            <Loader2 className="h-4 w-4 animate-spin" /> Hydrating estimator…
          </div>
        ) : null}
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className={clsx(panelClasses, "p-6")} aria-label="Work breakdown structure">
          <header className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-text-primary">Work breakdown</h3>
              <p className="text-xs text-text-secondary">Accept or refine segments prior to pricing.</p>
            </div>
            <span className="inline-flex items-center gap-2 rounded-full bg-accent-soft px-3 py-1 text-xs font-semibold text-accent">
              <ClipboardList className="h-3.5 w-3.5" /> Copilot suggestions
            </span>
          </header>
          <div className="mt-4 space-y-3">
            {summary?.wbs.length ? (
              summary.wbs.map((item) => {
                const accepted = item.accepted;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => toggleItemAcceptance(item)}
                    className={clsx(
                      "w-full rounded-xl border px-4 py-3 text-left shadow-panel transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                      accepted
                        ? "border-success/40 bg-success-soft/80 text-text-primary"
                        : "border-border-subtle bg-surface text-text-secondary hover:bg-surface-muted",
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-text-primary">{item.code} · {item.description}</p>
                        <p className="mt-1 text-xs text-text-secondary">Confidence {Math.round(item.confidence * 100)}%</p>
                      </div>
                      {accepted ? (
                        <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
                      ) : (
                        <CircleDashed className="h-4 w-4 text-text-tertiary" aria-hidden />
                      )}
                    </div>
                  </button>
                );
              })
            ) : (
              <div className="rounded-xl border border-border-subtle border-dashed bg-surface px-4 py-6 text-center text-sm text-text-secondary">
                No scope mined yet. Trigger copilot mining to draft the breakdown.
              </div>
            )}
          </div>
        </section>

        <section className={clsx(panelClasses, "p-6 space-y-4")} aria-label="Rate library">
          <header className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-text-primary">Rate intelligence</h3>
              <p className="text-xs text-text-secondary">Crew and material ranges surfaced by copilot.</p>
            </div>
          </header>
          {summary?.rates.length ? (
            <div className="space-y-3">
              {summary.rates.map((rate) => (
                <div key={rate.id} className="rounded-xl border border-border-subtle bg-surface px-4 py-3 shadow-panel">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold text-text-primary">{rate.category}</p>
                      {rate.csi_code ? <p className="text-xs text-text-secondary">CSI {rate.csi_code}</p> : null}
                    </div>
                    <div className="text-right text-xs text-text-secondary">
                      <p>Low {formatCurrency(rate.low_rate)}</p>
                      <p>Base {formatCurrency(rate.base_rate)}</p>
                      <p>High {formatCurrency(rate.high_rate)}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-border-subtle border-dashed bg-surface px-4 py-6 text-center text-sm text-text-secondary">
              Rate cards load here after the first platform sync.
            </div>
          )}
        </section>
      </div>

      <section className={clsx(panelClasses, "p-6 space-y-5")} aria-label="Scenario cockpit">
        <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-base font-semibold text-text-primary">Scenarios</h3>
            <p className="text-xs text-text-secondary">Iterate pricing blends and share with downstream estimators.</p>
          </div>
          <form className="flex flex-wrap items-center gap-2" onSubmit={handleScenarioSubmit}>
            <input
              type="text"
              value={scenarioName}
              onChange={(event) => setScenarioName(event.target.value)}
              className="w-48 rounded-full border border-border-subtle bg-surface px-3 py-1.5 text-xs text-text-primary shadow-inner focus:border-accent focus:outline-none"
              placeholder="Scenario name"
            />
            <button
              type="submit"
              disabled={creatingScenario}
              className="inline-flex items-center gap-2 rounded-full border border-accent/50 bg-accent px-3 py-1.5 text-xs font-semibold text-accent-contrast shadow-panel transition hover:-translate-y-0.5 hover:bg-accent/90 disabled:opacity-60"
            >
              {creatingScenario ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />} New scenario
            </button>
          </form>
        </header>
        <div className="flex flex-wrap items-center gap-2">
          {summary?.scenarios.length ? (
            summary.scenarios.map((scenario) => (
              <button
                key={scenario.id}
                type="button"
                onClick={() => setActiveScenarioId(scenario.id)}
                className={clsx(
                  "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold shadow-panel transition",
                  scenario.id === activeScenarioId
                    ? "border-accent/60 bg-accent text-accent-contrast"
                    : "border-border-subtle bg-surface text-text-secondary hover:bg-surface-muted",
                )}
              >
                {scenario.name}
              </button>
            ))
          ) : (
            <span className="text-xs text-text-secondary">Copilot will list scenarios here after creation.</span>
          )}
        </div>
        {activeScenario ? (
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-3">
              <label className="block text-xs font-semibold uppercase tracking-[0.3em] text-text-tertiary" htmlFor="scenario-title">
                Scenario title
              </label>
              <div className="flex items-center gap-2">
                <input
                  id="scenario-title"
                  type="text"
                  value={scenarioTitle}
                  onChange={(event) => setScenarioTitle(event.target.value)}
                  className="w-full rounded-full border border-border-subtle bg-surface px-3 py-1.5 text-sm text-text-primary shadow-inner focus:border-accent focus:outline-none"
                />
                <button
                  type="button"
                  onClick={handleScenarioRename}
                  disabled={savingScenario}
                  className="inline-flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1.5 text-xs font-semibold text-text-secondary shadow-panel transition hover:bg-surface-muted disabled:opacity-60"
                >
                  {savingScenario ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save"}
                </button>
              </div>
              <div className="rounded-xl border border-border-subtle bg-surface px-4 py-3 text-xs text-text-secondary shadow-panel">
                <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-text-tertiary">Markups</p>
                <dl className="mt-2 space-y-1">
                  {Object.entries(activeScenario.markup_summary ?? {}).map(([key, value]) => (
                    <div key={key} className="flex items-center justify-between gap-2">
                      <dt className="text-xs text-text-secondary">{key}</dt>
                      <dd className="text-xs font-semibold text-text-primary">{formatCurrency(Number(value))}</dd>
                    </div>
                  ))}
                  {Object.keys(activeScenario.markup_summary ?? {}).length === 0 ? (
                    <p>No markups recorded yet.</p>
                  ) : null}
                </dl>
              </div>
            </div>
            <div className="rounded-xl border border-border-subtle bg-surface px-4 py-3 shadow-panel">
              <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-text-tertiary">Totals</p>
              <dl className="mt-2 space-y-1 text-xs text-text-secondary">
                {scenarioTotals.length ? (
                  scenarioTotals.map((entry) => (
                    <div key={entry.label} className="flex items-center justify-between gap-2">
                      <dt>{entry.label}</dt>
                      <dd className="font-semibold text-text-primary">{formatCurrency(entry.value)}</dd>
                    </div>
                  ))
                ) : (
                  <p>Totals will populate once cost models sync.</p>
                )}
              </dl>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-border-subtle border-dashed bg-surface px-4 py-6 text-center text-sm text-text-secondary">
            Select a scenario to view copilot analysis.
          </div>
        )}
      </section>
    </section>
  );
}
