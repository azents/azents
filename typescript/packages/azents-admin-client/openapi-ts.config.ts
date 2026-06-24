import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: '../../../python/apps/azents/specs/admin/openapi.json',
  output: {
    path: './src/generated',
    format: 'prettier',
  },
  plugins: ['@hey-api/client-fetch'],
});
