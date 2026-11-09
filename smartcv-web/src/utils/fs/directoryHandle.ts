const DB_NAME = 'smartcv-fs'
const DB_VERSION = 1
const STORE_NAME = 'handles'
const BACKUP_HANDLE_KEY = 'backup-dir'

export function supportsDirectoryPicker(): boolean {
  return typeof window !== 'undefined' && typeof window.showDirectoryPicker === 'function'
}

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

export async function saveDirectoryHandle(handle: FileSystemDirectoryHandle): Promise<void> {
  await runRequest('readwrite', (store) => store.put(handle, BACKUP_HANDLE_KEY))
}

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

export async function clearDirectoryHandle(): Promise<void> {
  try {
    await runRequest('readwrite', (store) => store.delete(BACKUP_HANDLE_KEY))
  } catch {
  }
}

export async function queryDirPermission(
  handle: FileSystemDirectoryHandle,
): Promise<PermissionState> {
  try {
    return (await handle.queryPermission?.({ mode: 'readwrite' })) ?? 'granted'
  } catch {
    return 'prompt'
  }
}

export async function requestDirPermission(
  handle: FileSystemDirectoryHandle,
): Promise<PermissionState> {
  try {
    return (await handle.requestPermission?.({ mode: 'readwrite' })) ?? 'granted'
  } catch {
    return 'denied'
  }
}

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
