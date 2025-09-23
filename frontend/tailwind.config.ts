import type { Config } from "tailwindcss";

const withOpacity = (variable: string) => {
  return ({ opacityValue }: { opacityValue?: string }) => {
    if (opacityValue !== undefined) {
      return `rgb(var(${variable}) / ${opacityValue})`;
    }
    return `rgb(var(${variable}))`;
  };
};

const semanticUtilities = ({
  addUtilities,
}: {
  addUtilities: (utilities: Record<string, Record<string, string>>) => void;
}) => {
  addUtilities({
    ".bg-surface": { backgroundColor: "rgb(var(--color-surface) / 1)" },
    ".bg-surface-soft": { backgroundColor: "rgb(var(--color-surface) / 0.6)" },
    ".bg-surface-muted": { backgroundColor: "rgb(var(--color-surface-muted) / 1)" },
    ".bg-surface-muted-soft": { backgroundColor: "rgb(var(--color-surface-muted) / 0.6)" },
    ".bg-surface-elevated": { backgroundColor: "rgb(var(--color-surface-elevated) / 1)" },
    ".bg-surface-elevated-90": { backgroundColor: "rgb(var(--color-surface-elevated) / 0.9)" },
    ".bg-surface-inset": { backgroundColor: "rgb(var(--color-surface-inset) / 1)" },
    ".bg-surface-inset-soft": { backgroundColor: "rgb(var(--color-surface-inset) / 0.6)" },
    ".bg-accent": { backgroundColor: "rgb(var(--color-accent) / 1)" },
    ".bg-accent-90": { backgroundColor: "rgb(var(--color-accent) / 0.9)" },
    ".bg-accent-soft": { backgroundColor: "rgb(var(--color-accent-soft) / 1)" },
    ".bg-accent-contrast-20": { backgroundColor: "rgb(var(--color-accent-contrast) / 0.2)" },
    ".bg-success": { backgroundColor: "rgb(var(--color-success) / 1)" },
    ".bg-success-90": { backgroundColor: "rgb(var(--color-success) / 0.9)" },
    ".bg-success-soft": { backgroundColor: "rgb(var(--color-success-soft) / 1)" },
    ".bg-warning": { backgroundColor: "rgb(var(--color-warning) / 1)" },
    ".bg-warning-soft": { backgroundColor: "rgb(var(--color-warning-soft) / 1)" },
    ".bg-danger": { backgroundColor: "rgb(var(--color-danger) / 1)" },
    ".bg-danger-soft": { backgroundColor: "rgb(var(--color-danger-soft) / 1)" },
    ".bg-danger-soft-10": { backgroundColor: "rgb(var(--color-danger-soft) / 0.1)" },
    ".bg-danger-soft-70": { backgroundColor: "rgb(var(--color-danger-soft) / 0.7)" },
    ".bg-brand-500": { backgroundColor: "rgb(var(--color-brand-500) / 1)" },
    ".bg-brand-700": { backgroundColor: "rgb(var(--color-brand-700) / 1)" },
    ".text-text-primary": { color: "rgb(var(--color-text-primary) / 1)" },
    ".text-text-secondary": { color: "rgb(var(--color-text-secondary) / 1)" },
    ".text-text-tertiary": { color: "rgb(var(--color-text-tertiary) / 1)" },
    ".text-accent": { color: "rgb(var(--color-accent) / 1)" },
    ".text-accent-contrast": { color: "rgb(var(--color-accent-contrast) / 1)" },
    ".text-accent-contrast-80": { color: "rgb(var(--color-accent-contrast) / 0.8)" },
    ".text-success": { color: "rgb(var(--color-success) / 1)" },
    ".text-warning": { color: "rgb(var(--color-warning) / 1)" },
    ".text-danger": { color: "rgb(var(--color-danger) / 1)" },
    ".border-border-subtle": { borderColor: "rgb(var(--color-border-subtle) / 1)" },
    ".border-border-strong": { borderColor: "rgb(var(--color-border-strong) / 1)" },
    ".border-accent": { borderColor: "rgb(var(--color-accent) / 1)" },
    ".border-accent-30": { borderColor: "rgb(var(--color-accent) / 0.3)" },
    ".border-accent-50": { borderColor: "rgb(var(--color-accent) / 0.5)" },
    ".border-accent-contrast-40": { borderColor: "rgb(var(--color-accent-contrast) / 0.4)" },
    ".border-danger-soft": { borderColor: "rgb(var(--color-danger-soft) / 1)" },
    ".divide-border-subtle > :not([hidden]) ~ :not([hidden])": {
      "--tw-divide-y-reverse": "0",
      borderColor: "rgb(var(--color-border-subtle) / 1)",
    },
    ".ring-accent": { "--tw-ring-color": "rgb(var(--color-accent) / 1)" },
    ".ring-accent-20": { "--tw-ring-color": "rgb(var(--color-accent) / 0.2)" },
    ".ring-accent-30": { "--tw-ring-color": "rgb(var(--color-accent) / 0.3)" },
    ".ring-accent-40": { "--tw-ring-color": "rgb(var(--color-accent) / 0.4)" },
    ".ring-accent-50": { "--tw-ring-color": "rgb(var(--color-accent) / 0.5)" },
    ".shadow-panel": { boxShadow: "var(--shadow-panel)" },
    ".shadow-shell": { boxShadow: "var(--shadow-shell)" },
    ".from-brand-500": {
      "--tw-gradient-from": "rgb(var(--color-brand-500)) var(--tw-gradient-from-position)",
      "--tw-gradient-to": "rgb(var(--color-brand-500) / 0)",
      "--tw-gradient-stops": "var(--tw-gradient-from), var(--tw-gradient-to)",
    },
    ".via-accent": {
      "--tw-gradient-stops":
        "var(--tw-gradient-from), rgb(var(--color-accent)) var(--tw-gradient-via-position), var(--tw-gradient-to)",
    },
    ".to-brand-700": {
      "--tw-gradient-to": "rgb(var(--color-brand-700)) var(--tw-gradient-to-position)",
    },
  });
};

const config: Config = {
  darkMode: "class",
  content: ["./index.html", "./tailwind-probe.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: withOpacity("--color-surface"),
        "surface-muted": withOpacity("--color-surface-muted"),
        "surface-elevated": withOpacity("--color-surface-elevated"),
        "surface-inset": withOpacity("--color-surface-inset"),
        accent: withOpacity("--color-accent"),
        "accent-soft": withOpacity("--color-accent-soft"),
        "accent-contrast": withOpacity("--color-accent-contrast"),
        "text-primary": withOpacity("--color-text-primary"),
        "text-secondary": withOpacity("--color-text-secondary"),
        "text-tertiary": withOpacity("--color-text-tertiary"),
        "border-subtle": withOpacity("--color-border-subtle"),
        "border-strong": withOpacity("--color-border-strong"),
        success: withOpacity("--color-success"),
        "success-soft": withOpacity("--color-success-soft"),
        warning: withOpacity("--color-warning"),
        "warning-soft": withOpacity("--color-warning-soft"),
        danger: withOpacity("--color-danger"),
        "danger-soft": withOpacity("--color-danger-soft"),
        brand: {
          500: withOpacity("--color-brand-500"),
          700: withOpacity("--color-brand-700"),
        },
      },
      boxShadow: {
        panel: "var(--shadow-panel)",
        shell: "var(--shadow-shell)",
      },
      ringColor: {
        accent: withOpacity("--color-accent"),
      },
    },
  },
  plugins: [semanticUtilities],
};

export default config;
