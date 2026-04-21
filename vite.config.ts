import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig, loadEnv} from 'vite';

export default defineConfig(({mode, command}) => {
  const env = loadEnv(mode, '.', '');
  // GitHub Pages 项目站：若用相对路径 `./data/...`，在地址栏无末尾 `/` 时会错误解析到
  // github.io/data/... 导致 404。生产构建使用仓库子路径作为绝对前缀。
  const base = command === 'build' ? '/restaurant-weekly-dashboard/' : '/';
  return {
    base,
    plugins: [react(), tailwindcss()],
    define: {
      'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY),
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modifyâfile watching is disabled to prevent flickering during agent edits.
      // Avoid collision with other local Vite instances.
      port: 5173,
      strictPort: false,
      hmr:
        process.env.DISABLE_HMR === 'true'
          ? false
          : {
              port: 24688,
            },
    },
  };
});
