/**
 * File System Access API 的补充类型。
 *
 * TypeScript 5.7 的 lib.dom 只声明了 FileSystemHandle / FileSystemDirectoryHandle
 * 的基础方法，目录遍历（entries / values）、权限查询（queryPermission /
 * requestPermission）和 showDirectoryPicker 都没有，这里补齐本项目用到的部分。
 */

interface FileSystemHandlePermissionDescriptor {
  mode?: 'read' | 'readwrite'
}

interface FileSystemHandle {
  /** 查询当前权限；Chrome 86+ 支持。 */
  queryPermission?(descriptor?: FileSystemHandlePermissionDescriptor): Promise<PermissionState>
  /** 申请权限；必须在用户点击等手势中调用。 */
  requestPermission?(descriptor?: FileSystemHandlePermissionDescriptor): Promise<PermissionState>
}

interface FileSystemDirectoryHandle {
  entries(): AsyncIterableIterator<[string, FileSystemHandle]>
  values(): AsyncIterableIterator<FileSystemHandle>
  keys(): AsyncIterableIterator<string>
}

interface DirectoryPickerOptions {
  /** 同一 id 会让浏览器记住上次选择的位置 */
  id?: string
  mode?: 'read' | 'readwrite'
  startIn?: FileSystemHandle | 'desktop' | 'documents' | 'downloads' | 'music' | 'pictures' | 'videos'
}

interface Window {
  showDirectoryPicker?(options?: DirectoryPickerOptions): Promise<FileSystemDirectoryHandle>
}
