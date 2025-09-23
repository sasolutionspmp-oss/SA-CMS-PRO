import clsx from "clsx";

type StatusChip = {
  indicatorClass: string;
  label: string;
  badge: string;
};

const chipClasses =
  "inline-flex items-center gap-2 rounded-full bg-accent px-3 py-1.5 text-xs font-semibold text-accent-contrast shadow-panel transition-transform hover:-translate-y-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
const badgeClasses =
  "rounded-full border border-accent-contrast-40 bg-accent-contrast-20 px-2 py-0.5 text-[10px] uppercase tracking-wide text-accent-contrast";

const statusChips: StatusChip[] = [
  {
    indicatorClass: "bg-success",
    label: "Build Status",
    badge: "passing",
  },
  {
    indicatorClass: "bg-warning",
    label: "JIT Mode",
    badge: "active",
  },
  {
    indicatorClass: "bg-accent",
    label: "@tailwindcss/postcss",
    badge: "wired-in",
  },
];

const toTestId = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

export function TailwindProbe(): JSX.Element {
  return (
    <section
      data-testid="tailwind-probe"
      className={clsx(
        "rounded-3xl border border-accent-50 bg-surface-elevated-90 p-6 text-accent shadow-panel ring-1 ring-accent-20 backdrop-blur"
      )}
    >
      <p className="text-xs font-medium uppercase tracking-[0.2em] text-text-tertiary">
        Tailwind Utilities Online
      </p>
      <h2 className="mt-3 text-lg font-semibold text-text-primary">
        Runtime tokens and utilities compile through @tailwindcss/postcss.
      </h2>
      <p className="mt-2 text-sm text-text-secondary">
        This probe exercises gradients, grid layouts, semantic tokens, and focus
        states to ensure our PostCSS stack emits the expected classes in both
        dev and production builds.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {statusChips.map((chip) => (
          <span
            key={chip.label}
            data-testid={`tailwind-probe-chip-${toTestId(chip.label)}`}
            className={chipClasses}
          >
            <span className={clsx("h-2 w-2 rounded-full", chip.indicatorClass)} aria-hidden />
            {chip.label}
            <span className={badgeClasses}>{chip.badge}</span>
          </span>
        ))}
      </div>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <div
          data-testid="tailwind-probe-gradient-card"
          className="rounded-2xl border border-accent-30 bg-gradient-to-r from-brand-500 via-accent to-brand-700 p-5 text-accent-contrast shadow-shell"
        >
          <p className="text-xs uppercase tracking-[0.28em] text-accent-contrast-80">
            Gradient Check
          </p>
          <p className="mt-2 text-sm font-semibold">bg-gradient-to-r | from-brand-500 | via-accent | to-brand-700</p>
        </div>
        <div
          data-testid="tailwind-probe-layout-card"
          className="rounded-2xl border border-border-subtle bg-surface p-5 shadow-panel"
        >
          <p className="text-xs uppercase tracking-[0.28em] text-text-tertiary">
            Layout Grid
          </p>
          <div
            data-testid="tailwind-probe-layout-grid"
            className="mt-3 grid grid-cols-3 gap-2 text-center text-xs font-semibold text-text-secondary"
          >
            <span className="rounded-xl bg-surface-muted py-2 shadow-inner">gap-2</span>
            <span className="rounded-xl bg-surface-muted py-2 shadow-inner">grid-cols-3</span>
            <span className="rounded-xl bg-surface-muted py-2 shadow-inner">rounded-xl</span>
          </div>
        </div>
      </div>
    </section>
  );
}
