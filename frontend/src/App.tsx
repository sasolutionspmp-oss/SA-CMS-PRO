import { Dialog, Transition } from "@headlessui/react";



import clsx from "clsx";



import {



  ArrowUpRight,



  ClipboardList,



  Download,



  Filter,



  Inbox,



  LayoutDashboard,



  LineChart,



  Loader2,



  Moon,



  RefreshCcw,



  Search,



  ShieldCheck,



  Sun,



  Users,



} from "lucide-react";



import { Fragment, useEffect, useMemo, useState } from "react";



import { Toaster, toast } from "sonner";



import { AppShell, type AppShellNavItem } from "./components/shell/AppShell";



import { UploadPanel } from "./components/upload/UploadPanel";



import { EstimatingPanel } from "./components/estimating/EstimatingPanel";
import { useFallbackTelemetry } from "./hooks/useFallbackTelemetry";



import {



  downloadExport,



  fetchBootstrap,



  fetchIntakeStatus,



  getStoredTokens,



  launchIntake,



  login,



  type BootstrapResponse,



  type IntakeFileItem,



  type IntakeRunSummary,



} from "./api";







const POLL_INTERVAL = 1500;







type StatusFilter = "all" | "pending" | "parsed" | "failed";







type ThemeMode = "light" | "dark";







type ModuleKey = "dashboard" | "intake" | "estimating" | "crm" | "compliance" | "operations";







interface ModuleMeta {



  label: string;



  description: string;



  icon: JSX.Element;



  placeholderTitle?: string;



  placeholderBody?: string;



  defaultBadge?: string;



}







const MODULES: Record<ModuleKey, ModuleMeta> = {



  dashboard: {



    label: "Dashboard",



    description: "Executive overview and KPIs",



    icon: <LayoutDashboard className="h-4 w-4" aria-hidden />,



    placeholderTitle: "Dashboard coming soon",



    placeholderBody: "The executive dashboard will compile bid, intake, and risk summaries once data feeds are online.",



    defaultBadge: "Soon",



  },



  intake: {



    label: "Intake Control",



    description: "Document ingestion and parsing pipeline",



    icon: <Inbox className="h-4 w-4" aria-hidden />,



    placeholderTitle: "Intake workspace active",



    placeholderBody: "Launch parsing runs, monitor progress, and prep downstream exports from this surface.",



    defaultBadge: "Live",



  },



  estimating: {



    label: "Estimating",



    description: "Scenario planning and cost models",



    icon: <LineChart className="h-4 w-4" aria-hidden />,



    placeholderTitle: "Estimating workspace queued",



    placeholderBody: "Cost models, pricing grids, and export workflows land here after pipeline wiring.",



    defaultBadge: "Soon",



  },



  crm: {



    label: "CRM",



    description: "Pipeline, pursuits, and stakeholder intel",



    icon: <Users className="h-4 w-4" aria-hidden />,



    placeholderTitle: "CRM board scheduled",



    placeholderBody: "Deal kanban, pursuit health, and notifications will fill this space in the next backlog pass.",



    defaultBadge: "Soon",



  },



  compliance: {



    label: "Compliance",



    description: "QA requirements and document readiness",



    icon: <ShieldCheck className="h-4 w-4" aria-hidden />,



    placeholderTitle: "Compliance center in design",



    placeholderBody: "Compliance tasks, QA templates, and approvals wire up once ingestion feeds structured data.",



    defaultBadge: "Soon",



  },



  operations: {



    label: "Operations",



    description: "Field execution and coordinator tools",



    icon: <ClipboardList className="h-4 w-4" aria-hidden />,



    placeholderTitle: "Operations hub planned",



    placeholderBody: "Scheduling, logistics, and performance tracking arrive after integration work completes.",



    defaultBadge: "Soon",



  },



};







const DEFAULT_ORG_PROFILE = {



  name: "Signal Advantage Construction",



  code: "ORG-SA-CMS",



};







const DEFAULT_PROJECT_PROFILE = {



  name: "Science Annex Modernization",



  code: "FW-4821",



  stage: "Planning",



};







const DEFAULT_USER_PROFILE = {



  name: "Jordan Matthews",



  title: "Program Director",



  initials: "JM",



};







const DEFAULT_ORG_ID = "default";







const DEMO_USERNAME = import.meta.env.VITE_DEMO_USERNAME ?? "demo_owner";



const DEMO_PASSWORD = import.meta.env.VITE_DEMO_PASSWORD ?? "DemoOwner123$";



const DEMO_ORG_ID = import.meta.env.VITE_DEMO_ORG ?? undefined;



function toInitials(value: string): string {
  if (!value) {
    return "SA";
  }
  const parts = value.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return value.slice(0, 2).toUpperCase();
  }
  const initials = parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
  return initials || value.slice(0, 2).toUpperCase();
}

function formatStage(status?: string | null): string {



  if (!status) {



    return "Intake staging";



  }



  switch (status) {



    case "ready":



      return "Ready for analysis";



    case "parsing":



      return "Parsing in progress";



    case "failed":



      return "Attention required";



    case "staging":



      return "Document staging";



    default:



      return status;



  }



}







function useTheme(): [ThemeMode, () => void] {



  const [theme, setTheme] = useState<ThemeMode>(() => {



    const stored = window.localStorage.getItem("sa-theme");



    if (stored === "light" || stored === "dark") {



      return stored;



    }



    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";



  });







  useEffect(() => {



    const root = document.documentElement;



    root.classList.toggle("dark", theme === "dark");



    window.localStorage.setItem("sa-theme", theme);



  }, [theme]);







  const toggle = () => setTheme((prev) => (prev === "dark" ? "light" : "dark"));



  return [theme, toggle];



}







function statusBadgeColor(status: IntakeFileItem["parsed_status"]): string {



  switch (status) {



    case "parsed":



      return "bg-success-soft text-success";



    case "failed":



      return "bg-danger-soft text-danger";



    case "pending":



    default:



      return "bg-warning-soft text-warning";



  }



}







function runStateChip(status: string): string {



  switch (status) {



    case "ready":



      return "bg-success-soft text-success";



    case "failed":



      return "bg-danger-soft text-danger";



    case "parsing":



    case "staging":



      return "bg-warning-soft text-warning";



    default:



      return "bg-surface-muted text-text-tertiary";



  }



}







function filteredItems(items: IntakeFileItem[], filter: StatusFilter, search: string): IntakeFileItem[] {



  return items.filter((item) => {



    const matchesFilter = filter === "all" || item.parsed_status === filter;



    const matchesSearch = search



      ? [item.rel_path, item.snippet ?? "", item.metadata ? JSON.stringify(item.metadata) : ""]



          .join(" ")



          .toLowerCase()



          .includes(search.toLowerCase())



      : true;



    return matchesFilter && matchesSearch;



  });



}







function saveBlob(blob: Blob, filename: string) {



  const url = window.URL.createObjectURL(blob);



  const a = document.createElement("a");



  a.href = url;



  a.download = filename;



  a.click();



  window.URL.revokeObjectURL(url);



}







const statusMessages: Record<string, string> = {



  staging: "Preparing intake run...",



  parsing: "Parsing documents...",



  ready: "Run complete",



  failed: "Run has failures",



};







function statusProgress(run: IntakeRunSummary | null): number {



  if (!run || run.total === 0) return 0;



  const processed = run.parsed + run.failed;



  return Math.min(100, Math.round((processed / run.total) * 100));



}







const panelBase = "rounded-2xl border border-border-subtle bg-surface-elevated shadow-panel";



export default function App(): JSX.Element {



  const [theme, toggleTheme] = useTheme();



  const [projectId, setProjectId] = useState("");



  const [zipPath, setZipPath] = useState("");



  const [run, setRun] = useState<IntakeRunSummary | null>(null);
  const telemetry = useFallbackTelemetry();



  const [isLaunching, setIsLaunching] = useState(false);



  const [polling, setPolling] = useState(false);



  const [error, setError] = useState<string | null>(null);



  const [filter, setFilter] = useState<StatusFilter>("all");



  const [search, setSearch] = useState("");



  const [drawerOpen, setDrawerOpen] = useState(false);



  const [selectedItem, setSelectedItem] = useState<IntakeFileItem | null>(null);

  const [activeModule, setActiveModule] = useState<ModuleKey>("intake");
  const [bootstrapData, setBootstrapData] = useState<BootstrapResponse | null>(null);
  const [bootstrapLoading, setBootstrapLoading] = useState(true);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [workspaceOrg, setWorkspaceOrg] = useState(DEFAULT_ORG_PROFILE);
  const [workspaceProject, setWorkspaceProject] = useState(DEFAULT_PROJECT_PROFILE);
  const [userProfile, setUserProfile] = useState(DEFAULT_USER_PROFILE);
  const [activeOrgId, setActiveOrgId] = useState<string>(DEFAULT_ORG_ID);

  useEffect(() => {
    let cancelled = false;

    async function hydrateBootstrap() {
      try {
        setBootstrapLoading(true);
        setBootstrapError(null);

        if (!getStoredTokens()) {
          await login(DEMO_USERNAME, DEMO_PASSWORD, DEMO_ORG_ID);
        }

        const payload = await fetchBootstrap();
        if (cancelled) {
          return;
        }

        setBootstrapData(payload);

        const displayName = (payload.user.full_name && payload.user.full_name.trim()) || payload.user.username;
        const displayTitle = payload.user.roles[0] ?? "Operator";

        setUserProfile({
          name: displayName,
          title: displayTitle,
          initials: toInitials(displayName),
        });

        const resolvedOrg =
          payload.orgs.find((org) => org.id === payload.user.active_org_id) ?? payload.orgs[0];

        if (resolvedOrg) {
          setActiveOrgId(resolvedOrg.id);
          setWorkspaceOrg({
            name: resolvedOrg.name,
            code: (resolvedOrg.slug || resolvedOrg.id || DEFAULT_ORG_PROFILE.code).toUpperCase()
          });

          const resolvedProject =
            payload.active_project ??
            resolvedOrg.projects.find((project) => project.status !== "archived") ??
            resolvedOrg.projects[0];

          if (resolvedProject) {
            setWorkspaceProject({
              name: resolvedProject.name,
              code: resolvedProject.code,
              stage: resolvedProject.stage ?? resolvedProject.status ?? DEFAULT_PROJECT_PROFILE.stage,
            });
          }
        }
      } catch (error) {
        console.error("Bootstrap hydrate failed", error);
        if (!cancelled) {
          setBootstrapError(error instanceof Error ? error.message : "Unable to reach the platform API");
        }
      } finally {
        if (!cancelled) {
          setBootstrapLoading(false);
        }
      }
    }

    hydrateBootstrap();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!projectId && workspaceProject.code) {
      setProjectId(workspaceProject.code);
    }
  }, [projectId, workspaceProject.code]);

  useEffect(() => {



    if (!run) return;



    if (run.pending === 0) {



      setPolling(false);



      return;



    }



    setPolling(true);



    const interval = window.setInterval(async () => {



      try {



        const next = await fetchIntakeStatus(run.run_id);



        setRun(next);



        if (next.pending === 0) {



          setPolling(false);



        }



      } catch (err) {



        console.error(err);



        setPolling(false);



        toast.error("Unable to refresh intake status");



      }



    }, POLL_INTERVAL);



    return () => window.clearInterval(interval);



  }, [run?.run_id]);







  const handleLaunch = async () => {



    if (!projectId || !zipPath) {



      setError("Project ID and ZIP path are required");



      return;



    }



    try {



      setIsLaunching(true);



      setError(null);



      if (!getStoredTokens()) {



        await login(DEMO_USERNAME, DEMO_PASSWORD, DEMO_ORG_ID);



      }



      const summary = await launchIntake(projectId, zipPath);



      setRun(summary);



      setActiveModule("intake");



      toast.success(`Intake launched for ${projectId}`);



    } catch (err: unknown) {



      console.error(err);



      const message = err instanceof Error ? err.message : "Failed to launch intake";



      setError(message);



      toast.error(message);



    } finally {



      setIsLaunching(false);



    }



  };







  const handleExport = async (kind: "pdf" | "docx" | "xlsx") => {



    if (!run) return;



    try {



      const blob = await downloadExport(run.project_id, kind);



      saveBlob(blob, `${run.project_id}_intake.${kind}`);



      toast.success(`${kind.toUpperCase()} export ready`);



    } catch (err) {



      const message = err instanceof Error ? err.message : "Export failed";



      toast.error(message);



    }



  };







  const runStatusMessage = run ? statusMessages[run.status] ?? run.status : "Waiting for intake";







  const items = useMemo(() => (run ? filteredItems(run.items, filter, search) : []), [run, filter, search]);







  const canAdvance = run && run.pending === 0 && run.failed === 0;



  const hasFailures = run && run.failed > 0;







  const navItems = useMemo<AppShellNavItem[]>(() => {



    return (Object.entries(MODULES) as [ModuleKey, ModuleMeta][]).map(([key, meta]) => {



      const item: AppShellNavItem = {



        id: key,



        label: meta.label,



        description: meta.description,



        icon: meta.icon,



        badge: meta.defaultBadge,



      };



      if (key === "intake") {



        if (run) {



          const remaining = run.pending;



          item.badge = remaining > 0 ? `${remaining} pending` : `${run.parsed}/${run.total}`;



          if (run.status === "ready") {



            item.tone = "success";



          } else if (run.status === "failed") {



            item.tone = "danger";



          } else if (run.status === "parsing" || run.status === "staging") {



            item.tone = "warning";



          }



        } else {



          item.badge = meta.defaultBadge;



        }

        if (telemetry.fallback_events > 0) {
          const fallbackCount = telemetry.fallback_events;
          item.badge = `${fallbackCount} fallback${fallbackCount === 1 ? "" : "s"}`;
          item.tone = "danger";
        }



      }



      return item;



    });



  }, [run, telemetry.fallback_events, telemetry.last_event_at]);







  const projectProfile = useMemo(() => {



    const stage = run ? formatStage(run.status) : workspaceProject.stage;



    return { ...workspaceProject, stage };



  }, [run?.status, workspaceProject]);







  const handleSelectModule = (id: string) => {



    if (Object.prototype.hasOwnProperty.call(MODULES, id)) {



      setActiveModule(id as ModuleKey);



    }



  };



  const placeholderView = (module: ModuleMeta) => (



    <section className={clsx(panelBase, "p-10")} aria-label={`${module.label} placeholder`}>



      <h2 className="text-lg font-semibold text-text-primary">{module.placeholderTitle}</h2>



      <p className="mt-2 text-sm text-text-secondary">{module.placeholderBody}</p>



      <div className="mt-6 rounded-xl border border-dashed border-border-subtle bg-surface-muted p-6 text-left text-sm text-text-secondary">



        The production shell is wired and ready. Populate this module once its backend endpoints are available.



      </div>



    </section>



  );







  const bootstrapBanner = bootstrapError ? (



    <div className="rounded-xl border border-danger-soft bg-danger-soft-10 px-4 py-3 text-sm text-danger">



      Unable to reach the platform API. Working with local defaults.



    </div>



  ) : null;







const intakeView = (



    <div className="space-y-8">



      {bootstrapBanner}



      <section className={clsx(panelBase, "transition")} aria-label="Launch Intake">



        <div className="flex flex-col gap-6 p-6 md:flex-row md:items-start md:justify-between">



          <div className="flex-1 space-y-3">



            <h2 className="text-lg font-semibold text-text-primary">Launch Intake</h2>



            <p className="text-sm text-text-secondary">



              Provide a project identifier and the absolute ZIP path containing bid documents. The service copies and indexes files into the secure data staging area.



            </p>



            <div className="grid gap-4 md:grid-cols-2">



              <div className="space-y-2">



                <label className="text-sm font-medium text-text-primary" htmlFor="project">



                  Project ID



                </label>



                <input



                  id="project"



                  className="w-full rounded-lg border border-border-subtle bg-surface-elevated px-3 py-2 text-sm shadow-panel focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent-40"



                  value={projectId}



                  onChange={(event) => setProjectId(event.target.value)}



                  placeholder="ACME-SITE-2025"



                />



              </div>



              <div className="space-y-2">



                <label className="text-sm font-medium text-text-primary" htmlFor="zippath">



                  ZIP path



                </label>



                <input



                  id="zippath"



                  className="w-full rounded-lg border border-border-subtle bg-surface-elevated px-3 py-2 text-sm shadow-panel focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent-40"



                  value={zipPath}



                  onChange={(event) => setZipPath(event.target.value)}



                  placeholder="C:/Projects/Acme/intake_bundle.zip"



                />



              </div>



            </div>



            {error ? <p className="text-sm text-danger">{error}</p> : null}



            <div className="flex flex-wrap items-center gap-3">



              <button



                type="button"



                onClick={handleLaunch}



                disabled={isLaunching || polling}



                className="inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2 text-sm font-semibold text-accent-contrast shadow-panel transition hover:bg-accent-90 focus:outline-none focus:ring-2 focus:ring-accent-50 disabled:cursor-not-allowed disabled:opacity-60"



              >



                {isLaunching ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUpRight className="h-4 w-4" />}



                Launch Intake



              </button>



              {polling ? (



                <span className="inline-flex items-center gap-2 rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-accent">



                  <Loader2 className="h-3 w-3 animate-spin" /> monitoring status



                </span>



              ) : null}



              {run ? (



                <span className={clsx("inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium", runStateChip(run.status))}>



                  {runStatusMessage}



                </span>



              ) : null}



            </div>



          </div>



          <div className="w-full max-w-xs space-y-4">



            <div className="rounded-xl border border-border-subtle bg-surface-muted p-4 text-sm shadow-panel">



              <div className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-text-secondary">



                Progress



                <span>{statusProgress(run)}%</span>



              </div>



              <div className="h-2 rounded-full bg-surface-inset">



                <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${statusProgress(run)}%` }} />



              </div>



              {run ? (



                <dl className="mt-3 grid grid-cols-3 gap-3 text-center text-xs">



                  <div>



                    <dt className="text-text-secondary">Total</dt>



                    <dd className="font-semibold text-text-primary">{run.total}</dd>



                  </div>



                  <div>



                    <dt className="text-text-secondary">Parsed</dt>



                    <dd className="font-semibold text-success">{run.parsed}</dd>



                  </div>



                  <div>



                    <dt className="text-text-secondary">Failed</dt>



                    <dd className="font-semibold text-danger">{run.failed}</dd>



                  </div>



                </dl>



              ) : (



                <p className="mt-3 text-xs text-text-secondary">Intake progress appears here once a run starts.</p>



              )}



            </div>



            <div className="rounded-xl border border-border-subtle bg-surface-elevated p-4 text-xs shadow-panel">



              <p className="font-semibold text-text-primary">Launch checklist</p>



              <ul className="mt-2 space-y-1 text-text-secondary">



                <li>1. Confirm bundle paths on the secure share</li>



                <li>2. Stage project metadata in CMS</li>



                <li>3. Kick off parsing and monitor alerts</li>



              </ul>



            </div>



          </div>



        </div>



      </section>



      <UploadPanel className={panelBase} projectId={projectProfile.code} />







      {run ? (



        <section className={panelBase} aria-label="Parsed documents">



          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle px-6 py-4 text-sm">



            <div className="flex items-center gap-3">



              <span className="font-semibold text-text-primary">Parsed documents</span>



              <span className="rounded-full bg-surface px-2 py-0.5 text-xs text-text-secondary">{run.total} files</span>



            </div>



            <div className="flex flex-wrap items-center gap-2">



              <div className="flex items-center gap-1 text-xs text-text-secondary">



                <span className="h-2 w-2 rounded-full bg-success" aria-hidden /> parsed



                <span className="h-2 w-2 rounded-full bg-warning" aria-hidden /> pending



                <span className="h-2 w-2 rounded-full bg-danger" aria-hidden /> failed



              </div>



              <div className="flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1 text-xs shadow-panel">



                <Search className="h-4 w-4 text-text-tertiary" />



                <input



                  className="w-40 bg-transparent text-xs focus:outline-none"



                  placeholder="Search files"



                  value={search}



                  onChange={(event) => setSearch(event.target.value)}



                />



              </div>



              <div className="flex gap-2">



                {[



                  { id: "all", label: "All" },



                  { id: "parsed", label: "Parsed" },



                  { id: "pending", label: "Pending" },



                  { id: "failed", label: "Failed" },



                ].map((option) => (



                  <button



                    key={option.id}



                    type="button"



                    onClick={() => setFilter(option.id as StatusFilter)}



                    className={clsx(



                      "rounded-full px-3 py-1 text-xs font-semibold transition",



                      filter === option.id



                        ? "bg-accent text-accent-contrast"



                        : "border border-border-subtle bg-surface text-text-secondary hover:bg-surface-muted"



                    )}



                  >



                    {option.label}



                  </button>



                ))}



              </div>



              <div className="flex gap-2">



                <button



                  type="button"



                  onClick={() => handleExport("pdf")}



                  disabled={!run || run.pending > 0}



                  className="inline-flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1 text-xs font-medium shadow-panel transition hover:bg-surface-muted disabled:opacity-50"



                >



                  <Download className="h-3.5 w-3.5" /> PDF



                </button>



                <button



                  type="button"



                  onClick={() => handleExport("docx")}



                  disabled={!run || run.pending > 0}



                  className="inline-flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1 text-xs font-medium shadow-panel transition hover:bg-surface-muted disabled:opacity-50"



                >



                  <Download className="h-3.5 w-3.5" /> DOCX



                </button>



                <button



                  type="button"



                  onClick={() => handleExport("xlsx")}



                  disabled={!run || run.pending > 0}



                  className="inline-flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1 text-xs font-medium shadow-panel transition hover:bg-surface-muted disabled:opacity-50"



                >



                  <Download className="h-3.5 w-3.5" /> XLSX



                </button>



              </div>



              <button



                type="button"



                onClick={() => toast.info("Failures review stub - hook to remediation workflow.")}



                disabled={!hasFailures}



                className="inline-flex items-center gap-2 rounded-full border border-danger-soft bg-danger-soft-70 px-3 py-1 text-xs font-medium text-danger shadow-panel transition hover:bg-danger-soft disabled:opacity-50"



              >



                <Filter className="h-3.5 w-3.5" /> Review failures



              </button>



            </div>



          </div>



          <div className="px-6 pb-6">



            <div className="overflow-hidden rounded-xl border border-border-subtle">



              <table className="min-w-full divide-y divide-border-subtle text-sm">



                <thead className="bg-surface-muted">



                  <tr>



                    <th className="px-4 py-2 text-left font-semibold text-text-secondary">File</th>



                    <th className="px-4 py-2 text-left font-semibold text-text-secondary">Status</th>



                    <th className="px-4 py-2 text-left font-semibold text-text-secondary">Size</th>



                    <th className="px-4 py-2 text-left font-semibold text-text-secondary">Updated</th>



                  </tr>



                </thead>



                <tbody className="divide-y divide-border-subtle">



                  {items.length === 0 ? (



                    <tr>



                      <td className="px-4 py-6 text-center text-text-secondary" colSpan={4}>



                        No files match the current filters.



                      </td>



                    </tr>



                  ) : (



                    items.map((item) => (



                      <tr



                        key={item.id}



                        className="cursor-pointer transition hover:bg-surface-muted"



                        onClick={() => {



                          setSelectedItem(item);



                          setDrawerOpen(true);



                        }}



                      >



                        <td className="px-4 py-3 font-medium text-text-primary">{item.rel_path}</td>



                        <td className="px-4 py-3">



                          <span className={clsx("inline-flex rounded-full px-2.5 py-1 text-xs font-semibold", statusBadgeColor(item.parsed_status))}>



                            {item.parsed_status}



                          </span>



                        </td>



                        <td className="px-4 py-3 text-text-secondary">{formatBytes(item.size)}</td>



                        <td className="px-4 py-3 text-xs text-text-tertiary">



                          {new Date(item.updated_at).toLocaleString()}



                        </td>



                      </tr>



                    ))



                  )}



                </tbody>



              </table>



            </div>



          </div>



          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle px-6 py-4 text-sm">



            <div className="text-text-secondary">



              {items.length} item{items.length === 1 ? "" : "s"} shown of {run.total} indexed overall



            </div>



            <div className="flex items-center gap-3">



              <button



                type="button"



                onClick={() => toast.info("Retrying failed parses (stub)")}



                className="inline-flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1 text-xs font-medium shadow-panel transition hover:bg-surface-muted"



              >



                <RefreshCcw className="h-3.5 w-3.5" /> Retry failed



              </button>



              <button



                type="button"



                disabled={!canAdvance}



                onClick={() => toast.success("Stage advanced to analysis")}



                className="inline-flex items-center gap-2 rounded-full bg-success px-4 py-2 text-xs font-semibold text-accent-contrast shadow-panel transition hover:bg-success-90 disabled:cursor-not-allowed disabled:opacity-50"



              >



                Advance Stage



              </button>



            </div>



          </div>



        </section>



      ) : (



        <section className={clsx(panelBase, "border-dashed border-2 bg-surface-muted p-10 text-center text-sm text-text-secondary")}



          aria-label="Empty state">



          Launch an intake run to populate parsed documents, track progress, and enable exports.



        </section>



      )}



      <Transition show={drawerOpen} as={Fragment}>



        <Dialog as="div" className="relative z-50" onClose={() => setDrawerOpen(false)}>



          <Transition.Child



            as={Fragment}



            enter="ease-out duration-150"



            enterFrom="opacity-0"



            enterTo="opacity-100"



            leave="ease-in duration-100"



            leaveFrom="opacity-100"



            leaveTo="opacity-0"



          >



            <div className="fixed inset-0 bg-surface-inset-soft" />



          </Transition.Child>







          <div className="fixed inset-0 overflow-hidden">



            <div className="absolute inset-y-0 right-0 flex max-w-full pl-10">



              <Transition.Child



                as={Fragment}



                enter="transform transition ease-in-out duration-200"



                enterFrom="translate-x-full"



                enterTo="translate-x-0"



                leave="transform transition ease-in-out duration-200"



                leaveFrom="translate-x-0"



                leaveTo="translate-x-full"



              >



                <Dialog.Panel className="w-screen max-w-md border-l border-border-subtle bg-surface-elevated shadow-panel">



                  <div className="flex items-center justify-between border-b border-border-subtle px-6 py-4">



                    <Dialog.Title className="text-sm font-semibold text-text-primary">



                      File details



                    </Dialog.Title>



                    <button



                      type="button"



                      onClick={() => setDrawerOpen(false)}



                      className="rounded-full border border-border-subtle bg-surface px-2 py-1 text-xs font-medium text-text-secondary shadow-panel transition hover:bg-surface-muted"



                    >



                      Close



                    </button>



                  </div>



                  <div className="space-y-4 px-6 py-4 text-sm text-text-secondary">



                    <div>



                      <div className="text-xs font-semibold uppercase text-text-tertiary">Path</div>



                      <div className="break-all font-medium text-text-primary">{selectedItem?.rel_path}</div>



                    </div>



                    <div className="grid grid-cols-2 gap-4 text-xs">



                      <div>



                        <div className="text-text-tertiary">Status</div>



                        <div className="font-semibold text-text-primary">{selectedItem?.parsed_status}</div>



                      </div>



                      <div>



                        <div className="text-text-tertiary">Size</div>



                        <div className="font-semibold text-text-primary">{selectedItem ? formatBytes(selectedItem.size) : "-"}</div>



                      </div>



                      <div>



                        <div className="text-text-tertiary">Updated</div>



                        <div className="font-semibold text-text-primary">



                          {selectedItem ? new Date(selectedItem.updated_at).toLocaleString() : "-"}



                        </div>



                      </div>



                      <div>



                        <div className="text-text-tertiary">Checksum</div>



                        <div className="break-all font-semibold text-text-primary">{selectedItem?.checksum ?? "-"}</div>



                      </div>



                    </div>



                    {selectedItem?.error ? (



                      <div className="rounded-lg border border-danger-soft bg-danger-soft-70 p-3 text-danger">



                        {selectedItem.error}



                      </div>



                    ) : null}



                    <div>



                      <div className="text-xs font-semibold uppercase text-text-tertiary">Snippet</div>



                      <pre className="mt-1 max-h-60 overflow-auto rounded-lg border border-border-subtle bg-surface p-3 text-xs text-text-secondary">



                        {selectedItem?.snippet ?? "No preview available"}



                      </pre>



                    </div>



                    {selectedItem?.metadata ? (



                      <div>



                        <div className="text-xs font-semibold uppercase text-text-tertiary">Metadata</div>



                        <pre className="mt-1 max-h-48 overflow-auto rounded-lg border border-border-subtle bg-surface p-3 text-xs text-text-secondary">



                          {JSON.stringify(selectedItem.metadata, null, 2)}



                        </pre>



                      </div>



                    ) : null}



                  </div>



                </Dialog.Panel>



              </Transition.Child>



            </div>



          </div>



        </Dialog>



      </Transition>



    </div>



  );







  const moduleView = (() => {



    if (activeModule === "intake") {



      return intakeView;



    }



    if (activeModule === "estimating") {



      return (



        <>



          {bootstrapBanner}



          <EstimatingPanel



            className="space-y-6"



            orgId={activeOrgId}



            projectId={projectProfile.code}



          />



        </>



      );



    }



    return placeholderView(MODULES[activeModule]);



  })();







  const rightRail = activeModule === "intake"



    ? (



        <>



          <section className={clsx(panelBase, "p-5 text-sm space-y-3")} aria-label="Project snapshot">



            <h3 className="text-sm font-semibold text-text-primary">Project snapshot</h3>



            <dl className="space-y-2 text-xs text-text-secondary">



              <div className="flex items-center justify-between gap-2">



                <dt>Stage</dt>



                <dd className="font-semibold text-text-primary">{projectProfile.stage}</dd>



              </div>



              <div className="flex items-center justify-between gap-2">



                <dt>Bundle</dt>



                <dd className="font-semibold text-text-primary">{run ? run.project_id : "Pending"}</dd>



              </div>



              <div className="flex items-center justify-between gap-2">



                <dt>Total files</dt>



                <dd className="font-semibold text-text-primary">{run ? run.total : 0}</dd>



              </div>



            </dl>



          </section>



          <section className={clsx(panelBase, "p-5 text-sm space-y-2")} aria-label="Suggested actions">



            <h3 className="text-sm font-semibold text-text-primary">Next actions</h3>



            <ul className="mt-1 space-y-2 text-xs text-text-secondary">



              <li className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2">



                Review failed parses and requeue remediation



              </li>



              <li className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2">



                Package summary exports for estimating handoff



              </li>



              <li className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2">



                Update stakeholders once run reaches ready state



              </li>



            </ul>



          </section>



          <section className={clsx(panelBase, "p-5 text-sm")} aria-label="Intake activity">



            <h3 className="text-sm font-semibold text-text-primary">Intake activity</h3>



            {run ? (



              <div className="mt-3 space-y-3 text-xs text-text-secondary">



                <div className="flex items-center justify-between">



                  <span>Status</span>



                  <span className={clsx("rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase", runStateChip(run.status))}>{run.status}</span>



                </div>



                <div className="flex items-center justify-between">



                  <span>Parsed</span>



                  <span className="font-semibold text-text-primary">{run.parsed}</span>



                </div>



                <div className="flex items-center justify-between">



                  <span>Pending</span>



                  <span className="font-semibold text-text-primary">{run.pending}</span>



                </div>



                <div className="flex items-center justify-between">



                  <span>Failed</span>



                  <span className="font-semibold text-text-primary">{run.failed}</span>



                </div>



                <div>



                  <div className="mb-1 flex items-center justify-between">



                    <span>Progress</span>



                    <span>{statusProgress(run)}%</span>



                  </div>



                  <div className="h-2 rounded-full bg-surface-inset">



                    <div className="h-full rounded-full bg-accent" style={{ width: `${statusProgress(run)}%` }} />



                  </div>



                </div>



              </div>



            ) : (



              <p className="mt-3 text-xs text-text-secondary">



                Launch an intake run to populate live telemetry and enable export workflows.



              </p>



            )}



          </section>



        </>



      )



    : (



        <section className={clsx(panelBase, "p-5 text-sm space-y-2")} aria-label="Module preparation">



          <h3 className="text-sm font-semibold text-text-primary">Module preparation</h3>



          <p className="text-xs text-text-secondary">



            {MODULES[activeModule].placeholderBody}



          </p>



          <p className="text-xs text-text-secondary">



            The production shell reserves this space for future workflows. Wire backend APIs and UI modules before enabling it for customers.



          </p>



        </section>



      );



  return (



    <>



      <Toaster richColors position="bottom-right" />



      <AppShell



        navItems={navItems}



        activeItem={activeModule}



        onSelect={handleSelectModule}



        theme={theme}



        onToggleTheme={toggleTheme}



        user={userProfile}



        org={workspaceOrg}



        project={projectProfile}



        rightRail={rightRail}



      >



        {moduleView}



      </AppShell>



    </>



  );



}


