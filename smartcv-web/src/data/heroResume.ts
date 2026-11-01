import type { Section } from '@/types'

/**
 * 首页 Hero 右侧展示用的演示简历（纯展示数据，不进入 store、不参与任何业务）。
 * 结构与真实简历完全一致，直接走预览渲染链（PreviewSection → PreviewContent），
 * 用户看到的缩略图就是产品真实产出的样子。
 * 布局模式沿用 example/ 里真实简历的写法：横向容器左「公司｜职位」右「时间」。
 */
export const heroResume: Section[] = [
  {
    id: 'hero-header',
    kind: 'section',
    title: '',
    style: { fontSize: 15, gap: 10, lineHeight: 1.5, spaceBefore: 0, titleUnderline: false },
    rows: [
      {
        id: 'hero-header-row',
        layout: 'vertical',
        contents: [
          {
            id: 'hero-name',
            kind: 'content',
            type: 'iconText',
            content: { text: '林知远' },
            style: { fontSize: 36, textAlign: 'center' },
          },
          {
            id: 'hero-role',
            kind: 'content',
            type: 'iconText',
            content: { text: '高级产品经理 · 6 年 B 端经验' },
            style: { textAlign: 'center', color: '#64748b' },
          },
          {
            id: 'hero-contact',
            kind: 'content',
            type: 'twoColumn',
            content: { columns: ['138-0000-0000', 'lin.zhiyuan@smartcv.io', '上海'], separator: ' · ' },
            style: { textAlign: 'center', fontSize: 13, color: '#64748b' },
          },
        ],
      },
    ],
  },
  {
    id: 'hero-intro',
    kind: 'section',
    title: '个人简介',
    style: { fontSize: 14, lineHeight: 1.5, gap: 6, spaceBefore: 6 },
    rows: [
      {
        id: 'hero-intro-row',
        layout: 'vertical',
        contents: [
          {
            id: 'hero-intro-text',
            kind: 'content',
            type: 'iconText',
            content: {
              text: '6 年 B 端产品经验，主导 3 款从 0 到 1 的 SaaS 产品，累计服务 40 万企业用户。擅长复杂业务建模、AI 产品落地与数据驱动增长。',
            },
            style: {},
          },
        ],
      },
    ],
  },
  {
    id: 'hero-work',
    kind: 'section',
    title: '工作经历',
    style: { fontSize: 14, lineHeight: 1.4, gap: 4, spaceBefore: 4 },
    rows: [
      {
        id: 'hero-work1-head',
        layout: 'horizontal',
        contents: [],
        rows: [
          {
            id: 'hero-work1-head-left',
            layout: 'vertical',
            contents: [
              {
                id: 'hero-work1-company',
                kind: 'content',
                type: 'twoColumn',
                content: { columns: ['星云科技', '高级产品经理'], separator: '｜' },
                style: {},
              },
            ],
          },
          {
            id: 'hero-work1-head-right',
            layout: 'vertical',
            contents: [
              {
                id: 'hero-work1-time',
                kind: 'content',
                type: 'timeRange',
                content: { start: '2021.07', end: '至今' },
                style: { textAlign: 'right', color: '#64748b' },
              },
            ],
          },
        ],
      },
      {
        id: 'hero-work1-body',
        layout: 'vertical',
        contents: [
          {
            id: 'hero-work1-list',
            kind: 'content',
            type: 'listText',
            content: {
              listType: 'bullet',
              items: [
                { text: '负责智能客服产品线，年度营收增长 68%' },
                { text: '主导 AI 工单系统上线，客服人效提升 42%' },
              ],
            },
            style: { fontSize: 13 },
          },
        ],
      },
      {
        id: 'hero-work2-head',
        layout: 'horizontal',
        contents: [],
        rows: [
          {
            id: 'hero-work2-head-left',
            layout: 'vertical',
            contents: [
              {
                id: 'hero-work2-company',
                kind: 'content',
                type: 'twoColumn',
                content: { columns: ['云帆网络', '产品经理'], separator: '｜' },
                style: {},
              },
            ],
          },
          {
            id: 'hero-work2-head-right',
            layout: 'vertical',
            contents: [
              {
                id: 'hero-work2-time',
                kind: 'content',
                type: 'timeRange',
                content: { start: '2018.07', end: '2021.06' },
                style: { textAlign: 'right', color: '#64748b' },
              },
            ],
          },
        ],
      },
      {
        id: 'hero-work2-body',
        layout: 'vertical',
        contents: [
          {
            id: 'hero-work2-list',
            kind: 'content',
            type: 'listText',
            content: {
              listType: 'bullet',
              items: [
                { text: '从 0 搭建数据分析平台，次年付费用户突破 10 万' },
                { text: '推动开放平台落地，接入第三方应用 300+ 款' },
              ],
            },
            style: { fontSize: 13 },
          },
        ],
      },
    ],
  },
  {
    id: 'hero-edu',
    kind: 'section',
    title: '教育经历',
    style: { fontSize: 14, lineHeight: 1.4, gap: 4, spaceBefore: 4 },
    rows: [
      {
        id: 'hero-edu-row',
        layout: 'horizontal',
        contents: [],
        rows: [
          {
            id: 'hero-edu-left',
            layout: 'vertical',
            contents: [
              {
                id: 'hero-edu-school',
                kind: 'content',
                type: 'twoColumn',
                content: { columns: ['复旦大学', '计算机科学与技术 · 本科'], separator: '｜' },
                style: {},
              },
            ],
          },
          {
            id: 'hero-edu-right',
            layout: 'vertical',
            contents: [
              {
                id: 'hero-edu-time',
                kind: 'content',
                type: 'timeRange',
                content: { start: '2014.09', end: '2018.06' },
                style: { textAlign: 'right', color: '#64748b' },
              },
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'hero-skill',
    kind: 'section',
    title: '专业技能',
    style: { fontSize: 14, lineHeight: 1.4, gap: 4, spaceBefore: 4 },
    rows: [
      {
        id: 'hero-skill-row',
        layout: 'vertical',
        contents: [
          {
            id: 'hero-skill-tags',
            kind: 'content',
            type: 'tag',
            content: { tags: ['产品规划', '数据分析', '用户研究', 'Axure', 'SQL', 'AI 应用'] },
            style: {},
          },
        ],
      },
    ],
  },
]
