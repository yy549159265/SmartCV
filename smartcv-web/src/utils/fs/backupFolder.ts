/**
 * 备份文件夹的读写工具。
 *
 * 约定：一份简历 = 文件夹顶层的一个 .json 文件，内容就是现有的 Section[] 数组；
 * 文件名（去掉 .json）就是简历名。只处理顶层文件，不递归子文件夹。
 */
import { fileTitle, sanitizeFileTitle } from '@/utils/filename'

/** 文件夹里的一份简历文件 */
export interface BackupFileInfo {
  /** 完整文件名，如 张三-前端.json */
  name: string
  /** 简历名，如 张三-前端 */
  title: string
  /** 最后修改时间（毫秒时间戳） */
  mtime: number
  /** 文件大小（字节） */
  size: number
}

function isJsonName(name: string): boolean {
  return /\.json$/i.test(name)
}

/** 列出文件夹顶层的全部 JSON 简历，按修改时间倒序 */
export async function listResumeFiles(dir: FileSystemDirectoryHandle): Promise<BackupFileInfo[]> {
  const files: BackupFileInfo[] = []
  for await (const [name, handle] of dir.entries()) {
    if (handle.kind !== 'file' || !isJsonName(name)) continue
    try {
      const file = await (handle as FileSystemFileHandle).getFile()
      files.push({
        name,
        title: fileTitle(name),
        mtime: file.lastModified,
        size: file.size,
      })
    } catch {
      /* 单个文件读不了（被占用 / 权限不足）不影响整个列表 */
    }
  }
  files.sort((a, b) => b.mtime - a.mtime)
  return files
}

/** 读取并解析一份简历 JSON；文件不存在 / 内容非法时抛错 */
export async function readResumeJson(dir: FileSystemDirectoryHandle, name: string): Promise<unknown> {
  const handle = await dir.getFileHandle(name)
  const text = await (await handle.getFile()).text()
  return JSON.parse(text)
}

/** 写入 JSON，返回写完后文件的 lastModified（用于外部修改检测） */
export async function writeResumeJson(
  dir: FileSystemDirectoryHandle,
  name: string,
  data: unknown,
): Promise<number> {
  const handle = await dir.getFileHandle(name, { create: true })
  const writable = await handle.createWritable()
  try {
    await writable.write(JSON.stringify(data, null, 2))
  } finally {
    await writable.close()
  }
  return (await handle.getFile()).lastModified
}

/** 写入二进制文件（PDF），返回写完后文件的 lastModified */
export async function writeBlobToFolder(
  dir: FileSystemDirectoryHandle,
  name: string,
  blob: Blob,
): Promise<number> {
  const handle = await dir.getFileHandle(name, { create: true })
  const writable = await handle.createWritable()
  try {
    await writable.write(blob)
  } finally {
    await writable.close()
  }
  return (await handle.getFile()).lastModified
}

/** 删除文件夹里的一个文件 */
export async function removeFolderFile(dir: FileSystemDirectoryHandle, name: string): Promise<void> {
  await dir.removeEntry(name)
}

/** 文件夹里是否已有某个文件（Windows 大小写不敏感，统一按小写比较） */
export async function folderFileExists(
  dir: FileSystemDirectoryHandle,
  name: string,
): Promise<boolean> {
  const target = name.toLowerCase()
  for await (const [entryName, handle] of dir.entries()) {
    if (handle.kind === 'file' && entryName.toLowerCase() === target) return true
  }
  return false
}

/** 取单个文件的信息（不存在时返回 null） */
export async function getFolderFileInfo(
  dir: FileSystemDirectoryHandle,
  name: string,
): Promise<BackupFileInfo | null> {
  try {
    const handle = await dir.getFileHandle(name)
    const file = await handle.getFile()
    return { name, title: fileTitle(name), mtime: file.lastModified, size: file.size }
  } catch {
    return null
  }
}

/** 按「名字 (2).json」的规则找一个不冲突的文件名 */
export async function findAvailableName(
  dir: FileSystemDirectoryHandle,
  baseTitle: string,
  ext = '.json',
): Promise<string> {
  const names = new Set<string>()
  for await (const [name, handle] of dir.entries()) {
    if (handle.kind === 'file') names.add(name.toLowerCase())
  }

  const base = sanitizeFileTitle(baseTitle)
  let candidate = `${base}${ext}`
  let index = 2
  while (names.has(candidate.toLowerCase())) {
    candidate = `${base} (${index})${ext}`
    index += 1
  }
  return candidate
}
