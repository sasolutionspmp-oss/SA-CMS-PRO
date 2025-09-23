import clsx from "clsx";

import type { AppShellOrg, AppShellProject } from "./AppShell";

export interface OrgSummaryProps {
  org?: AppShellOrg | null;
  project?: AppShellProject | null;
  className?: string;
}

export function OrgSummary({ org, project, className }: OrgSummaryProps): JSX.Element {
  const orgName = org?.name ?? "—";
  const orgCode = org?.code;
  const projectName = project?.name ?? "—";
  const projectCode = project?.code;
  const projectStage = project?.stage;

  return (
    <div className={clsx("space-y-4 text-sm", className)}>
      <div className="space-y-1">
        <div className="text-xs font-semibold uppercase tracking-wide text-text-tertiary">Organization</div>
        <div className="text-sm font-semibold text-text-primary">{orgName}</div>
        {orgCode ? (
          <span className="inline-flex items-center rounded-full bg-surface px-2.5 py-0.5 text-xs font-medium text-text-secondary">
            {orgCode}
          </span>
        ) : null}
      </div>
      <div className="space-y-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-text-tertiary">Project</div>
        <div className="text-sm font-semibold text-text-primary">{projectName}</div>
        <div className="flex flex-wrap items-center gap-2">
          {projectCode ? (
            <span className="inline-flex items-center rounded-full bg-surface-inset px-2.5 py-0.5 text-xs font-medium text-text-secondary">
              {projectCode}
            </span>
          ) : null}
          {projectStage ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
              {projectStage}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
