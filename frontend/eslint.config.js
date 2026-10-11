import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import vue from 'eslint-plugin-vue'
import globals from 'globals'

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'coverage/**',
      'playwright-report/**',
      'test-results/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...vue.configs['flat/recommended'],
  {
    files: ['**/*.{ts,vue,js}'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
  {
    files: ['**/*.vue'],
    languageOptions: { parserOptions: { parser: tseslint.parser } },
    // Prettier owns layout; ESLint retains Vue correctness and TypeScript checks.
    rules: Object.fromEntries(
      [
        'html-indent',
        'multiline-html-element-content-newline',
        'html-closing-bracket-newline',
        'singleline-html-element-content-newline',
        'max-attributes-per-line',
        'html-self-closing',
      ].map((name) => [`vue/${name}`, 'off']),
    ),
  },
)
