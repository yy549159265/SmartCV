/** 最近面试回看：作答与讲解按问题合并，回看页与导出 HTML 共用同一套分组与文案。 */

import type { AnswerRecord, TeachingEvent } from '@/api/interview'
import { LEVEL_LABEL } from '@/utils/interview'

export interface ReviewRound {
  key: string
  cardId: string
  question: string
  records: AnswerRecord[]
  teachings: TeachingEvent[]
}

type ReviewEntry =
  | { kind: 'record'; at: string; record: AnswerRecord }
  | { kind: 'teaching'; at: string; teaching: TeachingEvent }

function timeValue(value: string): number {
  const time = Date.parse(value)
  return Number.isNaN(time) ? Number.MAX_SAFE_INTEGER : time
}

/** 问题文本可能夹带换行、全角空格或首尾问号；归一到同一把键才能和讲解合并。 */
function questionKey(question: string): string {
  return question
    .replace(/\s+/g, '')
    .replace(/[?？]+$/, '')
}

/** 按问题出现的时间排序；同一个问题的作答与讲解收在同一条记录里。 */
export function groupReviewRounds(
  records: AnswerRecord[],
  teachings: TeachingEvent[],
): ReviewRound[] {
  const entries: ReviewEntry[] = [
    ...records.map((record): ReviewEntry => ({ kind: 'record', at: record.createdAt, record })),
    ...teachings.map(
      (teaching): ReviewEntry => ({ kind: 'teaching', at: teaching.startedAt, teaching }),
    ),
  ]
  entries.sort((a, b) => timeValue(a.at) - timeValue(b.at))

  const groups = new Map<string, ReviewRound>()
  for (const entry of entries) {
    const cardId = entry.kind === 'record' ? entry.record.cardId : entry.teaching.cardId
    const question = entry.kind === 'record' ? entry.record.question : entry.teaching.question
    // 只按问题文本归组：旧记录可能缺 cardId，或讲解与作答来自同题的不同卡片字段。
    const key = questionKey(question) || `${cardId}\u0000`
    let round = groups.get(key)
    if (!round) {
      round = { key, cardId, question, records: [], teachings: [] }
      groups.set(key, round)
    }
    if (entry.kind === 'record') round.records.push(entry.record)
    else round.teachings.push(entry.teaching)
  }

  return [...groups.values()]
}

export function roundKind(round: ReviewRound): string {
  const record = round.records[0]
  if (record) {
    if (record.level) return `${LEVEL_LABEL[record.level]} 追问`
    return '主问题'
  }
  return '讲解'
}

export function sourceLabel(record: AnswerRecord): string {
  if (record.source === 'reanswer') {
    return record.level ? `${LEVEL_LABEL[record.level]} 重答` : '重答'
  }
  if (record.level) return `${LEVEL_LABEL[record.level]} 追问`
  return '主问题'
}

export function attemptLabel(round: ReviewRound, record: AnswerRecord): string {
  const base = sourceLabel(record)
  if (round.records.length <= 1) return base
  return `第 ${round.records.indexOf(record) + 1} 次 · ${base}`
}

export function outcomeLabel(outcome: TeachingEvent['outcome']): string {
  if (outcome === 'skipped') return '已跳过'
  if (outcome === 'active') return '进行中'
  return ''
}
