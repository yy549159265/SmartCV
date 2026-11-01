/**
 * 备份文件夹句柄的持久化与权限管理。
 *
 * 为什么不用 localStorage：
 *   用户选完文件夹后拿到的是 FileSystemDirectoryHandle 对象，localStorage 只能
 *   存字符串（JSON.stringify 会变成 {}）。IndexedDB 支持结构化克隆，可以把句柄
 *   原样存下来，下次打开页面取出来仍然指向同一个文件夹。
 *
 * 权限限制：
 *   浏览器重启后 queryPermission 通常会变回 "prompt"，必须在用户点击里调用
 *   requestPermission 重新授权，不能静默恢复。
 */

const DB_NAME = 'smartcv-fs'
const DB_VERSION = 1
const STORE_NAME = 'handles'
const BACKUP_HANDLE_KEY = 'backup-dir'

/** 当前浏览器是否支持选择文件夹（Chrome / Edge；且要求 https 或 localhost） */
export function supportsDirectoryPicker(): boolean {
  return typeof window !== 'undefined' && typeof window.showDirectoryPicker === 'function'
}

/** 打开 IndexedDB（首次使用时建 handles 对象仓库） */
function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME)
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB 打开失败'))
  })
}

/** 在一个事务里执行一次请求，事务完成后 resolve */
function runRequest<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, mode)
        const request = run(tx.objectStore(STORE_NAME))
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => reject(request.error ?? new Error('IndexedDB 操作失败'))
        tx.oncomplete = () => db.close()
        tx.onerror = () => {
          db.close()
          reject(tx.error ?? new Error('IndexedDB 事务失败'))
        }
      }),
  )
}

/** 保存选中的文件夹句柄 */
export async function saveDirectoryHandle(handle: FileSystemDirectoryHandle): Promise<void> {
  await runRequest('readwrite', (store) => store.put(handle, BACKUP_HANDLE_KEY))
}

/** 读回上次保存的文件夹句柄（没有 / 存储不可用时返回 null） */
export async function loadDirectoryHandle(): Promise<FileSystemDirectoryHandle | null> {
  try {
    const handle = await runRequest<FileSystemDirectoryHandle | undefined>('readonly', (store) =>
      store.get(BACKUP_HANDLE_KEY),
    )
    return handle ?? null
  } catch {
    return null
  }
}

/** 清除保存的文件夹句柄 */
export async function clearDirectoryHandle(): Promise<void> {
  try {
    await runRequest('readwrite', (store) => store.delete(BACKUP_HANDLE_KEY))
  } catch {
    /* 清除失败不影响用户继续使用；下次选择会覆盖 */
  }
}

/** 查询文件夹权限；不支持 queryPermission 的旧浏览器按已授权处理（选完就能用） */
export async function queryDirPermission(
  handle: FileSystemDirectoryHandle,
): Promise<PermissionState> {
  try {
    return (await handle.queryPermission?.({ mode: 'readwrite' })) ?? 'granted'
  } catch {
    return 'prompt'
  }
}

/** 申请文件夹权限；必须在用户点击等手势中调用 */
export async function requestDirPermission(
  handle: FileSystemDirectoryHandle,
): Promise<PermissionState> {
  try {
    return (await handle.requestPermission?.({ mode: 'readwrite' })) ?? 'granted'
  } catch {
    return 'denied'
  }
}

/**
 * 弹出系统文件夹选择器。
 * 取消选择会抛出 AbortError，由调用方静默处理。
 */
export async function pickDirectory(): Promise<FileSystemDirectoryHandle | null> {
  if (!supportsDirectoryPicker()) {
    throw new Error('当前浏览器不支持选择文件夹，请使用 Chrome 或 Edge')
  }
  return window.showDirectoryPicker!({
    id: 'smartcv-backup',
    mode: 'readwrite',
    startIn: 'documents',
  })
}
