/**
 * Vite 配置文件
 * 作用：告诉 Vite 怎么启动开发服务器、怎么打包项目。
 * - plugins: 加载 Vue 单文件组件(.vue)的编译插件
 * - resolve.alias: 配置 "@" 指向 src 目录，之后写 import 可以用 @/xxx 代替 ../../xxx
 */
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    open: false,
    // 开发时把 /api 请求代理到后端 FastAPI，前端不用关心后端地址。
    // 端口 8600：8000 在 Windows 的 Hyper-V/WSL 预留端口段里（7993-8092），bind 会失败。
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8600',
        changeOrigin: true,
      },
    },
    watch: {
      // Windows 下有些工具（含部分编辑器、脚本）会用"临时目录 + 重命名"的方式写文件，
      // 这些临时目录在写入瞬间被删掉时，文件监听器可能崩溃（EBUSY）。
      // 把它们排除出监听范围，开发服务器更稳。
      ignored: ['**/.*.tmpdir/**'],
    },
  },
})
