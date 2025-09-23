import clsx from "clsx";
import { Moon, Sun } from "lucide-react";
import { type ReactNode } from "react";

export type AppShellTone = "default" | "success" | "warning" | "danger";

export interface AppShellNavItem {
  id: string;
  label: string;
  description: string;
  icon: ReactNode;
  badge?: string | ReactNode;
  tone?: AppShellTone;
}

export interface AppShellProfile {
  name: string;
  code: string;
  stage?: string;
}

export interface AppShellUser {
  name: string;
  title?: string;
  initials: string;
}

export interface AppShellProps {
  children: ReactNode;
  navItems: AppShellNavItem[];
  activeItem: string;
  onSelect: (id: string) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  user: AppShellUser;
  org: AppShellProfile;
  project: AppShellProfile;
  rightRail?: ReactNode;
}

function badgeToneClasses(tone: AppShellTone = "default"): string {
  switch (tone) {
    case "success":
      return "bg-success-soft text-success border-success/30";
    case "warning":
      return "bg-warning-soft text-warning border-warning/30";
    case "danger":
      return "bg-danger-soft text-danger border-danger/30";
    default:
      return "bg-surface-muted text-text-secondary border-border-subtle";
  }
}

function NavItem({
  item,
  active,
  onSelect,
}: {
  item: AppShellNavItem;
  active: boolean;
  onSelect: (id: string) => void;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={() => onSelect(item.id)}
      className={clsx(
        "group w-full rounded-xl border border-transparent px-3 py-2 text-left transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        active ? "bg-surface-elevated/90 text-text-primary shadow-panel" : "hover:bg-surface-muted text-text-secondary",
      )}
    >
      <div className="flex items-center gap-3">
        <span
          className={clsx(
            "flex h-9 w-9 items-center justify-center rounded-lg border text-accent",
            active ? "border-accent/60 bg-accent/10" : "border-border-subtle bg-surface",
          )}
        >
          {item.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className={clsx("truncate text-sm font-semibold", active ? "text-text-primary" : "text-text-secondary")}>{
              item.label
            }</p>
            {item.badge ? (
              <span
                className={clsx(
                  "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                  badgeToneClasses(item.tone ?? "default"),
                )}
              >
                {item.badge}
              </span>
            ) : null}
          </div>
          <p className="mt-0.5 text-xs text-text-tertiary">{item.description}</p>
        </div>
      </div>
    </button>
  );
}

function UserBadge({ user }: { user: AppShellUser }): JSX.Element {
  const initials = user.initials || user.name.slice(0, 2).toUpperCase();
  return (
    <div className="flex items-center gap-3 rounded-full border border-border-subtle bg-surface px-3 py-1.5 shadow-panel">
      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-sm font-semibold text-accent-contrast">
        {initials}
      </span>
      <div className="leading-tight">
        <p className="text-sm font-semibold text-text-primary">{user.name}</p>
        {user.title ? <p className="text-xs text-text-tertiary">{user.title}</p> : null}
      </div>
    </div>
  );
}

function OrgProjectSummary({
  org,
  project,
}: {
  org: AppShellProfile;
  project: AppShellProfile;
}): JSX.Element {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-text-tertiary">Organization</p>
        <p className="text-sm font-semibold text-text-primary">{org.name}</p>
        <p className="text-xs text-text-secondary">{org.code}</p>
      </div>
      <div className="hidden h-10 w-px bg-border-subtle sm:block" aria-hidden />
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-text-tertiary">Project</p>
        <p className="text-sm font-semibold text-text-primary">{project.name}</p>
        <p className="text-xs text-text-secondary">{project.code}</p>
      </div>
      {project.stage ? (
        <div className="hidden h-10 w-px bg-border-subtle sm:block" aria-hidden />
      ) : null}
      {project.stage ? (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-text-tertiary">Stage</p>
          <p className="text-sm font-semibold text-text-primary">{project.stage}</p>
          <p className="text-xs text-text-secondary">Operational Copilot ready</p>
        </div>
      ) : null}
    </div>
  );
}

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
  return (
    <div className="min-h-screen bg-surface-base text-text-primary">
      <div className="flex min-h-screen">
        <aside className="hidden w-72 flex-shrink-0 flex-col border-r border-border-subtle bg-surface-muted/60 px-4 py-6 lg:flex">
          <div className="space-y-6">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-text-tertiary">Signal Advantage</p>
              <h1 className="mt-2 text-lg font-semibold text-text-primary">Control Center</h1>
              <p className="text-xs text-text-secondary">
                Navigate estimating, intake, and operations modules with copilot overlays.
              </p>
            </div>
            <nav className="space-y-2">
              {navItems.map((item) => (
                <NavItem key={item.id} item={item} active={item.id === activeItem} onSelect={onSelect} />
              ))}
            </nav>
          </div>
          <div className="mt-auto pt-8">
            <UserBadge user={user} />
          </div>
        </aside>
        <div className="flex min-h-screen flex-1 flex-col">
          <header className="border-b border-border-subtle bg-surface-elevated/90 px-4 py-4 shadow-shell sm:px-8">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <OrgProjectSummary org={org} project={project} />
              <div className="flex items-center justify-between gap-3">
                <button
                  type="button"
                  onClick={onToggleTheme}
                  className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-border-subtle bg-surface shadow-panel transition hover:-translate-y-0.5 hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  aria-label="Toggle theme"
                >
                  {theme === "dark" ? <Sun className="h-5 w-5" aria-hidden /> : <Moon className="h-5 w-5" aria-hidden />}
                </button>
                <div className="lg:hidden">
                  <UserBadge user={user} />
                </div>
              </div>
            </div>
          </header>
          <div className="flex flex-1 flex-col bg-surface">
            <div className={clsx("mx-auto flex w-full max-w-7xl flex-1 flex-col gap-8 px-4 py-8 lg:flex-row lg:px-8")}> 
              <main className={clsx("flex-1", rightRail ? "lg:max-w-4xl" : "max-w-5xl")}>{children}</main>
              {rightRail ? (
                <aside className="hidden w-full max-w-sm flex-shrink-0 space-y-4 lg:block">{rightRail}</aside>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
