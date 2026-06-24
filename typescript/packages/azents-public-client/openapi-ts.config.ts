import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: '../../../python/apps/azents/specs/public/openapi.json',
  output: {
    path: './src/generated',
    format: 'prettier',
  },
  plugins: ['@hey-api/client-fetch'],
});
