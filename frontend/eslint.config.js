import globals from "globals";
import tseslint from "@typescript-eslint/eslint-plugin";
import tsparser from "@typescript-eslint/parser";

const tsRecommendedConfigs = tseslint.configs["flat/recommended"].map((config) => {
  const baseLanguageOptions = {
    ...(config.languageOptions ?? {}),
    parser: tsparser,
    parserOptions: {
      ...(config.languageOptions?.parserOptions ?? {}),
      project: "./tsconfig.json",
      tsconfigRootDir: import.meta.dirname,
    },
    globals: {
      ...globals.browser,
      ...globals.es2024,
      ...(config.languageOptions?.globals ?? {}),
    },
  };

  if (config.files) {
    return {
      ...config,
      files: ["src/**/*.{ts,tsx}", "tests/**/*.{ts,tsx}"],
      languageOptions: baseLanguageOptions,
      rules: {
        ...config.rules,
        "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_", ignoreRestSiblings: true }],
        "@typescript-eslint/consistent-type-imports": "error",
        "no-console": ["warn", { allow: ["error", "warn"] }],
      },
    };
  }

  return {
    ...config,
    languageOptions: baseLanguageOptions,
  };
});

export default [
  {
    ignores: ["dist/**", "node_modules/**"],
  },
  ...tsRecommendedConfigs,
  {
    files: ["vite.config.ts", "playwright.config.ts", "postcss.config.js"],
    languageOptions: {
      parser: tsparser,
      parserOptions: {
        project: "./tsconfig.json",
        tsconfigRootDir: import.meta.dirname,
      },
      globals: {
        ...globals.node,
        ...globals.es2024,
      },
    },
    plugins: {
      "@typescript-eslint": tseslint,
    },
    rules: {
      ...tseslint.configs.recommended.rules,
    },
  },
];
