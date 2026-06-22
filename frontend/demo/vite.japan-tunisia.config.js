import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  root: path.resolve(__dirname, 'japan-tunisia-src'),
  base: './',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '../src'),
      '@locales': path.resolve(__dirname, '../../locales'),
    },
  },
  build: {
    outDir: path.resolve(__dirname, 'japan-tunisia'),
    emptyOutDir: true,
  },
})

