import eslintComments from "@eslint-community/eslint-plugin-eslint-comments";
import nextPlugin from "@next/eslint-plugin-next";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import checkFile from "eslint-plugin-check-file";
import importPlugin from "eslint-plugin-import";
import perfectionist from "eslint-plugin-perfectionist";
import prettier from "eslint-plugin-prettier/recommended";
import reactHooks from "eslint-plugin-react-hooks";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig([
  {
    ignores: [".next/**"],
  },
  tseslint.configs.recommendedTypeChecked,
  {
    files: ["**/*.ts", "**/*.tsx", "**/*.mts"],
    plugins: {
      "react-hooks": reactHooks,
      "@next/next": nextPlugin,
      perfectionist,
      "check-file": checkFile,
      "@eslint-community/eslint-comments": eslintComments,
      import: importPlugin,
    },
    languageOptions: {
      parserOptions: {
        projectService: {
          allowDefaultProject: ["*.mjs"],
          defaultProject: "tsconfig.json",
        },
        tsconfigRootDir: __dirname,
      },
    },
    settings: {
      "import/resolver": {
        typescript: {
          project: __dirname,
        },
      },
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
      "no-undefined": "error",
      "@typescript-eslint/no-unused-vars": "error",
      curly: ["error", "all"],
      eqeqeq: ["error", "always", { null: "ignore" }],
      "@typescript-eslint/no-unnecessary-condition": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      "@typescript-eslint/no-restricted-types": [
        "error",
        {
          types: {
            undefined: {
              message: "Use `null` or optional (`?`) instead of `undefined`",
              suggest: ["null"],
            },
          },
        },
      ],
      "perfectionist/sort-imports": [
        "error",
        {
          type: "alphabetical",
          order: "asc",
          ignoreCase: true,
          groups: [
            "builtin",
            "external",
            "internal",
            ["parent", "sibling", "index"],
            "type",
          ],
          newlinesBetween: "ignore",
          internalPattern: ["^@/.*"],
        },
      ],
      "perfectionist/sort-named-imports": [
        "error",
        {
          type: "alphabetical",
          order: "asc",
          ignoreCase: true,
        },
      ],
      "perfectionist/sort-named-exports": [
        "error",
        {
          type: "alphabetical",
          order: "asc",
          ignoreCase: true,
        },
      ],
      "check-file/no-index": "error",
      "@eslint-community/eslint-comments/require-description": "error",
      "import/no-cycle": "error",
      "import/no-restricted-paths": [
        "error",
        {
          basePath: __dirname,
          zones: [
            {
              target: "src/shared/**/*",
              from: "src/features/**/*",
              message:
                "Cannot import from features in shared. shared is the lowest layer.",
            },
            {
              target: "src/features/**/*",
              from: "src/app/**/*",
              message:
                "Cannot import from app in features. app is the entrypoint.",
            },
            {
              target: "src/shared/**/*",
              from: "src/app/**/*",
              message: "Cannot import from app in shared.",
            },
          ],
        },
      ],
    },
  },
  prettier,
  {
    rules: {
      curly: ["error", "all"],
    },
  },
]);
