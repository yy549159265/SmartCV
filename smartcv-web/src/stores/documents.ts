/**
 * 简历库（备份文件夹）状态管理。
 *
 * 设计：
 *   - 备份文件夹是「简历库」：一份简历 = 一个 .json 文件，文件名 = 简历名；
 *   - 当前正在编辑的那份简历由 currentFile 指向；
 *   - 文件夹句柄本身存在 IndexedDB（见 utils/fs/directoryHandle），
 *     这里只把文件夹名、文件索引、当前文件名等轻量信息缓存到 localStorage，
 *     没授权时也能先把列表显示出来；
 *   - 所有会读写文件夹的操作走 exclusive 队列，避免「改名」和「切换文档」
 *     同时进行时互相踩到。
 */
import { defineStore } from 'pinia'
import { useResumeStore } from '@/stores/resume'
import { useOptimizeStore } from '@/stores/optimize'
import { resumeName, resumeFilename } from '@/composables/useResumeName'
import { dialog, message } from '@/utils/feedback'
import { fileTitle, sanitizeFileTitle } from '@/utils/filename'
import {
  clearDirectoryHandle,
  loadDirectoryHandle,
  pickDirectory,
  queryDirPermission,
  requestDirPermission,
  saveDirectoryHandle,
  supportsDirectoryPicker,
} from '@/utils/fs/directoryHandle'
import {
  findAvailableName,
  folderFileExists,
  getFolderFileInfo,
  listResumeFiles,
  readResumeJson,
  removeFolderFile,
  writeBlobToFolder,
  writeResumeJson,
  type BackupFileInfo,
} from '@/utils/fs/backupFolder'

/** 文件夹状态：不支持 / 未绑定 / 需要授权 / 已连接 / 权限被拒 */
export type BackupStatus = 'unsupported' | 'unbound' | 'needs-permission' | 'ready' | 'denied'

/** 新建文档的结果（invalid = 数据不是合法简历；cancelled = 用户在重名弹窗里取消） */
export type CreateDocumentResult = 'ok' | 'invalid' | 'cancelled'

/** 重命名结果：conflict 表示目标文件已存在，由 UI 决定覆盖还是保留两份 */
export interface RenameDocumentResult {
  ok: boolean
  conflict?: string
  name?: string
}

const LS_FOLDER_NAME = 'smartcv-backup-folder'
const LS_INDEX = 'smartcv-backup-index'
const LS_LAST_SYNC = 'smartcv-backup-last-sync'
const LS_CURRENT = 'smartcv-resume-current'
const LS_CURRENT_MTIME = 'smartcv-backup-current-mtime'
const LS_PENDING = 'smartcv-backup-pending'

/** 文件 mtime 与上次记录之间的容差（毫秒），避免把自家刚写的文件误判成外部修改 */
const MTIME_TOLERANCE = 2000

/** 文件夹句柄（非响应式；需要持久化的只有它的 IndexedDB 副本） */
let dir: FileSystemDirectoryHandle | null = null
/** 自动保存防抖计时器 */
let saveTimer: ReturnType<typeof setTimeout> | null = null
/** 写文件的串行队列：同一时间只写一个文件，避免 createWritable 互相覆盖 */
let writeChain: Promise<unknown> = Promise.resolve()
/** 文件夹读写操作的串行队列：切换 / 改名 / 新建 / 同步不并发 */
let opChain: Promise<unknown> = Promise.resolve()
/** 避免同一条写入错误反复弹 toast */
let writeErrorShown = false
/** 避免外部修改提示反复弹 */
let externalWarnShown = false
/**
 * 最近一次与文件夹同步（读入或写入）的简历内容序列化。
 * 自动保存只写真正变化过的内容：打开文档、撤销回已保存状态时不会反复写盘。
 */
let lastSyncedJson: string | null = null

/** 把操作串起来执行（前一个失败也继续执行下一个） */
function exclusive<T>(fn: () => Promise<T>): Promise<T> {
  const next = opChain.then(fn, fn)
  opChain = next.then(
    () => undefined,
    () => undefined,
  )
  return next
}

function resumeSnapshot(): unknown {
  return JSON.parse(JSON.stringify(useResumeStore().resume))
}

/** 当前简历内容（含新建时重新生成的 id）的序列化 */
function currentResumeJson(): string {
  return JSON.stringify(useResumeStore().resume)
}

/** 替换当前简历，并把「已同步内容」更新为替换后的版本（避免刚打开就触发一次写盘） */
function replaceResume(data: unknown): boolean {
  const resumeStore = useResumeStore()
  const ok = resumeStore.openResume(data)
  if (ok) lastSyncedJson = JSON.stringify(resumeStore.resume)
  return ok
}

function errorText(err: unknown): string {
  if (err instanceof DOMException) {
    if (err.name === 'NotAllowedError') return '没有文件夹访问权限'
    if (err.name === 'NoModificationAllowedError') return '文件正被其他程序占用'
    if (err.name === 'NotFoundError') return '文件不存在'
    return err.message || err.name
  }
  return err instanceof Error ? err.message : String(err)
}

/** 简单确认框：返回用户是否点了“确定” */
function confirmAction(options: {
  title: string
  content: string
  positiveText: string
  negativeText: string
}): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false
    const finish = (value: boolean) => {
      if (settled) return
      settled = true
      resolve(value)
    }
    dialog.warning({
      title: options.title,
      content: options.content,
      positiveText: options.positiveText,
      negativeText: options.negativeText,
      onPositiveClick: () => finish(true),
      onNegativeClick: () => finish(false),
      onClose: () => finish(false),
      onMaskClick: () => finish(false),
    })
  })
}

/** 读取上次缓存的文件索引（未授权时也能先显示列表） */
function readCachedIndex(): BackupFileInfo[] {
  try {
    const raw = localStorage.getItem(LS_INDEX)
    if (!raw) return []
    const list = JSON.parse(raw)
    if (!Array.isArray(list)) return []
    return list
      .filter((item): item is BackupFileInfo => {
        return (
          item &&
          typeof item === 'object' &&
          typeof (item as BackupFileInfo).name === 'string' &&
          typeof (item as BackupFileInfo).mtime === 'number'
        )
      })
      .map((item) => ({
        name: item.name,
        title: typeof item.title === 'string' ? item.title : fileTitle(item.name),
        mtime: item.mtime,
        size: typeof item.size === 'number' ? item.size : 0,
      }))
  } catch {
    return []
  }
}

export const useDocumentsStore = defineStore('documents', {
  state: () => ({
    status: 'unbound' as BackupStatus,
    /** 文件夹显示名（浏览器只给 name，拿不到完整路径） */
    folderName: localStorage.getItem(LS_FOLDER_NAME) ?? '',
    /** 文件夹里的 JSON 简历列表 */
    files: readCachedIndex(),
    /** 当前正在编辑的文件名（如 张三-前端.json） */
    currentFile: localStorage.getItem(LS_CURRENT) || null,
    /** 最近一次同步时间 */
    lastSyncAt: Number(localStorage.getItem(LS_LAST_SYNC) || 0),
    /** 当前文件上次被本应用读到 / 写入时的 mtime，用于外部修改检测 */
    lastKnownMtime: Number(localStorage.getItem(LS_CURRENT_MTIME) || 0),
    /** 检测到文件被外部修改（自动保存暂停，等用户点同步处理） */
    externalChanged: false,
    /** 同步 / 写入进行中 */
    busy: false,
    /** 正在切换文档：此期间的自动保存要跳过，避免把旧内容写进新文件 */
    switching: false,
    initialized: false,
  }),

  getters: {
    /** 是否选过文件夹（不管当前有没有权限） */
    isBound: (state): boolean => state.folderName !== '',
    /** 是否能在编辑器里浏览 / 打开文件 */
    canBrowse: (state): boolean => state.status === 'ready' || state.status === 'needs-permission',
    /** 当前简历名（没有当前文件时为空） */
    currentTitle: (state): string => (state.currentFile ? fileTitle(state.currentFile) : ''),
  },

  actions: {
    /* ==================== 初始化 / 绑定 ==================== */

    /** 应用启动时调用一次：取回句柄、查询权限、恢复当前文件 */
    async init(): Promise<void> {
      if (this.initialized) return
      this.initialized = true

      if (!supportsDirectoryPicker()) {
        this.status = 'unsupported'
        this.files = []
        return
      }

      const handle = await loadDirectoryHandle()
      if (!handle) {
        this.status = 'unbound'
        this.folderName = ''
        this.files = []
        localStorage.removeItem(LS_FOLDER_NAME)
        return
      }

      dir = handle
      this.folderName = handle.name
      localStorage.setItem(LS_FOLDER_NAME, handle.name)

      const permission = await queryDirPermission(handle)
      if (permission !== 'granted') {
        this.status = permission === 'denied' ? 'denied' : 'needs-permission'
        return
      }

      this.status = 'ready'
      await this.refreshFiles()
      await this.restoreCurrentFromFolder()
    },

    /** 选择文件夹：选中即持久化句柄，不需要先点同步 */
    async bindFolder(): Promise<boolean> {
      if (!supportsDirectoryPicker()) {
        this.status = 'unsupported'
        message.warning('当前浏览器不支持选择文件夹，请使用 Chrome 或 Edge')
        return false
      }
      try {
        const handle = await pickDirectory()
        if (!handle) return false

        // 重新选的是不是同一个文件夹（同一个文件夹可以保留当前文件指针）
        const previous = dir
        const sameFolder = previous
          ? await previous.isSameEntry(handle).catch(() => false)
          : false

        dir = handle
        await saveDirectoryHandle(handle)

        this.folderName = handle.name
        localStorage.setItem(LS_FOLDER_NAME, handle.name)

        const permission = await queryDirPermission(handle)
        this.status =
          permission === 'granted' ? 'ready' : permission === 'denied' ? 'denied' : 'needs-permission'

        // 换成另一个文件夹：当前文件指针作废（内容仍在内存里，下次同步会写入新文件夹）
        if (!sameFolder) this.clearCurrentFile()

        if (this.status === 'ready') {
          await this.refreshFiles()
          // 同一个文件夹里当前文件被删掉 / 改名：也清掉指针
          const currentExists =
            this.currentFile != null &&
            this.files.some((f) => f.name.toLowerCase() === this.currentFile!.toLowerCase())
          if (this.currentFile && !currentExists) this.clearCurrentFile()
        }
        return true
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return false
        message.error(`选择文件夹失败：${errorText(err)}`)
        return false
      }
    },

    /** 断开备份文件夹：只清句柄和索引，不删除任何文件 */
    async unbindFolder(): Promise<void> {
      await clearDirectoryHandle()
      dir = null
      if (saveTimer) {
        clearTimeout(saveTimer)
        saveTimer = null
      }
      lastSyncedJson = null
      this.folderName = ''
      this.files = []
      this.currentFile = null
      this.lastKnownMtime = 0
      this.lastSyncAt = 0
      this.externalChanged = false
      this.status = supportsDirectoryPicker() ? 'unbound' : 'unsupported'
      localStorage.removeItem(LS_FOLDER_NAME)
      localStorage.removeItem(LS_INDEX)
      localStorage.removeItem(LS_LAST_SYNC)
      localStorage.removeItem(LS_CURRENT)
      localStorage.removeItem(LS_CURRENT_MTIME)
      localStorage.removeItem(LS_PENDING)
    },

    /** 申请 / 恢复文件夹权限（必须在用户点击里调用） */
    async ensurePermission(): Promise<boolean> {
      if (!dir) {
        dir = await loadDirectoryHandle()
        if (!dir) {
          this.status = 'unbound'
          return false
        }
      }

      let permission = await queryDirPermission(dir)
      if (permission === 'prompt') {
        permission = await requestDirPermission(dir)
      }

      this.status =
        permission === 'granted' ? 'ready' : permission === 'denied' ? 'denied' : 'needs-permission'
      return permission === 'granted'
    },

    /** 重新扫描文件夹 */
    async refreshFiles(): Promise<void> {
      if (!dir) return
      try {
        this.files = await listResumeFiles(dir)
        this.lastSyncAt = Date.now()
        localStorage.setItem(LS_LAST_SYNC, String(this.lastSyncAt))
        localStorage.setItem(LS_INDEX, JSON.stringify(this.files))
      } catch (err) {
        message.error(`读取备份文件夹失败：${errorText(err)}`)
      }
    },

    /** 只有已连接时才刷新（编辑器下拉打开时用，避免未授权时弹错） */
    async refreshIfReady(): Promise<void> {
      if (this.status === 'ready') await this.refreshFiles()
    },

    /* ==================== 当前文件指针 ==================== */

    setCurrentFile(name: string, mtime: number): void {
      this.currentFile = name
      this.lastKnownMtime = mtime
      localStorage.setItem(LS_CURRENT, name)
      localStorage.setItem(LS_CURRENT_MTIME, String(mtime))
    },

    clearCurrentFile(): void {
      this.currentFile = null
      this.lastKnownMtime = 0
      lastSyncedJson = null
      localStorage.removeItem(LS_CURRENT)
      localStorage.removeItem(LS_CURRENT_MTIME)
    },

    /* ==================== 打开 / 新建 / 导入 ==================== */

    /**
     * 打开文件夹里的一份简历。
     * 切换前先把当前文档的修改 flush 掉；写不进去时问用户是否仍要切换。
     */
    openFile(name: string): Promise<boolean> {
      return exclusive(async () => {
        if (!this.isBound) return false
        if (!(await this.ensurePermission())) {
          message.warning('没有文件夹访问权限，请重新授权')
          return false
        }
        if (!dir) return false

        const saved = await this.flush()
        if (!saved) {
          const go = await confirmAction({
            title: '当前修改尚未写入文件夹',
            content: '切换后当前修改可能丢失（浏览器缓存里仍会保留一份）。仍要切换吗？',
            positiveText: '仍要切换',
            negativeText: '取消',
          })
          if (!go) return false
        }

        try {
          const info = await getFolderFileInfo(dir, name)
          if (!info) {
            message.error('文件不存在，可能已被重命名或删除')
            await this.refreshFiles()
            return false
          }

          const data = await readResumeJson(dir, info.name)
          const resumeStore = useResumeStore()
          if (!resumeStore.canOpenResume(data)) {
            message.error(`「${info.name}」不是合法的简历 JSON`)
            return false
          }

          // 先切换指针再替换数据：自动保存只会写向新文件
          this.switching = true
          try {
            this.setCurrentFile(info.name, info.mtime)
            replaceResume(data)
            resumeName.value = fileTitle(info.name)
            this.externalChanged = false
            externalWarnShown = false
            useOptimizeStore().clearMessages()
          } finally {
            this.switching = false
          }
          return true
        } catch (err) {
          message.error(`打开失败：${errorText(err)}`)
          return false
        }
      })
    },

    /** 新建空白简历；绑定文件夹时立即写一个 新简历.json */
    createBlank(): Promise<CreateDocumentResult> {
      return exclusive<CreateDocumentResult>(async () => {
        if (!this.isBound) {
          this.switching = true
          try {
            replaceResume([])
            resumeName.value = '我的简历'
            this.clearCurrentFile()
          } finally {
            this.switching = false
          }
          useOptimizeStore().clearMessages()
          return 'ok'
        }

        if (!(await this.ensurePermission()) || !dir) {
          this.switching = true
          try {
            replaceResume([])
            resumeName.value = '新简历'
            this.clearCurrentFile()
            localStorage.setItem(LS_PENDING, '1')
          } finally {
            this.switching = false
          }
          useOptimizeStore().clearMessages()
          message.warning('文件夹未授权，新简历先保存在浏览器；授权后再同步')
          return 'ok'
        }

        // 先把当前这份简历的未保存修改写回旧文件，再切到新简历
        await this.flush()

        try {
          const target = await findAvailableName(dir, '新简历')
          const mtime = await writeResumeJson(dir, target, [])
          this.switching = true
          try {
            this.setCurrentFile(target, mtime)
            replaceResume([])
            resumeName.value = fileTitle(target)
            this.externalChanged = false
            useOptimizeStore().clearMessages()
          } finally {
            this.switching = false
          }
          await this.refreshFiles()
          return 'ok'
        } catch (err) {
          // 写盘失败仍然让用户先编辑空白简历，修改留在浏览器缓存里
          this.switching = true
          try {
            replaceResume([])
            resumeName.value = '新简历'
            this.clearCurrentFile()
            localStorage.setItem(LS_PENDING, '1')
          } finally {
            this.switching = false
          }
          useOptimizeStore().clearMessages()
          message.error(`新建失败：${errorText(err)}（已改为保存在浏览器）`)
          return 'ok'
        }
      })
    },

    /**
     * 创建一份新文档（导入 PDF/Word、导入 JSON、加载示例共用）。
     * - 已绑定文件夹：写一个新 JSON 文件并设为当前文档；
     * - 未绑定 / 未授权：只替换内存里的简历，等授权后同步。
     */
    createDocument(
      data: unknown,
      suggestedTitle: string,
      options: { conflict?: 'ask' | 'unique' } = {},
    ): Promise<CreateDocumentResult> {
      return exclusive<CreateDocumentResult>(async () => {
        const resumeStore = useResumeStore()
        if (!resumeStore.canOpenResume(data)) return 'invalid'

        const title = sanitizeFileTitle(suggestedTitle, '我的简历')

        if (!this.isBound) {
          this.switching = true
          try {
            replaceResume(data)
            resumeName.value = title
            this.clearCurrentFile()
          } finally {
            this.switching = false
          }
          useOptimizeStore().clearMessages()
          return 'ok'
        }

        if (!(await this.ensurePermission()) || !dir) {
          this.switching = true
          try {
            replaceResume(data)
            resumeName.value = title
            this.clearCurrentFile()
            localStorage.setItem(LS_PENDING, '1')
          } finally {
            this.switching = false
          }
          useOptimizeStore().clearMessages()
          message.warning('文件夹未授权，已先保存到浏览器；授权后再同步到文件夹')
          return 'ok'
        }

        // 先把当前这份简历的未保存修改写回旧文件，再创建新文档
        await this.flush()

        const target = await this.chooseNewName(title, options.conflict ?? 'unique')
        if (!target) return 'cancelled'

        try {
          const mtime = await writeResumeJson(dir, target, data)
          this.switching = true
          try {
            this.setCurrentFile(target, mtime)
            replaceResume(data)
            resumeName.value = fileTitle(target)
            this.externalChanged = false
            externalWarnShown = false
            useOptimizeStore().clearMessages()
          } finally {
            this.switching = false
          }
          await this.refreshFiles()
          return 'ok'
        } catch (err) {
          // 写盘失败仍然让用户继续编辑，修改会留在 localStorage
          this.switching = true
          try {
            replaceResume(data)
            resumeName.value = title
            this.clearCurrentFile()
            localStorage.setItem(LS_PENDING, '1')
          } finally {
            this.switching = false
          }
          useOptimizeStore().clearMessages()
          message.error(`写入备份文件夹失败：${errorText(err)}（已保存在浏览器）`)
          return 'ok'
        }
      })
    },

    /**
     * 重命名当前文件。
     * 名称冲突时默认返回 conflict，由 UI 询问后带 conflict 选项再次调用。
     */
    renameCurrent(
      newTitle: string,
      options: { conflict?: 'overwrite' | 'unique' } = {},
    ): Promise<RenameDocumentResult> {
      return exclusive(async () => {
        const clean = sanitizeFileTitle(newTitle, resumeFilename())
        resumeName.value = clean

        if (!this.isBound || !this.currentFile || this.status !== 'ready' || !dir) {
          return { ok: true }
        }

        const oldName = this.currentFile
        const oldTitle = fileTitle(oldName)
        if (clean === oldTitle) return { ok: true }

        // Windows 文件名大小写不敏感：只改显示名，不做「写新文件 + 删旧文件」
        if (clean.toLowerCase() === oldTitle.toLowerCase()) return { ok: true }

        const firstChoice = `${clean}.json`
        if (await folderFileExists(dir, firstChoice)) {
          if (options.conflict === 'overwrite') {
            return this.performRename(firstChoice)
          }
          if (options.conflict === 'unique') {
            return this.performRename(await findAvailableName(dir, clean))
          }
          return { ok: false, conflict: firstChoice }
        }
        return this.performRename(firstChoice)
      })
    },

    /** 真正执行“写新文件 + 删旧文件 + 切换指针” */
    async performRename(targetName: string): Promise<RenameDocumentResult> {
      if (!dir || !this.currentFile) return { ok: false }
      const oldName = this.currentFile
      const saved = await this.flush()
      if (!saved) return { ok: false }

      try {
        const snapshot = resumeSnapshot()
        const mtime = await writeResumeJson(dir, targetName, snapshot)
        if (oldName.toLowerCase() !== targetName.toLowerCase()) {
          try {
            await removeFolderFile(dir, oldName)
          } catch {
            message.warning(`新文件已创建，但旧文件「${oldName}」删除失败，请手动删除`)
          }
        }
        this.setCurrentFile(targetName, mtime)
        lastSyncedJson = JSON.stringify(snapshot)
        resumeName.value = fileTitle(targetName)
        await this.refreshFiles()
        return { ok: true, name: targetName }
      } catch (err) {
        message.error(`重命名失败：${errorText(err)}`)
        return { ok: false }
      }
    },

    /* ==================== 保存 / 同步 ==================== */

    /** 把当前简历写回文件夹（不弹成功提示；失败时按需提示一次） */
    async saveNow(options: { silent?: boolean; force?: boolean } = {}): Promise<boolean> {
      if (this.switching) return false
      if (!this.isBound) return true
      if (!dir || this.status !== 'ready' || !this.currentFile) {
        if (this.currentFile) localStorage.setItem(LS_PENDING, '1')
        return false
      }

      const name = this.currentFile
      const snapshot = resumeSnapshot()
      const json = JSON.stringify(snapshot)
      const knownMtime = this.lastKnownMtime

      const run = async (): Promise<boolean> => {
        try {
          // 内容与上次读入 / 写入完全一致：没有实际改动，不碰文件（打开文档、撤销回已保存状态等）
          if (!options.force && this.currentFile === name && json === lastSyncedJson) {
            localStorage.removeItem(LS_PENDING)
            return true
          }

          // 外部修改检测：除非用户明确选择覆盖，否则暂停自动保存
          if (!options.force && knownMtime > 0) {
            const info = await getFolderFileInfo(dir!, name)
            if (info && info.mtime > knownMtime + MTIME_TOLERANCE) {
              this.externalChanged = true
              if (!externalWarnShown) {
                externalWarnShown = true
                message.warning('文件夹里的简历已被外部修改，自动保存已暂停；请在简历库点「同步」处理')
              }
              return false
            }
          }

          const mtime = await writeResumeJson(dir!, name, snapshot)
          // 排队写盘期间用户可能已经切换了文档，只有仍指向这个文件时才更新指针
          if (this.currentFile === name) {
            this.setCurrentFile(name, mtime)
            lastSyncedJson = json
            this.externalChanged = false
            externalWarnShown = false
          }
          writeErrorShown = false
          localStorage.removeItem(LS_PENDING)
          return true
        } catch (err) {
          localStorage.setItem(LS_PENDING, '1')
          if (err instanceof DOMException && err.name === 'NotAllowedError') {
            this.status = 'needs-permission'
          }
          if (!options.silent && !writeErrorShown) {
            writeErrorShown = true
            message.error(`写入备份文件夹失败：${errorText(err)}（修改已保存在浏览器）`)
          }
          return false
        }
      }

      const task = writeChain.then(run, run)
      writeChain = task.catch(() => false)
      return task
    },

    /** 自动保存：防抖 1 秒写文件夹 */
    scheduleSave(delay = 1000): void {
      if (!this.initialized || this.switching) return
      if (!dir || this.status !== 'ready' || !this.currentFile) return
      // 标记「有改动尚未落盘」：若此时刷新/崩溃，下次启动会优先用 localStorage 里的内容
      localStorage.setItem(LS_PENDING, '1')
      if (saveTimer) clearTimeout(saveTimer)
      saveTimer = setTimeout(() => {
        saveTimer = null
        void this.saveNow({ silent: true })
      }, delay)
    },

    /**
     * 立即把防抖中的修改写盘。
     * 返回值表示“当前内容是否已经安全落盘”：没有变化 / 没有绑定文件夹也算成功。
     */
    async flush(): Promise<boolean> {
      if (saveTimer) {
        clearTimeout(saveTimer)
        saveTimer = null
      }
      if (!this.isBound) return true
      const resumeStore = useResumeStore()
      if (!dir || this.status !== 'ready') return resumeStore.resume.length === 0
      if (!this.currentFile) return resumeStore.resume.length === 0
      return this.saveNow({ silent: true })
    },

    /**
     * 设置页「立即同步」：
     *   1. 申请权限、重新扫描列表；
     *   2. 当前简历还没有对应文件 → 写一个新文件；
     *   3. 当前文件被外部修改 / 删除 → 让用户选择处理方式。
     * 不会批量导入、不会删除任何文件。
     */
    sync(): Promise<boolean> {
      return exclusive(async () => {
        if (!this.isBound) {
          message.warning('请先选择本地备份文件夹')
          return false
        }
        if (!(await this.ensurePermission()) || !dir) {
          message.warning('没有文件夹读写权限，请在浏览器提示中允许，或重新选择文件夹')
          return false
        }

        this.busy = true
        try {
          await this.flush()
          await this.refreshFiles()

          const resumeStore = useResumeStore()

          // 还没有当前文件：把内存里的简历写进文件夹
          if (!this.currentFile) {
            if (resumeStore.resume.length === 0) return true
            const target = await this.chooseNewName(resumeFilename(), 'ask')
            if (!target) return false
            const snapshot = resumeSnapshot()
            const mtime = await writeResumeJson(dir, target, snapshot)
            this.setCurrentFile(target, mtime)
            lastSyncedJson = JSON.stringify(snapshot)
            resumeName.value = fileTitle(target)
            await this.refreshFiles()
            return true
          }

          const currentName = this.currentFile
          const info = this.files.find(
            (f) => f.name.toLowerCase() === currentName.toLowerCase(),
          )

          // 当前文件被外部删除 / 改名
          if (!info) {
            const recreate = await confirmAction({
              title: '当前简历文件不在了',
              content: `备份文件夹里找不到「${currentName}」，可能被重命名或删除。要按当前内容重新创建吗？`,
              positiveText: '重新创建',
              negativeText: '暂不处理',
            })
            if (recreate) {
              const target = await this.chooseNewName(fileTitle(currentName), 'unique')
              if (target) {
                const snapshot = resumeSnapshot()
                const mtime = await writeResumeJson(dir, target, snapshot)
                this.setCurrentFile(target, mtime)
                lastSyncedJson = JSON.stringify(snapshot)
                resumeName.value = fileTitle(target)
                await this.refreshFiles()
              }
            }
            return true
          }

          if (this.lastKnownMtime > 0 && info.mtime > this.lastKnownMtime + MTIME_TOLERANCE) {
            await this.resolveExternalChange(info)
          } else {
            this.externalChanged = false
            externalWarnShown = false
          }
          return true
        } catch (err) {
          message.error(`同步失败：${errorText(err)}`)
          return false
        } finally {
          this.busy = false
        }
      })
    },

    /** 外部修改冲突：载入文件版本 / 用当前内容覆盖 / 稍后处理 */
    async resolveExternalChange(info: BackupFileInfo): Promise<void> {
      let choice: 'load' | 'overwrite' | null = null
      await new Promise<void>((resolve) => {
        let settled = false
        const finish = (value: 'load' | 'overwrite' | null) => {
          if (settled) return
          settled = true
          choice = value
          resolve()
        }
        dialog.warning({
          title: '简历文件已在外部修改',
          content: `「${info.name}」在 SmartCV 之外被修改过。要载入文件版本，还是用当前编辑内容覆盖它？`,
          positiveText: '载入文件版本',
          negativeText: '用当前内容覆盖',
          onPositiveClick: () => finish('load'),
          onNegativeClick: () => finish('overwrite'),
          onClose: () => finish(null),
          onMaskClick: () => finish(null),
        })
      })

      if (choice === 'load') {
        await this.loadCurrentFromFolder(info)
      } else if (choice === 'overwrite') {
        await this.saveNow({ force: true, silent: false })
      }
    },

    /** 直接从文件夹载入当前文件（不再 flush，避免把本地内容写回文件） */
    async loadCurrentFromFolder(info: BackupFileInfo): Promise<boolean> {
      if (!dir) return false
      try {
        const data = await readResumeJson(dir, info.name)
        const resumeStore = useResumeStore()
        if (!resumeStore.canOpenResume(data)) {
          message.error(`「${info.name}」不是合法的简历 JSON`)
          return false
        }
        this.switching = true
        try {
          this.setCurrentFile(info.name, info.mtime)
          replaceResume(data)
          resumeName.value = fileTitle(info.name)
          this.externalChanged = false
          externalWarnShown = false
          useOptimizeStore().clearMessages()
        } finally {
          this.switching = false
        }
        return true
      } catch (err) {
        message.error(`载入失败：${errorText(err)}`)
        return false
      }
    },

    /** 启动时从文件夹恢复当前文件（有未写盘修改时以本地缓存为准） */
    async restoreCurrentFromFolder(): Promise<void> {
      if (!dir || !this.currentFile) return

      // 上次退出时有修改没写进文件夹：以 localStorage 里的内容为准，补写一次
      if (localStorage.getItem(LS_PENDING) === '1') {
        await this.saveNow({ silent: true })
        return
      }

      const info = await getFolderFileInfo(dir, this.currentFile)
      if (!info) {
        // 文件被删除 / 改名：内容仍在浏览器缓存里，等用户同步时决定
        this.externalChanged = true
        return
      }
      await this.loadCurrentFromFolder(info)
    },

    /* ==================== 导出 ==================== */

    /**
     * 导出 JSON：绑定了文件夹就写回当前文件（没有当前文件时新建一个）。
     * - saved：已写入文件夹
     * - unavailable：没有文件夹 / 没有权限 / 写入失败，调用方改用浏览器下载
     * - cancelled：用户在覆盖确认或命名弹窗里取消，不要做任何兜底
     */
    exportJson(): Promise<'saved' | 'unavailable' | 'cancelled'> {
      return exclusive<'saved' | 'unavailable' | 'cancelled'>(async () => {
        if (!this.isBound) return 'unavailable'
        if (!(await this.ensurePermission()) || !dir) return 'unavailable'

        if (this.externalChanged) {
          const ok = await confirmAction({
            title: '文件已被外部修改',
            content: '继续保存会用当前编辑内容覆盖外部修改。是否继续？',
            positiveText: '覆盖保存',
            negativeText: '取消',
          })
          if (!ok) return 'cancelled'
        }

        if (!this.currentFile) {
          const target = await this.chooseNewName(resumeFilename(), 'unique')
          if (!target) return 'cancelled'
          try {
            const snapshot = resumeSnapshot()
            const mtime = await writeResumeJson(dir, target, snapshot)
            this.setCurrentFile(target, mtime)
            lastSyncedJson = JSON.stringify(snapshot)
            resumeName.value = fileTitle(target)
            this.externalChanged = false
            await this.refreshFiles()
            return 'saved'
          } catch (err) {
            message.error(`保存失败：${errorText(err)}`)
            return 'unavailable'
          }
        }

        return (await this.saveNow({ force: true, silent: false })) ? 'saved' : 'unavailable'
      })
    },

    /** 把 PDF 写入备份文件夹；失败时返回 false，由调用方降级为浏览器下载 */
    async savePdf(blob: Blob, title: string): Promise<boolean> {
      if (!this.isBound) return false
      if (!(await this.ensurePermission()) || !dir) return false
      const name = `${sanitizeFileTitle(title, resumeFilename())}.pdf`
      try {
        await writeBlobToFolder(dir, name, blob)
        return true
      } catch (err) {
        console.warn('PDF 写入备份文件夹失败', err)
        return false
      }
    },

    /* ==================== 内容替换辅助 ==================== */

    /**
     * 选一个不冲突的文件名。
     * mode = 'unique' 直接加序号；mode = 'ask' 先问用户“保留两份 / 覆盖原文件”。
     * 返回 null 表示用户取消。
     */
    async chooseNewName(baseTitle: string, mode: 'ask' | 'unique'): Promise<string | null> {
      if (!dir) return null
      const base = sanitizeFileTitle(baseTitle)
      const firstChoice = `${base}.json`
      if (!(await folderFileExists(dir, firstChoice))) return firstChoice
      if (mode === 'unique') return findAvailableName(dir, base)

      return new Promise<string | null>((resolve) => {
        let settled = false
        const finish = (value: string | null) => {
          if (settled) return
          settled = true
          resolve(value)
        }
        dialog.warning({
          title: '文件夹里已有同名简历',
          content: `「${firstChoice}」已经存在。保留两份会自动加序号；覆盖会替换原文件。`,
          positiveText: '保留两份',
          negativeText: '覆盖原文件',
          onPositiveClick: () => {
            void findAvailableName(dir!, base).then((name) => finish(name))
          },
          onNegativeClick: () => finish(firstChoice),
          onClose: () => finish(null),
          onMaskClick: () => finish(null),
        })
      })
    },
  },
})
