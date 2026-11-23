"""AI 模拟面试：简历画像 -> 问题包 -> 对话面试 / 清单自测。

模块边界见 SDD 5.7：graph.py 只做 action 分发、检查点与事件出口；
各 *_agent.py 负责一次模型调用；utils/policy.py 负责追问轮次、动态配额、
下一题与问题包校验；schemas/ 是跨层数据结构的唯一出处。
general_answer_agent.py 是通用答案 / 编辑入口：调用方传入输出实体类，模块据此
选择 prompts/general/<片段>.md、自动注入该实体的 JSON Schema，并用同一实体校验
返回值；主问题答案、追问答案与锚点编辑共用这一条调用链。
"""
