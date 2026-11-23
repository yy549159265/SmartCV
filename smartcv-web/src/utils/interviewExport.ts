/**
 * 面试记录导出：生成自包含的单文件 HTML。
 *
 * 约束：
 * - 不引用任何外部资源（字体、脚本、图片、样式），双击即可离线查看；
 * - 来自你与 AI 的所有文本都先转义；报告正文走 Markdown 渲染并禁用原始 HTML，
 *   图片只保留说明文字，避免打开文件时请求外链；
 * - 「面试报告」章节始终输出：有报告就渲染，未生成或面试未结束就给出对应占位，
 *   后续报告功能上线后导出结构不用改；
 * - 不截断任何文本，长内容按原样换行撑开。
 */

import MarkdownIt from 'markdown-it'

import type {
  AnswerRecord,
  FollowUp,
  InterviewReport,
  InterviewSummary,
  QuestionCard,
  ReferenceAnswer,
  ResumeProfile,
  TeachingEvent,
  TokenUsage,
} from '@/api/interview'
import type { SessionRecord } from '@/utils/interviewDb'
import type { ReviewRound } from '@/utils/interviewReview'
import {
  FINISH_LABEL,
  LEVEL_LABEL,
  PRIORITY_LABEL,
  SCENE_LABEL,
  dimensionLabel,
  focusLabel,
  formatDateTime,
  formatTokenCount,
  usageTitle,
} from '@/utils/interview'
import {
  attemptLabel,
  groupReviewRounds,
  outcomeLabel,
  roundKind,
} from '@/utils/interviewReview'
import { downloadBlob } from '@/utils/download'
import { message } from '@/utils/feedback'

/**
 * 报告正文专用渲染器：与页面一样禁用原始 HTML，但不渲染图片。
 * 图片会让「单文件、离线可看」变成打开即请求外链，导出里只保留其中文说明。
 */
const reportMarkdown = new MarkdownIt({ html: false, breaks: true, linkify: true })
reportMarkdown.renderer.rules.image = (tokens, index) => {
  const alt = tokens[index].content
  return alt
    ? `[图片] ${reportMarkdown.utils.escapeHtml(alt)}`
    : '[图片]'
}

export function renderReportProse(prose: string): string {
  return reportMarkdown.render(prose)
}

export interface ExportStat {
  label: string
  value: string
}

export interface ExportChecklist {
  cards: QuestionCard[]
  warnings: string[]
  seenCardIds: string[]
  projectNames: Map<string, string>
}

export interface InterviewExportModel {
  filename: string
  title: string
  timeLabel: string
  statusLabel: string
  finishLabel: string
  focusLabel: string
  projectLabel: string
  stats: ExportStat[]
  report: InterviewReport | null
  finished: boolean
  rounds: ReviewRound[]
  checklist: ExportChecklist | null
  usageLine: string
  exportedAt: string
}

function fallbackSummary(
  records: AnswerRecord[],
  teaching: TeachingEvent[],
): InterviewSummary {
  const answered = records.filter((record) => !record.skipped)
  return {
    records,
    dynamicCount: 0,
    teachingCount: teaching.length,
    answeredCount: answered.length,
    skippedCount: records.length - answered.length,
    finishedReason: '',
  }
}

function dateStamp(value: number): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function exportFilename(title: string, at: number): string {
  const stamp = dateStamp(at || Date.now())
  return `SmartCV-面试记录-${title}${stamp ? `-${stamp}` : ''}.html`
}

export function buildExportModel(
  session: SessionRecord,
  profile: ResumeProfile | null,
): InterviewExportModel {
  const isChecklist = session.useMode === 'checklist'
  const teaching = session.teaching ?? []
  const records = session.summary?.records ?? session.records
  const summary = session.summary ?? fallbackSummary(records, teaching)
  const title = isChecklist ? '清单自测' : SCENE_LABEL[session.scene] || '模拟面试'
  const finished = session.status === 'finished'
  const cards = session.checklistCards ?? []
  const projectNames = new Map<string, string>()
  for (const project of profile?.projects ?? []) {
    projectNames.set(project.id, project.name)
  }
  const usage: TokenUsage | undefined = session.usage ?? session.summary?.usage
  const finishedReason = session.summary?.finishedReason ?? ''

  const stats: ExportStat[] = isChecklist
    ? [
        { label: '主问题', value: String(cards.length) },
        {
          label: '追问',
          value: String(
            cards.reduce((total, card) => total + card.followUps.length, 0),
          ),
        },
        {
          label: '已读',
          value: `${(session.checklistSeenCardIds ?? []).length} / ${cards.length}`,
        },
      ]
    : [
        { label: '已答', value: String(summary.answeredCount) },
        { label: '跳过', value: String(summary.skippedCount) },
        { label: '动态追问', value: String(summary.dynamicCount) },
        { label: '讲解', value: String(teaching.length) },
      ]

  return {
    filename: exportFilename(title, session.endedAt || session.startedAt),
    title,
    timeLabel: formatDateTime(session.endedAt || session.startedAt),
    statusLabel: finished ? '已结束' : '进行中',
    finishLabel: finishedReason
      ? FINISH_LABEL[finishedReason] ?? finishedReason
      : '',
    focusLabel: focusLabel(session.focus),
    projectLabel: session.projectNames?.length
      ? `项目：${session.projectNames.join('、')}`
      : '',
    stats,
    report: session.report ?? null,
    finished,
    rounds: isChecklist ? [] : groupReviewRounds(records, teaching),
    checklist: isChecklist
      ? {
          cards,
          warnings: session.checklistWarnings ?? [],
          seenCardIds: session.checklistSeenCardIds ?? [],
          projectNames,
        }
      : null,
    usageLine: usage
      ? `本场累计 ${formatTokenCount(usage.totalTokens)} tokens（${usageTitle(usage)}）`
      : '',
    exportedAt: formatDateTime(Date.now()),
  }
}

// --------------------------------------------------------------------------- 渲染

const HTML_ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

function esc(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, (char) => HTML_ESCAPES[char])
}

function renderHeader(model: InterviewExportModel): string {
  const chips = [
    model.timeLabel,
    model.statusLabel,
    model.finishLabel,
    model.focusLabel,
  ].filter(Boolean)
  return `<header class="doc-head">
      <p class="eyebrow">SmartCV · 面试记录</p>
      <h1>${esc(model.title)}</h1>
      ${chips.length ? `<p class="doc-meta">${chips.map((chip) => `<span>${esc(chip)}</span>`).join('')}</p>` : ''}
      ${model.projectLabel ? `<p class="doc-meta"><span>${esc(model.projectLabel)}</span></p>` : ''}
    </header>`
}

function renderStats(stats: ExportStat[]): string {
  if (!stats.length) return ''
  return `<section class="stats">${stats
    .map(
      (stat) =>
        `<div class="stat"><b>${esc(stat.value)}</b><span>${esc(stat.label)}</span></div>`,
    )
    .join('')}</section>`
}

function renderReport(model: InterviewExportModel): string {
  const sections = model.report?.sections ?? []
  const body = sections.length
    ? sections
        .map(
          (section) =>
            `<section class="report-section"><h3>${esc(section.title)}</h3><div class="markdown">${renderReportProse(section.prose)}</div></section>`,
        )
        .join('')
    : `<p class="report-empty">${
        model.finished ? '本场面试报告尚未生成。' : '面试结束后生成本场报告。'
      }</p>`
  const generated = model.report?.generatedAt
    ? `<span class="section-count">${esc(formatDateTime(model.report.generatedAt))}</span>`
    : ''
  return `<section class="report">
      <div class="section-head"><h2>面试报告</h2>${generated}</div>
      <div class="report-body">${body}</div>
    </section>`
}

function renderReference(answer: ReferenceAnswer, label: string): string {
  const thinking = answer.thinking
    ? `<section class="ref-block"><h4>回答思路</h4><p class="pre">${esc(answer.thinking)}</p></section>`
    : ''
  const body = answer.answer
    ? `<section class="ref-block"><h4>回答内容</h4><p class="pre">${esc(answer.answer)}</p></section>`
    : ''
  const list = (title: string, items: string[], className: string) =>
    items.length
      ? `<section class="ref-block"><h4>${title}</h4><ul class="${className}">${items
          .map((item) => `<li>${esc(item)}</li>`)
          .join('')}</ul></section>`
      : ''
  const keyPoints = list('回答关键点', answer.keyPoints, 'ref-list')
  const missingInfo = list('缺少证据', answer.missingInfo, 'ref-list warn')
  const assumptions = list('补充假设', answer.assumptions ?? [], 'ref-list')
  return `<div class="ref">
        <p class="ref-label">${esc(label)}</p>
        ${thinking}${body}${keyPoints}${missingInfo}${assumptions}
      </div>`
}

/**
 * 回答评估区。结构与回看页的 HistoryDetail 保持一致：
 * 一个整体边框，里面依次是回答评估、没讲到的关键点、改进建议、AI 示例回答；
 * 没有内容的段落不输出，避免出现空标题。
 */
function renderRecordReview(record: AnswerRecord): string {
  const leaks = record.leaks.length
    ? `<div class="assessment-block"><h4 class="assessment-label">没讲到的关键点</h4><ul class="leaks">${record.leaks
        .map((leak) => `<li>${esc(leak)}</li>`)
        .join('')}</ul></div>`
    : ''
  const feedback = record.feedback
    ? `<div class="assessment-block"><h4 class="assessment-label">改进建议</h4><p class="feedback">${esc(record.feedback)}</p></div>`
    : ''
  const sample = record.sampleAnswer
    ? `<div class="assessment-block assessment-sample"><h4 class="assessment-label">AI 示例回答</h4><p class="sample-text">${esc(record.sampleAnswer)}</p></div>`
    : ''
  if (!record.offTopic && !leaks && !feedback && !sample) return ''
  const offTopic = record.offTopic
    ? '<p class="off-topic">这条回答偏离问题</p>'
    : ''
  return `<section class="assessment">
        <h3 class="assessment-title">回答评估</h3>
        ${offTopic}${leaks}${feedback}${sample}
      </section>`
}

function renderRecord(round: ReviewRound, record: AnswerRecord): string {
  const notes = record.skipped ? '<span class="note">跳过</span>' : ''
  return `<section class="attempt">
        <p class="row-meta"><span class="pill soft">${esc(attemptLabel(round, record))}</span>${notes}</p>
        <div class="bubble user"><span class="speaker">你的回答</span><p class="bubble-text">${esc(record.answer || '（未作答）')}</p></div>
        ${record.skipped ? '' : renderRecordReview(record)}
      </section>`
}

function renderTeaching(event: TeachingEvent): string {
  const outcome = outcomeLabel(event.outcome)
  const turns = event.turns
    .map(
      (turn) =>
        `<div class="bubble ${turn.role === 'teacher' ? 'teacher' : 'user'}"><span class="speaker">${
          turn.role === 'teacher' ? 'AI 导师' : '你'
        }</span><p class="bubble-text">${esc(turn.content)}</p></div>`,
    )
    .join('')
  return `<section class="teach">
        <p class="row-meta"><span class="pill">讲解</span>${outcome ? `<span class="note">${esc(outcome)}</span>` : ''}</p>
        <div class="teach-turns">${turns}</div>
      </section>`
}

function renderRound(round: ReviewRound): string {
  const notes: string[] = []
  if (round.records.length > 1) notes.push(`${round.records.length} 次作答`)
  if (round.teachings.length) notes.push(`${round.teachings.length} 次讲解`)
  if (!round.records.length) notes.push('无作答')
  return `<article class="round">
      <div class="round-head">
        <span class="pill">${esc(roundKind(round))}</span>
        <p class="round-q">${esc(round.question)}</p>
      </div>
      ${notes.length ? `<p class="round-notes">${notes.map(esc).join(' · ')}</p>` : ''}
      <div class="round-body">
        ${round.records.map((record) => renderRecord(round, record)).join('')}
        ${round.teachings.map(renderTeaching).join('')}
      </div>
    </article>`
}

function renderRounds(rounds: ReviewRound[]): string {
  const body = rounds.length
    ? `<div class="round-list">${rounds.map(renderRound).join('')}</div>`
    : '<p class="empty-text">这场面试没有留下作答或讲解记录。</p>'
  return `<section class="section">
      <div class="section-head"><h2>问题回看</h2><span class="section-count">${rounds.length} 个问题</span></div>
      ${body}
    </section>`
}

function renderFollowUp(followUp: FollowUp): string {
  const reference = followUp.referenceAnswer?.answer
    ? renderReference(followUp.referenceAnswer, 'AI 示范答案')
    : ''
  return `<li class="follow">
        <span class="level" data-level="${followUp.level}">${esc(LEVEL_LABEL[followUp.level])}</span>
        <div class="follow-main">
          <p class="follow-q">${esc(followUp.question)}</p>
          ${followUp.intent ? `<p class="follow-intent">${esc(followUp.intent)}</p>` : ''}
          ${reference}
        </div>
      </li>`
}

function renderCard(
  card: QuestionCard,
  index: number,
  checklist: ExportChecklist,
): string {
  const seen = checklist.seenCardIds.includes(card.id)
  const tags = [
    `<span class="tag" data-priority="${card.priority}">${esc(PRIORITY_LABEL[card.priority])}</span>`,
    `<span class="tag">${esc(dimensionLabel(card.dimension))}</span>`,
    `<span class="tag">${esc(checklist.projectNames.get(card.projectId) ?? '通用')}</span>`,
    seen ? '<span class="tag seen">已读</span>' : '',
  ]
    .filter(Boolean)
    .join('')
  const followUps = card.followUps.length
    ? `<h3 class="sub-title">追问链</h3><ol class="follow-list">${card.followUps
        .map(renderFollowUp)
        .join('')}</ol>`
    : ''
  const reference = card.referenceAnswer?.answer
    ? `<h3 class="sub-title">参考答案</h3>${renderReference(card.referenceAnswer, 'AI 示范答案')}`
    : ''
  const leaks = card.leakSignals.length
    ? `<h3 class="sub-title">容易露馅的地方</h3><ul class="leaks">${card.leakSignals
        .map((leak) => `<li>${esc(leak)}</li>`)
        .join('')}</ul>`
    : ''
  const coverage = card.coverage.length
    ? `<h3 class="sub-title">覆盖要点</h3><div class="chips">${card.coverage
        .map((item) => `<span class="chip">${esc(item)}</span>`)
        .join('')}</div>`
    : ''
  return `<article class="card">
      <div class="card-head">
        <span class="card-index">${index}</span>
        <div class="card-main">
          <div class="tags">${tags}</div>
          <p class="card-q">${esc(card.mainQuestion)}</p>
        </div>
      </div>
      <div class="card-body">
        ${card.intent ? `<p class="intent">${esc(card.intent)}</p>` : ''}
        ${card.evidenceQuote ? `<p class="evidence">简历原文：${esc(card.evidenceQuote)}</p>` : ''}
        ${followUps}
        ${reference}
        ${leaks}
        ${coverage}
      </div>
    </article>`
}

function renderChecklist(checklist: ExportChecklist): string {
  if (!checklist.cards.length) {
    return `<section class="section">
      <div class="section-head"><h2>题包内容</h2></div>
      <p class="empty-text">这条清单记录缺少题卡快照，无法导出题包内容。</p>
    </section>`
  }
  const warnings = checklist.warnings.length
    ? `<div class="warnings">${checklist.warnings
        .map((warning) => `<p>${esc(warning)}</p>`)
        .join('')}</div>`
    : ''
  const cards = checklist.cards
    .map((card, index) => renderCard(card, index + 1, checklist))
    .join('')
  return `<section class="section">
      <div class="section-head"><h2>题包内容</h2><span class="section-count">${checklist.cards.length} 道主问题</span></div>
      ${warnings}
      <div class="card-list">${cards}</div>
    </section>`
}

function renderFoot(model: InterviewExportModel): string {
  const lines = [
    model.usageLine,
    model.exportedAt ? `导出时间：${model.exportedAt}` : '',
    '内容来自本机浏览器保存的面试记录；本文件不引用外部资源，可离线查看。',
  ].filter(Boolean)
  return `<footer class="doc-foot">${lines
    .map((line) => `<p>${esc(line)}</p>`)
    .join('')}</footer>`
}

export function renderInterviewHtml(model: InterviewExportModel): string {
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(`SmartCV · ${model.title}`)}</title>
<style>${EXPORT_STYLE}</style>
</head>
<body>
<main class="page">
  <article class="paper">
    ${renderHeader(model)}
    ${renderStats(model.stats)}
    ${renderReport(model)}
    ${
      model.checklist
        ? renderChecklist(model.checklist)
        : renderRounds(model.rounds)
    }
    ${renderFoot(model)}
  </article>
</main>
</body>
</html>
`
}

/** 下载自包含 HTML；失败时提示，不抛出到组件层。 */
export function exportInterviewHtml(
  session: SessionRecord,
  profile: ResumeProfile | null,
): void {
  try {
    const model = buildExportModel(session, profile)
    const html = renderInterviewHtml(model)
    downloadBlob(
      new Blob([html], { type: 'text/html;charset=utf-8' }),
      model.filename,
    )
    message.success(`已导出 ${model.filename}`)
  } catch (error) {
    message.error(error instanceof Error ? error.message : '导出失败')
  }
}

// --------------------------------------------------------------------------- 样式

const EXPORT_STYLE = `
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: #f2f4f8;
  color: #181c29;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI Variable Text', 'Segoe UI',
    'PingFang SC', 'HarmonyOS Sans SC', 'Microsoft YaHei UI', 'Microsoft YaHei',
    'Noto Sans SC', sans-serif;
  font-size: 14px;
  line-height: 1.7;
  -webkit-font-smoothing: antialiased;
}
.page { max-width: 920px; margin: 0 auto; padding: 40px 28px 56px; }
.paper {
  padding: 40px 44px 36px;
  border: 1px solid #e2e5ee;
  border-radius: 14px;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(24, 28, 41, 0.04), 0 18px 44px -28px rgba(24, 28, 41, 0.22);
}
h1, h2, h3, h4, p, ul, ol { margin: 0; }
p, li { overflow-wrap: anywhere; }

.doc-head { padding-bottom: 22px; border-bottom: 1px solid #e9ecf3; }
.eyebrow {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #4753c7;
}
h1 {
  margin-top: 8px;
  font-size: 30px;
  line-height: 1.25;
  letter-spacing: -0.02em;
  font-weight: 650;
}
.doc-meta {
  display: flex;
  flex-wrap: wrap;
  margin-top: 9px;
  font-size: 13px;
  color: #525a6e;
}
.doc-meta span + span::before {
  content: '·';
  margin: 0 8px;
  color: #ccd1de;
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
  margin-top: 18px;
}
.stat {
  padding: 12px 14px;
  border: 1px solid #e2e5ee;
  border-radius: 10px;
  background: #fafbfd;
}
.stat b {
  display: block;
  font-size: 22px;
  line-height: 1.25;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.stat span { font-size: 12px; color: #798196; }

.section { margin-top: 30px; }
.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e9ecf3;
}
.section-head h2 { font-size: 16px; line-height: 1.4; letter-spacing: 0.01em; }
.section-count { font-size: 12px; color: #798196; white-space: nowrap; }

.report {
  margin-top: 26px;
  padding: 20px 22px 22px;
  border: 1px solid #d9ddf5;
  border-radius: 12px;
  background: #f6f7fd;
}
.report .section-head { border-bottom-color: #d9ddf5; padding-bottom: 9px; }
.report .section-head h2 { color: #323c9c; }
.report-body { margin-top: 14px; }
.report-section + .report-section {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px dashed #d9ddf5;
}
.report-section h3 { margin-bottom: 6px; font-size: 14.5px; line-height: 1.6; }
.report-empty { font-size: 13.5px; color: #798196; }

.markdown > :first-child { margin-top: 0; }
.markdown > :last-child { margin-bottom: 0; }
.markdown p { margin: 8px 0; font-size: 13.5px; line-height: 1.8; color: #525a6e; }
.markdown h1, .markdown h2, .markdown h3, .markdown h4 {
  margin: 16px 0 6px;
  line-height: 1.5;
  color: #181c29;
}
.markdown h1 { font-size: 18px; }
.markdown h2 { font-size: 16px; }
.markdown h3 { font-size: 15px; }
.markdown h4 { font-size: 14px; }
.markdown ul, .markdown ol { margin: 8px 0; padding-left: 1.4em; }
.markdown li { margin: 3px 0; font-size: 13.5px; line-height: 1.75; color: #525a6e; }
.markdown a { color: #4753c7; }
.markdown blockquote {
  margin: 10px 0;
  padding: 2px 12px;
  border-left: 3px solid #d9ddf5;
  color: #525a6e;
}
.markdown code {
  padding: 1px 5px;
  border: 1px solid #e2e5ee;
  border-radius: 5px;
  background: #f5f6fa;
  font-family: ui-monospace, 'SFMono-Regular', 'Cascadia Mono', Consolas, monospace;
  font-size: 12.5px;
}
.markdown pre {
  margin: 10px 0;
  padding: 10px 12px;
  border: 1px solid #e2e5ee;
  border-radius: 8px;
  background: #f5f6fa;
  overflow-x: auto;
}
.markdown pre code { padding: 0; border: 0; background: none; }
.markdown table {
  width: 100%;
  margin: 10px 0;
  border-collapse: collapse;
  font-size: 13px;
}
.markdown th, .markdown td { padding: 6px 8px; border: 1px solid #e2e5ee; text-align: left; }
.markdown th { background: #f5f6fa; }

.round-list, .card-list { display: flex; flex-direction: column; gap: 12px; margin-top: 14px; }
.round, .card {
  padding: 16px 18px;
  border: 1px solid #e2e5ee;
  border-radius: 12px;
  background: #ffffff;
}
.round-head { display: flex; align-items: flex-start; gap: 10px; }
.round-q { font-size: 15px; font-weight: 600; line-height: 1.65; }
.round-notes { margin-top: 7px; font-size: 12px; color: #798196; }
.round-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #e9ecf3;
}

.pill {
  flex: none;
  display: inline-block;
  margin-top: 2px;
  padding: 1px 8px;
  border-radius: 999px;
  background: #eceffb;
  color: #4753c7;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 18px;
  white-space: nowrap;
}
.pill.soft { background: #f5f6fa; color: #798196; font-weight: 500; }
.row-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 12.5px;
}
.note { color: #798196; }
.note.warn { color: #8f6128; }

.bubble {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 8px;
  background: #f5f6fa;
}
.bubble + .bubble { margin-top: 7px; }
.bubble.teacher { background: #f6f7fd; }
.speaker {
  flex: none;
  min-width: 56px;
  padding-top: 1px;
  font-size: 12px;
  font-weight: 600;
  color: #798196;
}
.bubble.user .speaker { color: #4753c7; }
.bubble-text {
  min-width: 0;
  font-size: 13.5px;
  line-height: 1.75;
  color: #525a6e;
  white-space: pre-wrap;
}

.assessment {
  display: flex;
  flex-direction: column;
  gap: 11px;
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid #e2e5ee;
  border-radius: 8px;
  background: #f5f6fa;
}
.assessment-title {
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #525a6e;
}
.assessment-block { display: flex; flex-direction: column; gap: 5px; }
.assessment-label { font-size: 12px; font-weight: 600; color: #798196; }
.assessment-sample { padding: 9px 11px; border-radius: 8px; background: #f6f7fd; }
.assessment-sample .assessment-label { color: #4753c7; }
.leaks { margin: 8px 0 0; padding-left: 1.3em; }
.assessment .leaks { margin: 0; }
.leaks li { font-size: 13px; line-height: 1.7; color: #8f6128; }
.feedback { font-size: 13.5px; line-height: 1.75; color: #181c29; }
.sample-text { font-size: 13.5px; line-height: 1.75; color: #181c29; white-space: pre-wrap; }
.off-topic { font-size: 12.5px; color: #8f6128; }

.teach-turns { display: flex; flex-direction: column; gap: 7px; }
.pre { white-space: pre-wrap; font-size: 13.5px; line-height: 1.75; color: #525a6e; }

.card-head { display: flex; align-items: flex-start; gap: 10px; }
.card-index {
  flex: none;
  width: 24px;
  height: 24px;
  margin-top: 2px;
  border-radius: 6px;
  background: #f5f6fa;
  text-align: center;
  font-size: 12px;
  line-height: 24px;
  color: #798196;
  font-variant-numeric: tabular-nums;
}
.card-main { min-width: 0; flex: 1; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; }
.tag {
  padding: 1px 7px;
  border-radius: 999px;
  background: #f5f6fa;
  color: #798196;
  font-size: 11.5px;
  line-height: 18px;
  white-space: nowrap;
}
.tag[data-priority='high'] { background: #f8eae8; color: #a34640; }
.tag[data-priority='medium'] { background: #eceffb; color: #4753c7; }
.tag.seen { background: #eaf3ed; color: #2f7d52; }
.card-q { margin-top: 6px; font-size: 15px; font-weight: 600; line-height: 1.65; }
.card-body { margin-top: 12px; padding-top: 4px; border-top: 1px dashed #e9ecf3; }
.intent { margin-top: 12px; font-size: 13.5px; line-height: 1.7; color: #525a6e; }
.evidence {
  margin-top: 9px;
  padding: 8px 11px;
  border-radius: 8px;
  background: #f5f6fa;
  font-size: 13px;
  line-height: 1.7;
  color: #525a6e;
}
.sub-title {
  margin: 18px 0 8px;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #798196;
}
.follow-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 11px; }
.follow { display: flex; align-items: flex-start; gap: 9px; }
.level {
  flex: none;
  margin-top: 2px;
  padding: 1px 7px;
  border-radius: 999px;
  background: #f5f6fa;
  color: #798196;
  font-size: 11.5px;
  line-height: 18px;
  white-space: nowrap;
}
.level[data-level='L3'] { background: #eceffb; color: #4753c7; }
.follow-main { min-width: 0; flex: 1; }
.follow-q { font-size: 14px; line-height: 1.7; }
.follow-intent { margin-top: 3px; font-size: 12.5px; line-height: 1.65; color: #798196; }

.ref {
  margin-top: 9px;
  padding: 10px 12px;
  border: 1px solid #e2e5ee;
  border-radius: 8px;
  background: #ffffff;
}
.ref-label { font-size: 11.5px; font-weight: 600; color: #4753c7; }
.ref-block { margin-top: 10px; }
.ref-block h4 { margin-bottom: 4px; font-size: 12px; font-weight: 600; color: #798196; }
.ref-list { margin: 0; padding-left: 1.3em; }
.ref-list li { font-size: 13.5px; line-height: 1.7; color: #525a6e; }
.ref-list.warn li { color: #8f6128; }

.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  padding: 2px 8px;
  border: 1px solid #e2e5ee;
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
  color: #525a6e;
}

.warnings {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid #f0dcc2;
  border-radius: 8px;
  background: #f7f0e4;
  color: #8f6128;
  font-size: 13px;
}
.warnings p + p { margin-top: 4px; }

.empty-text {
  margin-top: 14px;
  padding: 24px;
  border: 1px dashed #e2e5ee;
  border-radius: 10px;
  text-align: center;
  font-size: 13.5px;
  color: #798196;
  background: #ffffff;
}

.doc-foot {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 30px;
  padding-top: 14px;
  border-top: 1px solid #e9ecf3;
  font-size: 12px;
  line-height: 1.65;
  color: #798196;
}

@media (max-width: 680px) {
  .page { padding: 0; }
  .paper { padding: 24px 16px 30px; border: 0; border-radius: 0; box-shadow: none; }
  h1 { font-size: 25px; }
  .stats { grid-template-columns: repeat(2, 1fr); }
  .bubble { flex-direction: column; gap: 2px; }
  .round, .card { padding: 14px 14px; }
  .card-body { padding-left: 0; }
  .assessment { padding: 10px 12px; }
}

@page { size: A4; margin: 16mm 14mm; }
@media print {
  body {
    background: #ffffff;
    font-size: 12px;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .page { max-width: none; padding: 0; }
  .paper { padding: 0; border: 0; border-radius: 0; box-shadow: none; }
  .stats { grid-template-columns: repeat(4, 1fr); }
  .round, .card, .attempt, .ref, .bubble, .assessment, .warnings, .report-section {
    break-inside: avoid;
  }
  .doc-foot { break-before: avoid; }
}
`
