/**
 * 生成 example/index.json —— 示例模板的目录清单。
 *
 * 为什么需要它：
 *   前端原来用 api.github.com 列 example/ 目录，未认证只有 60 次/小时/IP，
 *   多开标签页或同出口 IP 的其它工具一多就会耗尽。改成读仓库里的静态清单后，
 *   清单和示例文件都走 raw.githubusercontent.com（CDN 直出），不消耗 API 配额。
 *
 * 用法（在 smartcv-web 下）：
 *   npm run examples:index
 *
 * 新增示例的流程：
 *   1. 往仓库 example/ 丢一个 json 文件（建议按 `01-标题.json` 命名）；
 *   2. 跑一次本脚本；
 *   3. 把新 json 和更新后的 index.json 一起提交。
 */
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/** 仓库根目录下的 example/（本脚本在 smartcv-web/scripts/ 下） */
const EXAMPLE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '../../example')
const INDEX_FILE = join(EXAMPLE_DIR, 'index.json')

/**
 * 从文件名解析标题：`01-经典左头图.json` → 经典左头图。
 * 与前端 src/api/examples.ts 的 parseName() 规则保持一致。
 */
function parseTitle(name) {
  const stem = name.replace(/\.json$/i, '')
  const matched = /^(\d+)\s*[-_.、\s]\s*(.+)$/.exec(stem)
  return matched ? matched[2].trim() : stem
}

const files = readdirSync(EXAMPLE_DIR)
  .filter((name) => /\.json$/i.test(name) && name !== 'index.json')
  // 按文件名自然排序（数字按数值比较），和前端 parseName 的排序意图一致
  .sort((a, b) => a.localeCompare(b, 'zh-CN', { numeric: true }))

const entries = files.map((name) => ({
  name,
  title: parseTitle(name),
  size: statSync(join(EXAMPLE_DIR, name)).size,
}))

writeFileSync(INDEX_FILE, `${JSON.stringify(entries, null, 2)}\n`, 'utf8')
console.log(`已生成 ${INDEX_FILE}（${entries.length} 个示例）`)

// 读回一次，确保写出来的文件能被正常解析（比如文件名里有异常字符时尽早暴露）
JSON.parse(readFileSync(INDEX_FILE, 'utf8'))
