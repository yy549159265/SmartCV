import { defineStore } from 'pinia'
import { useResumeStore } from '@/stores/resume'
import { useReviewStore } from '@/stores/review'
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

export type BackupStatus = 'unsupported' | 'unbound' | 'needs-permission' | 'ready' | 'denied'

export type CreateDocumentResult = 'ok' | 'invalid' | 'cancelled'

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

const MTIME_TOLERANCE = 2000

let dir: FileSystemDirectoryHandle | null = null
let saveTimer: ReturnType<typeof setTimeout> | null = null
let writeChain: Promise<unknown> = Promise.resolve()
let opChain: Promise<unknown> = Promise.resolve()
let writeErrorShown = false
let externalWarnShown = false
let lastSyncedJson: string | null = null

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

function currentResumeJson(): string {
  return JSON.stringify(useResumeStore().resume)
}

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
    folderName: localStorage.getItem(LS_FOLDER_NAME) ?? '',
    files: readCachedIndex(),
    currentFile: localStorage.getItem(LS_CURRENT) || null,
    lastSyncAt: Number(localStorage.getItem(LS_LAST_SYNC) || 0),
    lastKnownMtime: Number(localStorage.getItem(LS_CURRENT_MTIME) || 0),
    externalChanged: false,
    busy: false,
    switching: false,
    initialized: false,
  }),

  getters: {
    isBound: (state): boolean => state.folderName !== '',
    canBrowse: (state): boolean => state.status === 'ready' || state.status === 'needs-permission',
    currentTitle: (state): string => (state.currentFile ? fileTitle(state.currentFile) : ''),
  },

  actions: {

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

    async bindFolder(): Promise<boolean> {
      if (!supportsDirectoryPicker()) {
        this.status = 'unsupported'
        message.warning('当前浏览器不支持选择文件夹，请使用 Chrome 或 Edge')
        return false
      }
      try {
        const handle = await pickDirectory()
        if (!handle) return false

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

        if (!sameFolder) this.clearCurrentFile()

        if (this.status === 'ready') {
          await this.refreshFiles()
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

    async refreshIfReady(): Promise<void> {
      if (this.status === 'ready') await this.refreshFiles()
    },

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

          this.switching = true
          try {
            this.setCurrentFile(info.name, info.mtime)
            replaceResume(data)
            resumeName.value = fileTitle(info.name)
            this.externalChanged = false
            externalWarnShown = false
            useReviewStore().clearMessages()
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

    deleteFile(name: string): Promise<boolean> {
      return exclusive(async () => {
        if (!this.isBound || !name) return false
        if (!(await this.ensurePermission()) || !dir) {
          message.warning('没有文件夹访问权限，请重新授权')
          return false
        }

        const deletingCurrent = this.currentFile?.toLowerCase() === name.toLowerCase()

        if (saveTimer) {
          clearTimeout(saveTimer)
          saveTimer = null
        }
        this.switching = true
        try {
          await writeChain.catch(() => undefined)
          await removeFolderFile(dir, name)
          if (deletingCurrent) {
            this.clearCurrentFile()
            this.externalChanged = false
            externalWarnShown = false
            localStorage.removeItem(LS_PENDING)
          }
        } catch (err) {
          if (err instanceof DOMException && err.name === 'NotFoundError') {
            message.warning(`「${name}」已经不在文件夹里了`)
            await this.refreshFiles()
            return false
          }
          message.error(`删除失败：${errorText(err)}`)
          return false
        } finally {
          this.switching = false
        }

        await this.refreshFiles()
        return true
      })
    },

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
          useReviewStore().clearMessages()
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
          useReviewStore().clearMessages()
          message.warning('文件夹未授权，新简历先保存在浏览器；授权后再同步')
          return 'ok'
        }

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
            useReviewStore().clearMessages()
          } finally {
            this.switching = false
          }
          await this.refreshFiles()
          return 'ok'
        } catch (err) {
          this.switching = true
          try {
            replaceResume([])
            resumeName.value = '新简历'
            this.clearCurrentFile()
            localStorage.setItem(LS_PENDING, '1')
          } finally {
            this.switching = false
          }
          useReviewStore().clearMessages()
          message.error(`新建失败：${errorText(err)}（已改为保存在浏览器）`)
          return 'ok'
        }
      })
    },

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
          useReviewStore().clearMessages()
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
          useReviewStore().clearMessages()
          message.warning('文件夹未授权，已先保存到浏览器；授权后再同步到文件夹')
          return 'ok'
        }

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
            useReviewStore().clearMessages()
          } finally {
            this.switching = false
          }
          await this.refreshFiles()
          return 'ok'
        } catch (err) {
          this.switching = true
          try {
            replaceResume(data)
            resumeName.value = title
            this.clearCurrentFile()
            localStorage.setItem(LS_PENDING, '1')
          } finally {
            this.switching = false
          }
          useReviewStore().clearMessages()
          message.error(`写入备份文件夹失败：${errorText(err)}（已保存在浏览器）`)
          return 'ok'
        }
      })
    },

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
          if (!options.force && this.currentFile === name && json === lastSyncedJson) {
            localStorage.removeItem(LS_PENDING)
            return true
          }

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

    scheduleSave(delay = 1000): void {
      if (!this.initialized || this.switching) return
      if (!dir || this.status !== 'ready' || !this.currentFile) return
      localStorage.setItem(LS_PENDING, '1')
      if (saveTimer) clearTimeout(saveTimer)
      saveTimer = setTimeout(() => {
        saveTimer = null
        void this.saveNow({ silent: true })
      }, delay)
    },

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
          useReviewStore().clearMessages()
        } finally {
          this.switching = false
        }
        return true
      } catch (err) {
        message.error(`载入失败：${errorText(err)}`)
        return false
      }
    },

    async restoreCurrentFromFolder(): Promise<void> {
      if (!dir || !this.currentFile) return

      if (localStorage.getItem(LS_PENDING) === '1') {
        await this.saveNow({ silent: true })
        return
      }

      const info = await getFolderFileInfo(dir, this.currentFile)
      if (!info) {
        this.externalChanged = true
        return
      }
      await this.loadCurrentFromFolder(info)
    },

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
