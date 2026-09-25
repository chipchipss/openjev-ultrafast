"""Decider 层。替换 jev-ultrafast 的 model.py:choose() 和 field_text()。

硬约束 H2：Decision 层与 Runtime 解耦。
对外契约：
  decider.choose_2b.choose(state, goal, history) -> decision
  decider.field_text_2b.field_text(context) -> (text, helper)
"""
