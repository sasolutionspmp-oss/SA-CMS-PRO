import clsx from "clsx";
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
import {
  CheckCircle2,
  Circle,
  Loader2,
  Plus,
  RefreshCcw,
  Wand2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

export interface EstimatingPanelProps {
  className?: string;
  orgId: string;
  projectId: string;
}

interface ScenarioDraftState {
  names: Record<string, string>;
  markups: Record<string, Record<string, number>>;
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  const percentage = Math.round(value * 100);
  return `${percentage}%`;
}

function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value >= 1000 ? 0 : 2,
  }).format(value);
}

function flattenTotals(totals: Scenario["totals"], prefix = ""): Array<{ key: string; value: number }> {
  const entries: Array<{ key: string; value: number }> = [];
  for (const [key, value] of Object.entries(totals)) {
    const nextKey = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "number" && Number.isFinite(value)) {
      entries.push({ key: nextKey, value });
    } else if (value && typeof value === "object") {
      entries.push(...flattenTotals(value as Scenario["totals"], nextKey));
    }
  }
  return entries;
}

function calculateGrandTotal(totals: Scenario["totals"]): number {
  return flattenTotals(totals).reduce((acc, item) => acc + item.value, 0);
}

const EMPTY_DRAFTS: ScenarioDraftState = { names: {}, markups: {} };

export function EstimatingPanel({ className, orgId, projectId }: EstimatingPanelProps): JSX.Element {
  const [summary, setSummary] = useState<EstimatorSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mining, setMining] = useState(false);
  const [wbsUpdating, setWbsUpdating] = useState<string | null>(null);
  const [scenarioSaving, setScenarioSaving] = useState<string | null>(null);
  const [creatingScenario, setCreatingScenario] = useState(false);
  const [drafts, setDrafts] = useState<ScenarioDraftState>(EMPTY_DRAFTS);

  const syncDrafts = useCallback((scenarios: Scenario[]) => {
    setDrafts(() => {
      const nameDrafts: Record<string, string> = {};
      const markupDrafts: Record<string, Record<string, number>> = {};
      for (const scenario of scenarios) {
        nameDrafts[scenario.id] = scenario.name;
        markupDrafts[scenario.id] = { ...scenario.parameters.markups };
      }
      return { names: nameDrafts, markups: markupDrafts };
    });
  }, []);

  const loadSummary = useCallback(async () => {
    if (!orgId || !projectId) {
      setSummary(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchEstimatorSummary(orgId, projectId);
      setSummary(payload);
      syncDrafts(payload.scenarios);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to load estimator summary";
      setError(message);
      toast.error(message);
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [orgId, projectId, syncDrafts]);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  const wbsItems = useMemo(() => {
    if (!summary) {
      return [] as WbsItem[];
    }
    return [...summary.wbs].sort((a, b) => {
      if (Number.isFinite(a.sequence) && Number.isFinite(b.sequence)) {
        return a.sequence - b.sequence;
      }
      return a.code.localeCompare(b.code);
    });
  }, [summary]);

  const acceptedCount = useMemo(() => wbsItems.filter((item) => item.accepted).length, [wbsItems]);

  const handleMineScope = useCallback(async () => {
    if (!orgId || !projectId) {
      return;
    }
    setMining(true);
    setError(null);
    try {
      const mined = await mineEstimatorScope(orgId, projectId);
      setSummary((prev) => {
        const base: EstimatorSummary =
          prev ?? {
            org_id: orgId,
            project_id: projectId,
            wbs: [],
            rates: [],
            scenarios: [],
          };
        return { ...base, wbs: mined };
      });
      toast.success("Scope mining complete", {
        description: `${mined.length.toLocaleString()} activities refreshed from project files.`,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Scope mining failed";
      setError(message);
      toast.error(message);
    } finally {
      setMining(false);
    }
  }, [orgId, projectId]);

  const handleToggleAccepted = useCallback(
    async (item: WbsItem) => {
      setWbsUpdating(item.id);
      setError(null);
      try {
        const updated = await updateWbsItem(item.id, { accepted: !item.accepted });
        setSummary((prev) => {
          if (!prev) {
            return prev;
          }
          return { ...prev, wbs: prev.wbs.map((existing) => (existing.id === updated.id ? updated : existing)) };
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Unable to update WBS item";
        setError(message);
        toast.error(message);
      } finally {
        setWbsUpdating(null);
      }
    },
    [],
  );

  const handleMarkupDraftChange = useCallback(
    (scenarioId: string, markupKey: string, rawValue: string) => {
      const numeric = Number(rawValue);
      setDrafts((prev) => {
        const nextNames = { ...prev.names };
        const nextMarkups = { ...prev.markups };
        const current = { ...(nextMarkups[scenarioId] ?? {}) };
        current[markupKey] = Number.isFinite(numeric) ? numeric : 0;
        nextMarkups[scenarioId] = current;
        return { names: nextNames, markups: nextMarkups };
      });
    },
    [],
  );

  const commitScenarioUpdate = useCallback(
    async (scenarioId: string, payload: Parameters<typeof adjustEstimatorScenario>[1]) => {
      setScenarioSaving(scenarioId);
      setError(null);
      try {
        const updated = await adjustEstimatorScenario(scenarioId, payload);
        setSummary((prev) => {
          if (!prev) {
            return prev;
          }
          const scenarios = prev.scenarios.map((scenario) => (scenario.id === updated.id ? updated : scenario));
          return { ...prev, scenarios };
        });
        setDrafts((prev) => ({
          names: { ...prev.names, [updated.id]: updated.name },
          markups: { ...prev.markups, [updated.id]: { ...updated.parameters.markups } },
        }));
        toast.success("Scenario updated", { description: updated.name });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to update scenario";
        setError(message);
        toast.error(message);
      } finally {
        setScenarioSaving(null);
      }
    },
    [],
  );

  const handleScenarioNameChange = useCallback((scenarioId: string, value: string) => {
    setDrafts((prev) => ({ names: { ...prev.names, [scenarioId]: value }, markups: { ...prev.markups } }));
  }, []);

  const handleScenarioNameCommit = useCallback(
    (scenario: Scenario) => {
      const draftName = drafts.names[scenario.id]?.trim();
      const nextName = draftName || scenario.name;
      if (nextName === scenario.name) {
        setDrafts((prev) => ({
          names: { ...prev.names, [scenario.id]: scenario.name },
          markups: { ...prev.markups },
        }));
        return;
      }
      void commitScenarioUpdate(scenario.id, { name: nextName });
    },
    [commitScenarioUpdate, drafts.names],
  );

  const handleMarkupCommit = useCallback(
    (scenario: Scenario, markupKey: string) => {
      const draftMarkups = drafts.markups[scenario.id];
      const nextValue = draftMarkups?.[markupKey];
      const currentValue = scenario.parameters.markups[markupKey];
      if (nextValue === undefined || nextValue === currentValue) {
        return;
      }
      void commitScenarioUpdate(scenario.id, { parameters: { markups: { [markupKey]: nextValue } } });
    },
    [commitScenarioUpdate, drafts.markups],
  );

  const handleCreateScenario = useCallback(async () => {
    if (!orgId || !projectId) {
      return;
    }
    setCreatingScenario(true);
    setError(null);
    try {
      const existing = summary?.scenarios ?? [];
      const payload = await createEstimatorScenario({
        org_id: orgId,
        project_id: projectId,
        name: `Scenario ${existing.length + 1}`,
      });
      setSummary((prev) => {
        const base: EstimatorSummary =
          prev ?? {
            org_id: orgId,
            project_id: projectId,
            wbs: [],
            rates: [],
            scenarios: [],
          };
        return { ...base, scenarios: [...base.scenarios, payload] };
      });
      setDrafts((prev) => ({
        names: { ...prev.names, [payload.id]: payload.name },
        markups: { ...prev.markups, [payload.id]: { ...payload.parameters.markups } },
      }));
      toast.success("Scenario created", { description: payload.name });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to create scenario";
      setError(message);
      toast.error(message);
    } finally {
      setCreatingScenario(false);
    }
  }, [orgId, projectId, summary?.scenarios]);

  const scenarioCards = summary?.scenarios ?? [];
  const rateEntries = summary?.rates ?? [];

  return (
    <section className={clsx("space-y-6", className)} aria-label="Estimating workspace">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-text-primary">Estimating workspace</h3>
          <p className="text-xs text-text-secondary">
            Review mined scope, adjust markups, and compare pricing scenarios before issuing bids.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleMineScope}
            disabled={mining || !orgId || !projectId}
            className="inline-flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1.5 text-xs font-semibold text-text-secondary shadow-panel transition hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60"
          >
            {mining ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Wand2 className="h-3.5 w-3.5" aria-hidden />}
            Mine scope
          </button>
          <button
            type="button"
            onClick={() => void loadSummary()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1.5 text-xs font-semibold text-text-secondary shadow-panel transition hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <RefreshCcw className="h-3.5 w-3.5" aria-hidden />
            )}
            Refresh
          </button>
          <button
            type="button"
            onClick={handleCreateScenario}
            disabled={creatingScenario}
            className="inline-flex items-center gap-2 rounded-full bg-accent px-4 py-1.5 text-xs font-semibold text-accent-contrast shadow-panel transition hover:bg-accent-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {creatingScenario ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Plus className="h-3.5 w-3.5" aria-hidden />}
            New scenario
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-xl border border-danger-soft bg-danger-soft-10 px-4 py-3 text-sm text-danger">{error}</div>
      ) : null}

      {loading && !summary ? (
        <div className="flex items-center gap-3 rounded-xl border border-border-subtle bg-surface px-4 py-6 text-sm text-text-secondary">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading estimator data
        </div>
      ) : null}

      {!loading && !summary ? (
        <div className="rounded-xl border border-border-subtle bg-surface px-4 py-6 text-sm text-text-secondary">
          Provide a valid organization and project to view estimating data.
        </div>
      ) : null}

      {summary ? (
        <div className="space-y-6">
          <section className="rounded-xl border border-border-subtle bg-surface shadow-panel" aria-label="Scope breakdown">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle px-5 py-4">
              <div>
                <h4 className="text-sm font-semibold text-text-primary">Work breakdown structure</h4>
                <p className="text-xs text-text-secondary">
                  {acceptedCount.toLocaleString()} of {wbsItems.length.toLocaleString()} activities accepted for estimating.
                </p>
              </div>
            </header>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-border-subtle text-left text-sm">
                <thead className="bg-surface-muted text-xs uppercase tracking-wide text-text-tertiary">
                  <tr>
                    <th scope="col" className="px-5 py-3 font-semibold">Code</th>
                    <th scope="col" className="px-5 py-3 font-semibold">Description</th>
                    <th scope="col" className="px-5 py-3 font-semibold">Confidence</th>
                    <th scope="col" className="px-5 py-3 font-semibold">Accepted</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {wbsItems.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-5 py-6 text-center text-sm text-text-secondary">
                        No scope items available. Run scope mining to populate the estimator.
                      </td>
                    </tr>
                  ) : (
                    wbsItems.map((item) => {
                      const isUpdating = wbsUpdating === item.id;
                      return (
                        <tr key={item.id} className="align-top">
                          <td className="px-5 py-4 text-xs font-semibold uppercase tracking-wide text-text-tertiary">
                            {item.code || "—"}
                          </td>
                          <td className="px-5 py-4">
                            <div className="text-sm font-medium text-text-primary">{item.description}</div>
                            <div className="mt-1 text-xs text-text-secondary">Sequence {item.sequence}</div>
                          </td>
                          <td className="px-5 py-4">
                            <span className="inline-flex items-center rounded-full bg-surface-inset px-2.5 py-0.5 text-xs font-medium text-text-secondary">
                              {formatPercent(item.confidence)}
                            </span>
                          </td>
                          <td className="px-5 py-4">
                            <button
                              type="button"
                              onClick={() => void handleToggleAccepted(item)}
                              disabled={isUpdating}
                              className="inline-flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1 text-xs font-medium text-text-secondary shadow-panel transition hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {item.accepted ? (
                                <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
                              ) : (
                                <Circle className="h-4 w-4 text-text-tertiary" aria-hidden />
                              )}
                              {isUpdating ? "Saving" : item.accepted ? "Accepted" : "Review"}
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="space-y-4" aria-label="Scenario planning">
            <header className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h4 className="text-sm font-semibold text-text-primary">Pricing scenarios</h4>
                <p className="text-xs text-text-secondary">Adjust markups to compare bid-ready totals.</p>
              </div>
            </header>
            {scenarioCards.length === 0 ? (
              <div className="rounded-xl border border-border-subtle bg-surface px-4 py-6 text-sm text-text-secondary">
                No scenarios available. Create a new scenario to begin estimating.
              </div>
            ) : (
              <div className="grid gap-5 lg:grid-cols-2">
                {scenarioCards.map((scenario) => {
                  const markupDraft = drafts.markups[scenario.id] ?? scenario.parameters.markups;
                  const nameDraft = drafts.names[scenario.id] ?? scenario.name;
                  const totals = flattenTotals(scenario.totals);
                  const grandTotal = calculateGrandTotal(scenario.totals);
                  const isSaving = scenarioSaving === scenario.id;
                  return (
                    <article
                      key={scenario.id}
                      className="flex flex-col gap-4 rounded-xl border border-border-subtle bg-surface shadow-panel"
                    >
                      <div className="flex flex-col gap-3 border-b border-border-subtle px-5 py-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1">
                            <label className="text-xs font-semibold uppercase tracking-wide text-text-tertiary" htmlFor={`scenario-${scenario.id}`}>
                              Scenario name
                            </label>
                            <input
                              id={`scenario-${scenario.id}`}
                              value={nameDraft}
                              onChange={(event) => handleScenarioNameChange(scenario.id, event.target.value)}
                              onBlur={() => handleScenarioNameCommit(scenario)}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                  event.currentTarget.blur();
                                }
                              }}
                              className="mt-1 w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm font-semibold text-text-primary shadow-panel focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent-30"
                            />
                          </div>
                          <div className="text-right">
                            <div className="text-xs font-semibold uppercase tracking-wide text-text-tertiary">Grand total</div>
                            <div className="text-base font-semibold text-text-primary">{formatCurrency(grandTotal)}</div>
                          </div>
                        </div>
                        {isSaving ? (
                          <div className="flex items-center gap-2 text-xs text-text-secondary">
                            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Saving updates
                          </div>
                        ) : null}
                      </div>
                      <div className="grid gap-4 px-5 pb-5">
                        <div className="space-y-3">
                          <h5 className="text-xs font-semibold uppercase tracking-wide text-text-tertiary">Markups</h5>
                          <div className="space-y-3">
                            {Object.keys(markupDraft).length === 0 ? (
                              <p className="rounded-lg border border-border-subtle bg-surface px-3 py-2 text-xs text-text-secondary">
                                No markups defined for this scenario.
                              </p>
                            ) : (
                              Object.entries(markupDraft).map(([key, value]) => (
                                <div key={key} className="flex items-center justify-between gap-3">
                                  <label className="text-sm font-medium text-text-primary" htmlFor={`markup-${scenario.id}-${key}`}>
                                    {key.replace(/_/g, " ")}
                                  </label>
                                  <div className="flex items-center gap-2">
                                    <input
                                      id={`markup-${scenario.id}-${key}`}
                                      type="number"
                                      value={value}
                                      onChange={(event) => handleMarkupDraftChange(scenario.id, key, event.target.value)}
                                      onBlur={() => handleMarkupCommit(scenario, key)}
                                      onKeyDown={(event) => {
                                        if (event.key === "Enter") {
                                          event.currentTarget.blur();
                                        }
                                      }}
                                      step={0.1}
                                      className="w-24 rounded-lg border border-border-subtle bg-surface px-2 py-1 text-right text-sm text-text-primary shadow-panel focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent-30"
                                    />
                                    <span className="text-xs text-text-secondary">%</span>
                                  </div>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                        <div className="space-y-3">
                          <h5 className="text-xs font-semibold uppercase tracking-wide text-text-tertiary">Totals</h5>
                          <div className="space-y-2">
                            {totals.length === 0 ? (
                              <p className="rounded-lg border border-border-subtle bg-surface px-3 py-2 text-xs text-text-secondary">
                                Totals unavailable for this scenario.
                              </p>
                            ) : (
                              totals.map((entry) => (
                                <div key={entry.key} className="flex items-center justify-between gap-3 text-sm">
                                  <span className="text-text-secondary">{entry.key.replace(/\./g, " › ")}</span>
                                  <span className="font-semibold text-text-primary">{formatCurrency(entry.value)}</span>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section className="rounded-xl border border-border-subtle bg-surface shadow-panel" aria-label="Rate reference">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle px-5 py-4">
              <div>
                <h4 className="text-sm font-semibold text-text-primary">Crew and trade rates</h4>
                <p className="text-xs text-text-secondary">
                  Baseline labor and material assumptions pulled from the estimating library.
                </p>
              </div>
            </header>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-border-subtle text-left text-sm">
                <thead className="bg-surface-muted text-xs uppercase tracking-wide text-text-tertiary">
                  <tr>
                    <th scope="col" className="px-5 py-3 font-semibold">Category</th>
                    <th scope="col" className="px-5 py-3 font-semibold">CSI</th>
                    <th scope="col" className="px-5 py-3 font-semibold">Base rate</th>
                    <th scope="col" className="px-5 py-3 font-semibold">Range</th>
                    <th scope="col" className="px-5 py-3 font-semibold">Confidence</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {rateEntries.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-5 py-6 text-center text-sm text-text-secondary">
                        Rate library not available. Confirm estimator services are online.
                      </td>
                    </tr>
                  ) : (
                    rateEntries.map((rate) => (
                      <tr key={rate.id}>
                        <td className="px-5 py-4">
                          <div className="text-sm font-medium text-text-primary">{rate.category}</div>
                          <div className="text-xs text-text-secondary">{rate.metadata?.region ?? "Standard region"}</div>
                        </td>
                        <td className="px-5 py-4 text-xs font-semibold uppercase tracking-wide text-text-tertiary">
                          {rate.csi_code || "—"}
                        </td>
                        <td className="px-5 py-4 font-semibold text-text-primary">{formatCurrency(rate.base_rate)}</td>
                        <td className="px-5 py-4 text-sm text-text-secondary">
                          {formatCurrency(rate.low_rate)} – {formatCurrency(rate.high_rate)}
                        </td>
                        <td className="px-5 py-4">
                          <span className="inline-flex items-center rounded-full bg-surface-inset px-2.5 py-0.5 text-xs font-medium text-text-secondary">
                            {formatPercent(rate.confidence)}
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
