/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 语音识别 WebSocket 服务地址；未配置时按开发/生产环境取默认值 */
  readonly VITE_ASR_WS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
