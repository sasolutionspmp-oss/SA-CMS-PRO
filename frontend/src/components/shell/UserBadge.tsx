import clsx from "clsx";

import type { AppShellUser } from "./AppShell";

export interface UserBadgeProps {
  user?: AppShellUser | null;
  className?: string;
}

function deriveInitials(name?: string | null, fallback = "SA"): string {
  if (!name) {
    return fallback;
  }
  const trimmed = name.trim();
  if (!trimmed) {
    return fallback;
  }
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return fallback;
  }
  if (parts.length === 1) {
    return parts[0]!.slice(0, 2).toUpperCase() || fallback;
  }
  const initials = `${parts[0]![0] ?? ""}${parts[1]![0] ?? ""}`.toUpperCase();
  return initials || trimmed.slice(0, 2).toUpperCase() || fallback;
}

export function UserBadge({ user, className }: UserBadgeProps): JSX.Element {
  const displayName = user?.name?.trim() || "Signed out";
  const displayTitle = user?.title?.trim() || "Operator";
  const initials = user?.initials?.trim() || deriveInitials(user?.name);

  return (
    <div
      className={clsx(
        "inline-flex items-center gap-3 rounded-full border border-border-subtle bg-surface px-3 py-2 shadow-panel",
        className,
      )}
      aria-label={`Signed in as ${displayName}`}
    >
      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-sm font-semibold text-accent-contrast">
        {initials}
      </span>
      <div className="flex flex-col leading-tight">
        <span className="text-sm font-semibold text-text-primary">{displayName}</span>
        <span className="text-xs text-text-secondary">{displayTitle}</span>
      </div>
    </div>
  );
}
