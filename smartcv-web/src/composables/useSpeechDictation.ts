/**
 * 语音输入：两种识别方式共用同一套麦克风采集链路，在「高级设置 · 模拟面试」里切换。
 *
 * sherpa-onnx（默认）：getUserMedia → AudioContext → 低通滤波 → AudioWorklet 采集
 * → 重采样为 16kHz 单声道 Float32 PCM → WebSocket 发送。
 * partial 作为临时文本实时显示，final 落到目标输入框；录音不落盘。
 * 服务地址由 VITE_ASR_WS_URL 配置，未配置时按开发/生产环境取默认值。
 *
 * DeepSeek 非实时：同样的麦克风采集，但 PCM 先留在内存里；点停止（或录满 60 秒）
 * 后重采样并编码为 16-bit PCM WAV，multipart 上传到 DeepSeek ASR，
 * 拿到整段文字后写进目标输入框，随后释放音频数据。
 */

import {
  computed,
  onScopeDispose,
  onUnmounted,
  ref,
  type ComputedRef,
  type Ref,
} from 'vue'

import {
  DEEPSEEK_MAX_SECONDS,
  asrSettings,
  deepSeekAsrEndpoint,
  type AsrMode,
} from '@/composables/useAsrSettings'
import { message } from '@/utils/feedback'

/** 服务端要求的采样率；声道由 getUserMedia 的 channelCount=1 保证。 */
const ASR_SAMPLE_RATE = 16_000
/** 停止后等待最终结果的时限，超时后保留当前已识别文本。 */
const FINAL_TIMEOUT = 6_000
/** WebSocket 建连时限。 */
const CONNECT_TIMEOUT = 8_000
/** 麦克风持续静音多久后放弃本轮识别；静音不代表连接断开，需要单独兜住。 */
const MUTE_TIMEOUT = 10_000
const WORKLET_NAME = 'smartcv-pcm-collector'
/**
 * 工作线程攒够这么多采样点再回传，降低 postMessage 频率。
 * 48kHz 下 2048 点约 43ms，比 4096 点少一截上行延迟。
 */
const WORKLET_CHUNK_SIZE = 2048
/** 录音波形条数；每收到一块音频就更新一次，足够看出说话起伏。 */
const WAVEFORM_BARS = 14
/** 太短的录音不生成文件，直接提示重录。 */
const MIN_UPLOAD_SECONDS = 0.4

const FALLBACK_WS_URL = import.meta.env.DEV
  ? 'ws://127.0.0.1:6006'
  : 'wss://smart-cv.tech/asr'
const ASR_WS_URL = import.meta.env.VITE_ASR_WS_URL?.trim() || FALLBACK_WS_URL

/**
 * 在音频线程里把麦克风采样攒成块再发回主线程。
 * 只采集输入、不写输出，节点本身输出静音。
 */
const WORKLET_SOURCE = `
class PcmCollector extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buffer = new Float32Array(${WORKLET_CHUNK_SIZE})
    this.offset = 0
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel) return true

    let read = 0
    while (read < channel.length) {
      const count = Math.min(channel.length - read, this.buffer.length - this.offset)
      this.buffer.set(channel.subarray(read, read + count), this.offset)
      this.offset += count
      read += count

      if (this.offset === this.buffer.length) {
        const chunk = this.buffer
        this.port.postMessage(chunk, [chunk.buffer])
        this.buffer = new Float32Array(${WORKLET_CHUNK_SIZE})
        this.offset = 0
      }
    }
    return true
  }
}
registerProcessor('${WORKLET_NAME}', PcmCollector)
`

interface ServerMessage {
  type?: string
  text?: string
  is_final?: boolean
  final?: boolean
}

/**
 * 流式线性插值重采样器，跨音频块保留末尾采样点，避免块边界丢点/咔哒声。
 */
class StreamingResampler {
  private readonly step: number
  private position = 0
  private tail: Float32Array | null = null

  constructor(inputRate: number, outputRate: number) {
    this.step = inputRate / outputRate
  }

  process(chunk: Float32Array): Float32Array {
    if (chunk.length === 0) return new Float32Array(0)

    let input = chunk
    if (this.tail) {
      input = new Float32Array(this.tail.length + chunk.length)
      input.set(this.tail)
      input.set(chunk, this.tail.length)
    }

    // 输出点数必须从当前相位算起，否则跨块时会多吐出采样点、逐渐拉长时间轴。
    const count =
      this.position <= input.length - 1
        ? Math.floor((input.length - 1 - this.position) / this.step) + 1
        : 0
    const output = new Float32Array(count)
    let position = this.position
    for (let i = 0; i < output.length; i += 1) {
      const index = Math.floor(position)
      if (index >= input.length - 1) {
        output[i] = input[input.length - 1]
      } else {
        const fraction = position - index
        output[i] = input[index] + (input[index + 1] - input[index]) * fraction
      }
      position += this.step
    }

    // 下一块的第一个输出点需要上一块末尾的采样做左端点。
    const keepFrom = Math.min(Math.floor(position), input.length)
    this.tail = keepFrom < input.length ? input.slice(keepFrom) : null
    this.position = position - keepFrom
    return output
  }
}

/** 直接把两段话拼起来；只有两侧都是英文/数字时才补一个空格。 */
function appendText(base: string, extra: string): string {
  const text = extra.trim()
  if (!text) return base
  if (!base) return text
  return /[A-Za-z0-9]$/.test(base) && /^[A-Za-z0-9]/.test(text)
    ? `${base} ${text}`
    : `${base}${text}`
}

/** 把多块 PCM 按记录顺序拼成一整段；没有重采样需求时直接返回。 */
function mergePcm(chunks: Float32Array[]): Float32Array {
  let total = 0
  for (const chunk of chunks) total += chunk.length
  const merged = new Float32Array(total)
  let offset = 0
  for (const chunk of chunks) {
    merged.set(chunk, offset)
    offset += chunk.length
  }
  return merged
}

/**
 * 录音结束后的离线重采样：逐块喂给同一个 StreamingResampler，块边界仍然连续，
 * 不会因为分段处理而在拼接处丢采样点。
 */
function resamplePcm(chunks: Float32Array[], inputRate: number): Float32Array {
  if (!chunks.length) return new Float32Array(0)
  if (inputRate === ASR_SAMPLE_RATE) return mergePcm(chunks)
  const resampler = new StreamingResampler(inputRate, ASR_SAMPLE_RATE)
  return mergePcm(chunks.map((chunk) => resampler.process(chunk)))
}

/** 把 16kHz 单声道 Float32 采样编码成 16 位小端 PCM 的 WAV 文件。 */
function encodeWav(samples: Float32Array, sampleRate = ASR_SAMPLE_RATE): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const writeText = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i))
  }

  writeText(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeText(8, 'WAVE')
  writeText(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeText(36, 'data')
  view.setUint32(40, samples.length * 2, true)

  let offset = 44
  for (let i = 0; i < samples.length; i += 1) {
    const value = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true)
    offset += 2
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

/** 取一块音频里各段的均方根，换算成 0~1 的波形高度；和上一帧做平滑避免跳动。 */
function nextWaveform(chunk: Float32Array, previous: number[]): number[] {
  if (!chunk.length) return previous
  const bars: number[] = []
  const step = chunk.length / WAVEFORM_BARS
  for (let i = 0; i < WAVEFORM_BARS; i += 1) {
    const start = Math.min(chunk.length - 1, Math.floor(i * step))
    const end = Math.min(chunk.length, Math.max(start + 1, Math.floor((i + 1) * step)))
    let sum = 0
    for (let j = start; j < end; j += 1) sum += chunk[j] * chunk[j]
    const rms = Math.sqrt(sum / Math.max(1, end - start))
    const level = Math.min(1, Math.sqrt(rms) * 2.4)
    bars.push((previous[i] ?? 0) * 0.35 + level * 0.65)
  }
  return bars
}

function describeAsrHttpError(status: number): string {
  switch (status) {
    case 400:
      return '音频格式无法识别，请重试'
    case 401:
    case 403:
      return 'DeepSeek API Key 无效，请在「高级设置 · 模拟面试」中检查'
    case 408:
      return '音频上传超时，请检查网络后重试'
    case 413:
      return '录音文件过大，请缩短录音后重试'
    case 429:
      return '语音识别请求过多，请稍后再试'
    case 503:
    case 504:
      return '语音识别服务繁忙，请稍后再试'
    default:
      return `语音识别失败（HTTP ${status}），请稍后再试`
  }
}

function describeUploadError(error: unknown): string {
  if (error instanceof TypeError) {
    return '无法连接语音识别服务，请检查网络、接口地址，或确认接口允许浏览器跨域访问'
  }
  if (error instanceof Error && error.message) return error.message
  return '语音识别失败，请重试'
}

/** 把 getUserMedia 的常见拒绝原因换成用户能看懂的提示。 */
function describeMediaError(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return '麦克风权限未开启，请在浏览器地址栏允许后重试'
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return '没有检测到可用的麦克风，请检查设备后重试'
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return '麦克风被其他程序占用，请关闭后重试'
  }
  return '无法启动麦克风，请检查设备和权限后重试'
}

export function useSpeechDictation(target: Ref<string>): {
  isSupported: ComputedRef<boolean>
  isListening: Ref<boolean>
  /** DeepSeek 模式上传识别中；此时录音已结束，结果还没回来。 */
  isTranscribing: Ref<boolean>
  mode: ComputedRef<AsrMode>
  /** 录音波形（0~1），只在 DeepSeek 录音期间有值。 */
  waveform: Ref<number[]>
  /** 本次录音已进行秒数。 */
  elapsed: Ref<number>
  maxSeconds: number
  toggle: () => void
  stop: () => void
  /** 直接放弃本轮录音 / 上传（切题、跳转、离开作答时用）。 */
  cancel: () => void
} {
  const mode = computed<AsrMode>(() => asrSettings.value.mode)

  const isSupported = computed(() => {
    if (typeof window === 'undefined' || !window.isSecureContext) return false
    const audioReady = Boolean(
      navigator.mediaDevices &&
        typeof navigator.mediaDevices.getUserMedia === 'function' &&
        typeof AudioContext !== 'undefined' &&
        typeof AudioWorkletNode !== 'undefined',
    )
    if (!audioReady) return false
    // sherpa 依赖 WebSocket 流；DeepSeek 依赖 fetch / FormData 上传。
    if (mode.value === 'deepseek') {
      return typeof fetch === 'function' && typeof FormData !== 'undefined'
    }
    return typeof WebSocket !== 'undefined'
  })

  const isListening = ref(false)
  const isTranscribing = ref(false)
  const waveform = ref<number[]>([])
  const elapsed = ref(0)
  const maxSeconds = DEEPSEEK_MAX_SECONDS

  /** 本次录音实际使用的识别方式；录音过程中切换设置不会影响当前会话。 */
  let activeMode: AsrMode = 'sherpa'
  /** DeepSeek 录音的原始 PCM 分片与采样率，停止后统一重采样、编码。 */
  let pcmChunks: Float32Array[] = []
  let captureSampleRate = ASR_SAMPLE_RATE
  let elapsedTimer: number | undefined
  let maxDurationTimer: number | undefined
  let uploadAbort: AbortController | null = null

  let socket: WebSocket | null = null
  let cancelConnect: (() => void) | null = null
  let stream: MediaStream | null = null
  let audioContext: AudioContext | null = null
  let sourceNode: MediaStreamAudioSourceNode | null = null
  let filters: BiquadFilterNode[] = []
  let workletNode: AudioWorkletNode | null = null
  let silentGain: GainNode | null = null
  let resampler: StreamingResampler | null = null
  let finalTimer: number | undefined

  let sessionId = 0
  let active = false
  let finishing = false

  /** 媒体轨事件解绑函数；释放音频前统一移除，避免回调打到已结束的会话。 */
  let detachTracks: Array<() => void> = []
  let mutedNotified = false
  let muteTimer: number | undefined

  let baseText = ''
  let finalText = ''
  let interimText = ''

  function render(): void {
    target.value = appendText(appendText(baseText, finalText), interimText)
  }

  function clearFinalTimer(): void {
    if (finalTimer !== undefined) {
      window.clearTimeout(finalTimer)
      finalTimer = undefined
    }
  }

  function clearMuteTimer(): void {
    if (muteTimer !== undefined) {
      window.clearTimeout(muteTimer)
      muteTimer = undefined
    }
  }

  function resetWaveform(): void {
    waveform.value = []
    elapsed.value = 0
  }

  function clearDeepSeekTimers(): void {
    if (elapsedTimer !== undefined) {
      window.clearInterval(elapsedTimer)
      elapsedTimer = undefined
    }
    if (maxDurationTimer !== undefined) {
      window.clearTimeout(maxDurationTimer)
      maxDurationTimer = undefined
    }
  }

  /** 录音开始后启动计时；到 60 秒自动结束并按正常流程上传。 */
  function beginDeepSeekCapture(): void {
    pcmChunks = []
    resetWaveform()
    const startedAt = Date.now()
    elapsedTimer = window.setInterval(() => {
      elapsed.value = Math.min(
        DEEPSEEK_MAX_SECONDS,
        Math.floor((Date.now() - startedAt) / 1000),
      )
    }, 200)
    maxDurationTimer = window.setTimeout(() => {
      if (active && activeMode === 'deepseek') finishDeepSeek()
    }, DEEPSEEK_MAX_SECONDS * 1000)
  }

  /** 结束 DeepSeek 录音：停麦克风，重采样、编码 WAV，再上传识别。 */
  function finishDeepSeek(): void {
    if (!active) return
    const token = sessionId
    active = false
    isListening.value = false
    clearDeepSeekTimers()
    releaseAudio()

    const chunks = pcmChunks
    pcmChunks = []
    const inputRate = captureSampleRate
    resetWaveform()

    if (!chunks.length) {
      message.warning('没有录到声音，请靠近麦克风后重试')
      return
    }

    let samples: Float32Array
    try {
      samples = resamplePcm(chunks, inputRate || ASR_SAMPLE_RATE)
    } catch {
      message.warning('录音处理失败，请重试')
      return
    }

    // 后台标签页的定时器可能被节流，按采样点再截一次，保证文件不超过 60 秒。
    const maxSamples = DEEPSEEK_MAX_SECONDS * ASR_SAMPLE_RATE
    if (samples.length > maxSamples) samples = samples.slice(0, maxSamples)

    if (samples.length < ASR_SAMPLE_RATE * MIN_UPLOAD_SECONDS) {
      message.warning('录音太短，请说完再结束')
      return
    }

    const audio = encodeWav(samples)
    void uploadDeepSeek(audio, token)
  }

  /** 上传 WAV 到 DeepSeek ASR；成功后把整段文字追加到目标输入框并释放音频。 */
  async function uploadDeepSeek(audio: Blob, token: number): Promise<void> {
    const { baseUrl, apiKey } = asrSettings.value.deepseek
    const key = apiKey.trim()
    if (!key) {
      message.warning('请先在「高级设置 · 模拟面试」里填写 DeepSeek API Key')
      return
    }

    const controller = new AbortController()
    uploadAbort?.abort()
    uploadAbort = controller
    isTranscribing.value = true

    const form = new FormData()
    form.append('file', audio, `speech-${Date.now()}.wav`)

    try {
      const response = await fetch(deepSeekAsrEndpoint(baseUrl), {
        method: 'POST',
        headers: { Authorization: `Bearer ${key}` },
        body: form,
        signal: controller.signal,
      })
      if (!response.ok) {
        message.warning(describeAsrHttpError(response.status))
        return
      }

      const payload = (await response.json()) as { text?: unknown }
      if (token !== sessionId) return
      const text = typeof payload.text === 'string' ? payload.text.trim() : ''
      if (!text) {
        message.warning('没有识别到语音内容，请重试')
        return
      }
      target.value = appendText(target.value, text)
    } catch (error) {
      if (controller.signal.aborted || token !== sessionId) return
      message.warning(describeUploadError(error))
    } finally {
      // 上传结束（无论成败）立即丢掉音频：表单字段和 PCM 分片都不再保留。
      // 会话已换掉时不要动 pcmChunks，那可能已经是下一轮录音的数据。
      form.delete('file')
      if (token === sessionId) {
        pcmChunks = []
        isTranscribing.value = false
      }
      if (uploadAbort === controller) uploadAbort = null
    }
  }

  /** 放弃正在上传的识别结果，并让还在路上的响应失效。 */
  function cancelUpload(): void {
    sessionId += 1
    uploadAbort?.abort()
    uploadAbort = null
    isTranscribing.value = false
  }

  function detachTrackListeners(): void {
    detachTracks.forEach((off) => off())
    detachTracks = []
    mutedNotified = false
    clearMuteTimer()
  }

  function releaseAudio(): void {
    detachTrackListeners()
    if (workletNode) {
      workletNode.port.onmessage = null
      workletNode.port.close()
      workletNode.disconnect()
      workletNode = null
    }
    filters.forEach((filter) => filter.disconnect())
    filters = []
    sourceNode?.disconnect()
    sourceNode = null
    silentGain?.disconnect()
    silentGain = null
    resampler = null
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
    if (audioContext) {
      const context = audioContext
      audioContext = null
      if (context.state !== 'closed') void context.close().catch(() => undefined)
    }
  }

  function closeSocket(): void {
    const current = socket
    socket = null
    finishing = false
    clearFinalTimer()

    const cancel = cancelConnect
    cancelConnect = null
    if (current) {
      current.onopen = null
      current.onmessage = null
      current.onerror = null
      current.onclose = null
    }
    cancel?.()
    if (
      current &&
      (current.readyState === WebSocket.CONNECTING || current.readyState === WebSocket.OPEN)
    ) {
      try {
        current.close()
      } catch {
        // 连接已经不可用，无需额外处理
      }
    }
  }

  /**
   * 跟踪麦克风轨状态：设备拔出/权限撤销时 `ended`，暂时不可用时 `mute`。
   * 这些情况都不会让 WebSocket 断开，必须单独发现并停止采集。
   */
  function watchTracks(media: MediaStream, token: number): void {
    detachTrackListeners()
    media.getAudioTracks().forEach((track) => {
      const onEnded = () => {
        if (!active || token !== sessionId) return
        abortListening('麦克风已断开，语音输入已停止')
      }
      const onMute = () => {
        if (!active || token !== sessionId || mutedNotified) return
        // 切到后台时部分浏览器也会把轨道静音，交给 visibilitychange 统一处理。
        if (document.visibilityState === 'hidden') return
        mutedNotified = true
        message.warning('麦克风暂时不可用，请检查设备或权限')
        clearMuteTimer()
        muteTimer = window.setTimeout(() => {
          muteTimer = undefined
          if (!active || token !== sessionId) return
          abortListening('麦克风持续不可用，语音输入已停止')
        }, MUTE_TIMEOUT)
      }
      const onUnmute = () => {
        if (token !== sessionId) return
        clearMuteTimer()
        if (!mutedNotified) return
        mutedNotified = false
        if (active) message.success('麦克风已恢复，可以继续说话')
      }

      track.addEventListener('ended', onEnded)
      track.addEventListener('mute', onMute)
      track.addEventListener('unmute', onUnmute)
      detachTracks.push(() => {
        track.removeEventListener('ended', onEnded)
        track.removeEventListener('mute', onMute)
        track.removeEventListener('unmute', onUnmute)
      })
    })
  }

  /** 异常中止：放弃本轮识别并彻底释放麦克风与连接，已识别文字保留在输入框。 */
  function abortListening(notice: string): void {
    const wasActive = active
    sessionId += 1
    active = false
    isListening.value = false
    isTranscribing.value = false
    clearDeepSeekTimers()
    pcmChunks = []
    uploadAbort?.abort()
    uploadAbort = null
    resetWaveform()
    commitInterim()
    releaseAudio()
    closeSocket()
    if (wasActive && notice) message.warning(notice)
  }

  function commitInterim(): void {
    if (!interimText) return
    finalText = appendText(finalText, interimText)
    interimText = ''
    render()
  }

  /** 连接在录音或等待最终结果时断开：停止采集、恢复按钮并提示，已识别文字保留。 */
  function handleSocketClosed(): void {
    const wasActive = active
    if (wasActive) {
      // 连接已经没了，作废本轮会话，避免残留的异步回调继续采集。
      sessionId += 1
      active = false
      isListening.value = false
      commitInterim()
      releaseAudio()
    }
    if (finishing) {
      commitInterim()
      finishing = false
    }
    clearFinalTimer()
    if (wasActive) message.warning('语音识别服务连接已断开，请稍后重试')
  }

  function handleServerMessage(event: MessageEvent): void {
    if (typeof event.data !== 'string') return
    let payload: ServerMessage
    try {
      payload = JSON.parse(event.data) as ServerMessage
    } catch {
      return
    }
    if (!payload || typeof payload !== 'object') return

    const text = typeof payload.text === 'string' ? payload.text.trim() : ''
    const isFinal =
      payload.type === 'final' || payload.is_final === true || payload.final === true

    if (isFinal) {
      if (text) finalText = appendText(finalText, text)
      interimText = ''
      render()
      if (finishing) closeSocket()
      return
    }

    // partial 是当前这句话的完整临时文本，直接替换而不是追加。
    if (typeof payload.text !== 'string' || !active) return
    interimText = text
    render()
  }

  function connectSocket(token: number): Promise<WebSocket> {
    return new Promise((resolve, reject) => {
      let current: WebSocket
      try {
        current = new WebSocket(ASR_WS_URL)
      } catch {
        reject(new Error('语音识别服务地址无效，请检查配置'))
        return
      }

      socket = current
      current.binaryType = 'arraybuffer'

      let settled = false
      let timer: number | undefined

      const settle = (error?: Error) => {
        if (settled) return
        settled = true
        if (timer !== undefined) window.clearTimeout(timer)
        if (cancelConnect === cancel) cancelConnect = null

        if (!error) {
          resolve(current)
          return
        }

        current.onopen = null
        current.onmessage = null
        current.onerror = null
        current.onclose = null
        if (socket === current) socket = null
        if (
          current.readyState === WebSocket.CONNECTING ||
          current.readyState === WebSocket.OPEN
        ) {
          try {
            current.close()
          } catch {
            // 连接已经不可用，无需额外处理
          }
        }
        reject(error)
      }

      const cancel = () => settle(new Error('语音输入已取消'))
      cancelConnect = cancel

      timer = window.setTimeout(
        () => settle(new Error('语音识别服务连接超时，请检查网络后重试')),
        CONNECT_TIMEOUT,
      )

      current.onopen = () => {
        if (!active || token !== sessionId) {
          cancel()
          return
        }
        current.onmessage = (event: MessageEvent) => {
          if (socket === current) handleServerMessage(event)
        }
        settle()
      }

      current.onerror = () => {
        settle(new Error('无法连接语音识别服务，请检查网络后重试'))
      }

      current.onclose = () => {
        if (!settled) {
          settle(new Error('语音识别服务连接失败，请稍后重试'))
          return
        }
        if (socket !== current) return
        socket = null
        handleSocketClosed()
      }
    })
  }

  function sendPcm(samples: Float32Array): void {
    const current = socket
    if (!current || current.readyState !== WebSocket.OPEN || samples.length === 0) return
    try {
      current.send(samples.buffer)
    } catch {
      // 连接状态变化由 onclose 统一处理
    }
  }

  function requestFinal(): void {
    const current = socket
    if (!current || current.readyState !== WebSocket.OPEN) {
      closeSocket()
      return
    }

    finishing = true
    try {
      current.send(JSON.stringify({ type: 'end' }))
    } catch {
      closeSocket()
      return
    }

    clearFinalTimer()
    finalTimer = window.setTimeout(() => {
      finalTimer = undefined
      closeSocket()
    }, FINAL_TIMEOUT)
  }

  async function startAudio(token: number, context: AudioContext): Promise<void> {
    let media: MediaStream
    try {
      media = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
    } catch (error) {
      throw new Error(describeMediaError(error))
    }

    if (!active || token !== sessionId) {
      media.getTracks().forEach((track) => track.stop())
      return
    }
    stream = media
    watchTracks(media, token)

    try {
      await context.resume()
      if (!active || token !== sessionId) return

      const source = context.createMediaStreamSource(media)
      sourceNode = source

      // 降采样前先低通，避免 8kHz 以上的成分折叠回语音频段。
      const cutoff = Math.min(ASR_SAMPLE_RATE * 0.45, context.sampleRate * 0.45)
      let tail: AudioNode = source
      for (let i = 0; i < 2; i += 1) {
        const filter = context.createBiquadFilter()
        filter.type = 'lowpass'
        filter.frequency.value = cutoff
        filter.Q.value = Math.SQRT1_2
        tail.connect(filter)
        tail = filter
        filters.push(filter)
      }

      const moduleUrl = URL.createObjectURL(
        new Blob([WORKLET_SOURCE], { type: 'text/javascript' }),
      )
      try {
        await context.audioWorklet.addModule(moduleUrl)
      } finally {
        URL.revokeObjectURL(moduleUrl)
      }
      if (!active || token !== sessionId) return

      const node = new AudioWorkletNode(context, WORKLET_NAME, {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      })
      workletNode = node
      captureSampleRate = context.sampleRate
      if (activeMode === 'sherpa') {
        resampler = new StreamingResampler(context.sampleRate, ASR_SAMPLE_RATE)
      }
      node.port.onmessage = (event: MessageEvent) => {
        if (!active || token !== sessionId) return
        const chunk = event.data as Float32Array

        if (activeMode === 'deepseek') {
          // 非实时模式：先把 PCM 留在内存里，同时用这块音频驱动录音波形。
          pcmChunks.push(chunk)
          waveform.value = nextWaveform(chunk, waveform.value)
          return
        }

        const pcm = resampler?.process(chunk)
        if (pcm) sendPcm(pcm)
      }

      // 工作节点必须接出去才会被驱动；经 0 增益节点输出，避免麦克风回放。
      const silent = context.createGain()
      silent.gain.value = 0
      silentGain = silent
      tail.connect(node)
      node.connect(silent)
      silent.connect(context.destination)
    } catch {
      throw new Error('语音识别初始化失败，请刷新页面后重试')
    }
  }

  async function start(): Promise<void> {
    if (active) return
    if (!isSupported.value) {
      message.warning('当前浏览器不支持语音输入，请使用 Chrome 或 Edge')
      return
    }

    const requestedMode = asrSettings.value.mode
    if (requestedMode === 'deepseek' && !asrSettings.value.deepseek.apiKey.trim()) {
      message.warning('请先在「高级设置 · 模拟面试」里填写 DeepSeek API Key')
      return
    }

    // 页面可能刚从 bfcache 恢复，dispose 已移除监听，这里补回来。
    bindPageEvents()
    cancelUpload()
    releaseAudio()
    closeSocket()
    resetWaveform()

    let context: AudioContext
    try {
      context = new AudioContext()
    } catch {
      message.warning('当前浏览器无法启动音频处理，请刷新页面后重试')
      return
    }
    audioContext = context
    if (context.state === 'suspended') void context.resume().catch(() => undefined)

    activeMode = requestedMode
    baseText = target.value
    finalText = ''
    interimText = ''
    active = true
    isListening.value = true
    const token = ++sessionId

    try {
      if (activeMode === 'sherpa') await connectSocket(token)
      if (!active || token !== sessionId) return
      await startAudio(token, context)
      if (!active || token !== sessionId) return
      if (activeMode === 'deepseek') beginDeepSeekCapture()
    } catch (error) {
      if (!active || token !== sessionId) return
      active = false
      isListening.value = false
      clearDeepSeekTimers()
      pcmChunks = []
      resetWaveform()
      releaseAudio()
      closeSocket()
      message.warning(error instanceof Error ? error.message : '语音识别启动失败，请重试')
    }
  }

  function stop(): void {
    if (!active) return
    if (activeMode === 'deepseek') {
      finishDeepSeek()
      return
    }
    active = false
    isListening.value = false
    releaseAudio()
    requestFinal()
  }

  function cancel(): void {
    if (!active && !finishing && !isTranscribing.value) return
    abortListening('')
  }

  function toggle(): void {
    if (active) stop()
    else void start()
  }

  /** 页面进入后台就不再占用麦克风；回到前台由用户重新点击开始。 */
  function handleVisibilityChange(): void {
    if (document.visibilityState !== 'hidden') return
    // DeepSeek 录音切后台时直接结束并上传，避免把已经录好的话丢掉。
    if (active && activeMode === 'deepseek') {
      finishDeepSeek()
      return
    }
    if (!active && !finishing) return
    abortListening('页面已切到后台，语音输入已停止')
  }

  /** 绑定页面级监听；重复调用不会重复注册。 */
  function bindPageEvents(): void {
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange)
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('pagehide', dispose)
    }
  }

  /** 离开页面或组件销毁：作废会话、关连接、停麦克风；可重复调用。 */
  function dispose(): void {
    sessionId += 1
    active = false
    isListening.value = false
    isTranscribing.value = false
    clearDeepSeekTimers()
    pcmChunks = []
    uploadAbort?.abort()
    uploadAbort = null
    resetWaveform()
    releaseAudio()
    closeSocket()
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
    if (typeof window !== 'undefined') {
      window.removeEventListener('pagehide', dispose)
    }
  }

  bindPageEvents()
  // 组件卸载时 onScopeDispose 也会触发，dispose 幂等，两条路径都兜住。
  onUnmounted(dispose)
  onScopeDispose(dispose)

  return {
    isSupported,
    isListening,
    isTranscribing,
    mode,
    waveform,
    elapsed,
    maxSeconds,
    toggle,
    stop,
    cancel,
  }
}
