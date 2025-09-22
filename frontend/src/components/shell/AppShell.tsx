import clsx from "clsx";
import { useMemo } from "react";
import type { PropsWithChildren, ReactNode } from "react";

export type AppShellTone = "default" | "success" | "warning" | "danger";

export interface AppShellNavItem {
  id: string;
  label: string;
  description?: string;
  icon?: ReactNode;
  badge?: string;
  tone?: AppShellTone;
}

export interface AppShellIdentity {
  name?: string | null;
  full_name?: string | null;
  username?: string | null;
  code?: string | null;
  roles?: string[];
  slug?: string | null;
}

export interface AppShellProps extends PropsWithChildren {
  navItems: AppShellNavItem[];
  activeItem: string;
  onSelect: (id: string) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  user?: AppShellIdentity | null;
  org?: AppShellIdentity | null;
  project?: AppShellIdentity | null;
  rightRail?: ReactNode;
}

const BADGE_TONES: Record<AppShellTone, string> = {
  default: "bg-slate-200 text-slate-900",
  success: "bg-emerald-500 text-emerald-950 dark:text-white",
  warning: "bg-amber-400 text-amber-950",
  danger: "bg-rose-500 text-white",
};

function Badge({ label, tone = "default" }: { label: string; tone?: AppShellTone }) {
  return (
    <span
      className={clsx(
        "ml-auto inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold",
        BADGE_TONES[tone] ?? BADGE_TONES.default,
      )}
    >
      {label}
    </span>
  );
}

export function AppShell({
  navItems,
  activeItem,
  onSelect,
  theme,
  onToggleTheme,
  user,
  org,
  project,
  rightRail,
  children,
}: AppShellProps) {
  const isDark = theme === "dark";
  const activeNav = useMemo(() => navItems.find((item) => item.id === activeItem), [navItems, activeItem]);

  const frameClass = clsx(
    "min-h-screen w-full",
    isDark ? "bg-slate-950 text-slate-100" : "bg-slate-100 text-slate-900",
  );

  const sidebarClass = clsx(
    "flex w-64 flex-col border-r border-slate-200/40",
    isDark ? "bg-slate-900/80" : "bg-white",
  );

  const headerClass = clsx(
    "flex items-center justify-between border-b border-slate-200/40 px-6 py-4",
    isDark ? "bg-slate-900/60" : "bg-white/80 backdrop-blur",
  );

  const mainClass = "flex-1 overflow-y-auto px-6 py-6";

  const themeButtonClass = clsx(
    "rounded-md border px-3 py-1 text-xs font-medium transition",
    isDark
      ? "border-slate-700 bg-slate-800 text-slate-100 hover:bg-slate-700"
      : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
  );

  const handleSelect = (id: string) => {
    if (id !== activeItem) {
      onSelect(id);
    }
  };

  return (
    <div className={frameClass}>
      <div className="flex min-h-screen">
        <aside className={sidebarClass}>
          <div className="flex flex-col gap-6 px-4 py-6">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Workspace</p>
              <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                {org?.name ?? "SA-CMS Pro"}
              </h1>
              {project?.name ? (
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {project.name}
                  {project.code ? ` · ${project.code}` : ""}
                </p>
              ) : null}
            </div>

            <nav className="space-y-1">
              {navItems.map((item) => {
                const isActive = item.id === activeItem;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => handleSelect(item.id)}
                    className={clsx(
                      "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition",
                      isActive
                        ? "bg-emerald-500 text-white shadow-sm"
                        : isDark
                          ? "hover:bg-slate-800"
                          : "hover:bg-slate-100",
                    )}
                    aria-current={isActive ? "page" : undefined}
                  >
                    {item.icon ? <span className="text-base opacity-80">{item.icon}</span> : null}
                    <span className="flex flex-col">
                      <span className="font-medium">{item.label}</span>
                      {item.description ? (
                        <span className="text-[11px] text-slate-500 dark:text-slate-400">{item.description}</span>
                      ) : null}
                    </span>
                    {item.badge ? <Badge label={item.badge} tone={item.tone ?? "default"} /> : null}
                  </button>
                );
              })}
            </nav>
          </div>
        </aside>

        <section className="flex min-h-screen flex-1 flex-col">
          <header className={headerClass}>
            <div>
              <p className="text-xs uppercase tracking-wider text-slate-500">Module</p>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                {activeNav?.label ?? "Dashboard"}
              </h2>
            </div>
            <div className="flex items-center gap-4">
              {user ? (
                <div className="text-right">
                  <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                    {user.full_name ?? user.name ?? user.username ?? "Operator"}
                  </p>
                  {user.roles && user.roles.length > 0 ? (
                    <p className="text-[11px] uppercase tracking-widest text-slate-500">
                      {user.roles.join(", ")}
                    </p>
                  ) : null}
                </div>
              ) : null}
              <button type="button" onClick={onToggleTheme} className={themeButtonClass}>
                {isDark ? "Light mode" : "Dark mode"}
              </button>
            </div>
          </header>

          <div className="flex flex-1">
            <main className={mainClass}>{children}</main>
            {rightRail ? (
              <aside className="hidden w-80 border-l border-slate-200/40 px-5 py-6 lg:block">{rightRail}</aside>
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}
