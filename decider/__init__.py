"""2B Decider 包：Decision 层替换实现（H2）。

接口边界（B）：OpenAI-compatible HTTP，后端经 base_url + model 配置，
不绑定 llama-cpp-python / Ollama / vLLM 任一实现。

子模块直接导入（不做包级预导入，避免 `python -m decider.*` 重复执行）：

    from decider.choose_2b import choose
    from decider.field_text_2b import field_text
"""
