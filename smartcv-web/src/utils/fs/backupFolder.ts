import { fileTitle, sanitizeFileTitle } from '@/utils/filename'

export interface BackupFileInfo {
  name: string
  title: string
  mtime: number
  size: number
}

function isJsonName(name: string): boolean {
  return /\.json$/i.test(name)
}

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
    }
  }
  files.sort((a, b) => b.mtime - a.mtime)
  return files
}

export async function readResumeJson(dir: FileSystemDirectoryHandle, name: string): Promise<unknown> {
  const handle = await dir.getFileHandle(name)
  const text = await (await handle.getFile()).text()
  return JSON.parse(text)
}

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

export async function removeFolderFile(dir: FileSystemDirectoryHandle, name: string): Promise<void> {
  await dir.removeEntry(name)
}

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
