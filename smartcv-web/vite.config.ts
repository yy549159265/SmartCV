/**
 * Vite 配置文件
 * 作用：告诉 Vite 怎么启动开发服务器、怎么打包项目。
 * - plugins: 加载 Vue 单文件组件(.vue)的编译插件
 * - resolve.alias: 配置 "@" 指向 src 目录，之后写 import 可以用 @/xxx 代替 ../../xxx
 */
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端端口：默认 8700，和后端 main.py 的 SMARTCV_API_PORT 保持同一个变量。
// 注意：Windows 的 Hyper-V/WSL 会预留一些动态端口段，落在里面的端口 bind 会报
// WinError 10013（不是端口被占用）。查当前预留段：
//   netsh interface ipv4 show excludedportrange protocol=tcp
const apiPort = process.env.SMARTCV_API_PORT ?? '8700'

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
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${apiPort}`,
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
