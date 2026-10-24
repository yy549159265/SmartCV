# 简历解析流程

```
PDF/DOCX ──MinerU──> content_list.json ──清洗──> Block[]
         ──大模型(1次)──> CanonicalResume ──代码排版──> Section[]（返回前端）
```

| 顺序 | 函数 | 做什么 |
|---|---|---|
| 1 | `services/pdf2json.py::parse_with_mineru` | 上传文件给 MinerU，轮询后下载 ZIP，取出 `content_list.json` |
| 2 | `agent.py::normalize_document` | 清洗：去页码/页眉页脚/图片名/重复段落 |
| 3 | `agent.py::structure_resume` | 一次 `llm.invoke`，把原文拆成语义字段（学校、学位、专业、时间） |
| 4 | `utils/build.py::build_canonical_sections` | 纯代码排版，生成 `Section[]` |
| 5 | `utils/validate.py::validate_sections` | 统计原文有没有丢块，只写日志 |

只有第 3 步调模型，模型**不负责排版**；排版固定由代码完成，所以同一份简历结果稳定。

---

## 数据怎么一步步变

### ① MinerU 给的一条表格

```json
{
  "type": "table",
  "table_body": "<table><tr><td>2007.2-2011.6</td><td>山东大学</td><td>经贸 MBA</td><td>硕士学位</td></tr></table>"
}
```

### ② 清洗后变成 Block

```python
Block(id="b0003", text="2007.2-2011.6 | 山东大学 | 经贸 MBA | 硕士学位", kind="table")
```

### ③ 大模型输出 CanonicalResume（只管“是什么”，不管“放哪”）

```json
{
  "personal": {
    "name": "锤子简历",
    "job_title": "项目主管",
    "phone": "18000000000",
    "email": "xiaowang@qq.com",
    "location": "武汉.光谷",
    "website": "www.xiaowang.com",
    "extra": []
  },
  "education": [
    {
      "start": "2007.2",
      "end": "2011.6",
      "school": "山东大学",
      "major": "经贸 MBA",
      "degree": "硕士学位",
      "details": []
    }
  ],
  "skills": [
    {"group": "项目管理", "items": ["PMP", "敏捷开发"]}
  ]
}
```

字段含义固定，见 `schemas/canonical.py`；模型输出用了别名、中文键、`null` 也能被 `normalize_payload` 纠正。

### ④ 代码排版成最终的 Section[]（接口返回的 JSON）

```json
[
  {
    "id": "s02",
    "kind": "section",
    "title": "教育经历",
    "style": {"gap": 8.0},
    "rows": [
      {
        "id": "s02-w03",
        "layout": "horizontal",
        "contents": [],
        "rows": [
          {
            "id": "s02-w01",
            "layout": "vertical",
            "contents": [
              {"id": "s02-c002", "kind": "content", "type": "iconText",
               "content": {"icon": "", "text": "山东大学"}, "style": {}}
            ]
          },
          {
            "id": "s02-w02",
            "layout": "vertical",
            "contents": [
              {"id": "s02-c001", "kind": "content", "type": "twoColumn",
               "content": {"columns": ["硕士学位", "经贸 MBA", "2007.2 - 2011.6"], "separator": "|"},
               "style": {"textAlign": "right"}}
            ]
          }
        ]
      }
    ]
  }
]
```

`horizontal` 的 `rows` 就是左右分栏：左边学校，右边学位 | 专业 | 时间——所以四个字段显示在一行。
（id 只是稳定编号，父子窗口的编号先后不代表层级。）

其他章节同理：

| CanonicalResume | Section 里的排法 |
|---|---|
| `personal` | 第一个章节（无标题）：姓名/职业/电话/地址 左，邮箱/网站 右 |
| `work` / `project` | 一行：公司 · 职位 ｜ 时间；下面每条职责一个 bullet |
| `skills` | 多列（2~3 列），一组一列 |
| `awards` / `certificates` | 每条一行 |
| `other` | 保留原章节标题和内容 |

---

## 模型挂了怎么办

`structure_resume` 超时（120s）、报错、或输出不是合法 JSON 时返回 `None`，自动改走：

```
Block[] ──utils/sections.py 按标题分章──> SectionPlan[] ──utils/build.py::build_sections──> Section[]
```

照样返回 `Section[]`，只是字段拆分没模型路径准。

---

## 模块

- `agent.py`：流程 + 唯一一次 `llm.invoke`
- `schemas/`：数据结构（`models.py` 内部结构、`canonical.py` 模型输出、`resume.py` 前端契约、`store.py` 进度）
- `utils/`：确定性规则（清洗、分章、排版、模板、校验）
- `system_prompt_md2json.md`：第 3 步的提示词
- `template.json`：章节顺序和默认标题
