import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const proxyOptions = {
  target: `http://127.0.0.1:${process.env.BACKEND_PORT || 80}`,
  changeOrigin: false,
  secure: true,
  ws: false,
};


// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: "localhost",
    port: process.env.FRONTEND_PORT as unknown as number,
    proxy: {
      "^/(\\?.*)?$": proxyOptions,
      "^/api(/|(\\?.*)?$)": proxyOptions,
    },
    // ref: https://vite.dev/config/server-options.html#server-allowedhosts
    allowedHosts: true,
  },
})
