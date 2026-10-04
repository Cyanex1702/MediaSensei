import tailwindcss from '@tailwindcss/postcss';
import vinext from 'vinext';
import { defineConfig, loadEnv } from 'vite';

const LOCAL_PLACEHOLDER_DATABASE_ID =
  '00000000-0000-4000-8000-000000000000';

const localBindingConfig = {
  main: 'vinext/server/fetch-handler',
  compatibility_flags: ['nodejs_compat'],
  d1_databases: [
    {
      binding: 'DB',
      database_name: 'mediasensei-d1',
      database_id: LOCAL_PLACEHOLDER_DATABASE_ID,
    },
  ],
  r2_buckets: [],
};

export default defineConfig(async ({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env };
  // Keep Wrangler and Miniflare state project-local. These are non-secret tool
  // settings; application environment belongs in ignored `.env*` files.
  process.env.WRANGLER_WRITE_LOGS ??= 'false';
  process.env.WRANGLER_LOG_PATH ??= '.wrangler/logs';
  process.env.MINIFLARE_REGISTRY_PATH ??= '.wrangler/registry';

  // Wrangler snapshots its log path while the Cloudflare plugin is imported.
  const { cloudflare } = await import('@cloudflare/vite-plugin');

  return {
    define: { 'process.env.NEXT_PUBLIC_CORE_API_URL': JSON.stringify(env.NEXT_PUBLIC_CORE_API_URL || 'http://127.0.0.1:8000/api/v1') },
    css: { postcss: { plugins: [tailwindcss()] } },
    server: {
      host: '127.0.0.1', port: Number(env.MEDIASENSEI_WEB_PORT || 3000), strictPort: true,
      watch: {
        ignored: ['**/.audit/**', '**/.venv/**', '**/.mediasensei-workspace/**', '**/.mediasensei-launcher/**', '**/release/**'],
      },
    },
    plugins: [
      vinext(),
      cloudflare({
        viteEnvironment: { name: 'rsc', childEnvironments: ['ssr'] },
        config: localBindingConfig,
      }),
    ],
  };
});
