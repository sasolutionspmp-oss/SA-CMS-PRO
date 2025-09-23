import clsx from "clsx";
import { Moon, Sun } from "lucide-react";
import { type ReactNode } from "react";

import { OrgSummary } from "./OrgSummary";
import { UserBadge } from "./UserBadge";

export type AppShellNavTone = "neutral" | "accent" | "warning" | "success" | "danger";

export interface AppShellNavItem {
  id: string;
  label: string;
  description?: string;
  icon?: ReactNode;
  badge?: ReactNode;
  tone?: AppShellNavTone;
  disabled?: boolean;
}

export interface AppShellUser {
  name: string;
  title?: string | null;
  initials?: string | null;
}

export interface AppShellOrg {
  name: string;
  code?: string | null;
}

export interface AppShellProject {
  name: string;
  code?: string | null;
  stage?: string | null;
}

export interface AppShellProps {
  children: ReactNode;
  navItems: AppShellNavItem[];
  activeItem?: string | null;
  onSelect: (id: string) => void;
  theme: "light" | "dark";
  onToggleTheme?: () => void;
  user?: AppShellUser | null;
  org?: AppShellOrg | null;
  project?: AppShellProject | null;
  rightRail?: ReactNode;
}

const BADGE_TONE_CLASSES: Record<AppShellNavTone, string> = {
  neutral: "bg-surface-inset text-text-secondary",
  accent: "bg-accent-soft text-accent",
  warning: "bg-warning-soft text-warning",
  success: "bg-success-soft text-success",
  danger: "bg-danger-soft text-danger",
};

const ACTIVE_NAV_CLASSES =
  "bg-surface px-3 py-3 ring-1 ring-border-strong shadow-panel text-text-primary";
const INACTIVE_NAV_CLASSES =
  "bg-transparent px-3 py-3 text-text-secondary hover:bg-surface-soft hover:text-text-primary";

export function AppShell({
  children,
  navItems,
  activeItem,
  onSelect,
  theme,
  onToggleTheme,
  user,
  org,
  project,
  rightRail,
}: AppShellProps): JSX.Element {
  const workspaceTitle = project?.name || "Project workspace";
  const workspaceCode = project?.code;
  const workspaceStage = project?.stage;
  const organizationName = org?.name || "Workspace";
  const organizationCode = org?.code;

  const handleSelect = (item: AppShellNavItem) => {
    if (!item.disabled) {
      onSelect(item.id);
    }
  };

  return (
    <div className="flex min-h-screen bg-surface text-text-primary">
      <aside
        className="hidden w-72 flex-shrink-0 flex-col border-r border-border-subtle bg-surface-elevated lg:flex"
        aria-label="Primary navigation"
      >
        <div className="flex h-16 items-center px-6 text-sm font-semibold uppercase tracking-wide text-text-tertiary">
          SA CMS
        </div>
        <nav className="flex-1 overflow-y-auto px-3 pb-6">
          <ul className="flex flex-col gap-2">
            {navItems.map((item) => {
              const isActive = item.id === activeItem;
              const tone = item.tone ?? "neutral";
              const badgeClass = BADGE_TONE_CLASSES[tone];
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => handleSelect(item)}
                    className={clsx(
                      "group w-full rounded-xl text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                      item.disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
                      isActive ? ACTIVE_NAV_CLASSES : INACTIVE_NAV_CLASSES,
                    )}
                    aria-current={isActive ? "page" : undefined}
                    disabled={item.disabled}
                  >
                    <div className="flex items-center gap-3">
                      {item.icon ? (
                        <span className={clsx("flex h-9 w-9 items-center justify-center rounded-full text-text-tertiary", isActive ? "bg-surface-inset" : "bg-surface-muted")}>{item.icon}</span>
                      ) : null}
                      <div className="flex flex-1 flex-col gap-1">
                        <div className="flex items-center gap-2">
                          <span className={clsx("text-sm font-semibold", isActive ? "text-text-primary" : "text-text-secondary")}>{item.label}</span>
                          {item.badge ? (
                            <span className={clsx(
                              "inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium",
                              badgeClass,
                            )}
                            >
                              {item.badge}
                            </span>
                          ) : null}
                        </div>
                        {item.description ? (
                          <p className="text-xs text-text-tertiary line-clamp-2">{item.description}</p>
                        ) : null}
                      </div>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="border-t border-border-subtle p-5">
          <OrgSummary org={org} project={project} />
        </div>
      </aside>
      <div className="flex min-h-screen flex-1 flex-col">
        <header className="flex flex-col gap-4 border-b border-border-subtle bg-surface-elevated px-4 py-4 md:flex-row md:items-center md:justify-between md:px-8">
          <div className="space-y-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-text-tertiary">{organizationName}</div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-base font-semibold text-text-primary">{workspaceTitle}</h1>
              {workspaceCode ? (
                <span className="inline-flex items-center rounded-full bg-surface-inset px-2.5 py-0.5 text-xs font-medium text-text-secondary">
                  {workspaceCode}
                </span>
              ) : null}
              {workspaceStage ? (
                <span className="inline-flex items-center rounded-full bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-accent">
                  {workspaceStage}
                </span>
              ) : null}
              {organizationCode ? (
                <span className="inline-flex items-center rounded-full bg-surface px-2.5 py-0.5 text-xs font-medium text-text-tertiary">
                  {organizationCode}
                </span>
              ) : null}
            </div>
            <p className="text-xs text-text-secondary">
              Review program modules, monitor status, and coordinate estimating and intake workflows inside the SA CMS workspace.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={onToggleTheme}
              className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-border-subtle bg-surface text-text-secondary shadow-panel transition hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            >
              {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
            </button>
            <UserBadge user={user} />
          </div>
        </header>
        <div className="flex flex-1 overflow-hidden">
          <main className="flex-1 overflow-y-auto px-4 py-6 md:px-8 md:py-10">
            <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">{children}</div>
          </main>
          {rightRail ? (
            <aside className="hidden w-80 flex-shrink-0 overflow-y-auto border-l border-border-subtle bg-surface-elevated px-5 py-6 lg:block">
              <div className="space-y-6">{rightRail}</div>
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  );
}
