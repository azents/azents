import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import nextPlugin from "@next/eslint-plugin-next";
import perfectionist from "eslint-plugin-perfectionist";
import checkFile from "eslint-plugin-check-file";
import eslintComments from "@eslint-community/eslint-plugin-eslint-comments";
import importPlugin from "eslint-plugin-import";
import prettier from "eslint-plugin-prettier/recommended";

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig([
  {
    ignores: [".next/**", "storybook-static/**"],
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
      // React hooks rules
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      // Next.js rules
      ...nextPlugin.configs.recommended.rules,
      ...nextPlugin.configs["core-web-vitals"].rules,
      // Strict rules
      "no-undefined": "error",
      "@typescript-eslint/no-unused-vars": "error",
      curly: ["error", "all"],
      eqeqeq: ["error", "always", { null: "ignore" }],
      // Enable type-checked rules
      "@typescript-eslint/no-unnecessary-condition": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      // Prefer null or optional over undefined in types
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
      // Import sorting
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
      // Disallow index.ts files - prefer direct imports for tree-shaking
      "check-file/no-index": "error",
      // Require description for eslint-disable comments
      "@eslint-community/eslint-comments/require-description": "error",
      // 순환 참조 금지
      "import/no-cycle": "error",
      // 계층 간 import 규칙
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
  // config 외부에서 process.env 접근 금지
  {
    files: ["**/*.ts", "**/*.tsx"],
    ignores: ["src/config.ts", "src/config/**"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "MemberExpression[object.name='process'][property.name='env']",
          message:
            "process.env 직접 접근 금지. @/config의 getServerConfig(), getPublicConfig() 또는 useConfig()를 사용하세요.",
        },
      ],
    },
  },
  // NEXT_PUBLIC_ 환경변수 사용 금지 (빌드 타임 환경변수 대신 서버 사이드 환경변수 사용)
  {
    files: ["**/*.ts", "**/*.tsx"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "MemberExpression[object.object.name='process'][object.property.name='env'][property.name=/^NEXT_PUBLIC_/]",
          message:
            "NEXT_PUBLIC_ 환경변수 사용 금지. 서버 사이드 환경변수를 사용하고 클라이언트에는 ConfigProvider를 통해 전달하세요.",
        },
        {
          selector:
            "MemberExpression[object.name='process'][object.property.name='env'] > Literal[value=/NEXT_PUBLIC_/]",
          message:
            "NEXT_PUBLIC_ 환경변수 사용 금지. 서버 사이드 환경변수를 사용하고 클라이언트에는 ConfigProvider를 통해 전달하세요.",
        },
      ],
    },
  },
  // Prettier 통합
  prettier,
  {
    rules: {
      curly: ["error", "all"],
    },
  },
]);
