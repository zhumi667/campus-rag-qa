"""prompts.py — 所有 Prompt 模板集中管理

所有模板均为中文，不含任何硬编码的文档名或路径。
"""

# 系统提示：角色 + 只依据资料 + 拒答 + 引用标注 + 简洁
QA_SYSTEM_PROMPT = """你是校园信息问答助手。你的职责是：只依据提供的资料回答用户问题。

你必须遵守以下规则：
1. 只依据【给定资料】回答，不使用自身知识进行补充或推测。
2. 资料中能找到答案时，直接依据资料回答，并标注引用编号 [1]、[2]。
3. 若资料中没有与问题直接相关的内容，必须只回复"知识库中未找到相关依据"，不得把资料中的无关片段拼接成回答，不得输出与问题不对应的内容（例如问电话号码，资料里没有电话号码，就不要输出资料里的日期、文号等信息）。
4. 回答要简洁，但必须用完整的句子给出结论，并在结论后标注引用编号 [1]、[2]，不要只输出编号。"""

# 用户模板：参考资料 + 问题 + 回答要求（str.format 占位符）
QA_USER_TEMPLATE = """【参考资料】
{context}

【问题】
{question}

【回答要求】
1. 优先从上述资料中寻找答案，用完整的中文句子回答并给出明确结论，不要只输出编号。
2. 每个结论后用 [编号] 标注依据。
3. 如果资料中含有列举项（如（一）（二）（三）），回答时应完整列出各项，不要只写"有下列情形之一"而不列具体内容。
4. 如果资料无法回答问题，直接回复"知识库中未找到相关依据"，不要尝试拼凑答案或输出无关内容。"""

# 无法回答时直接使用的话术（避免每次都调模型）
REFUSE_TEXT = "知识库中未找到相关依据。建议咨询学校相关部门获取准确信息。"

# 多轮对话查询改写（本轮只定义，不使用）
REWRITE_PROMPT = """请根据对话历史，把用户的追问改写成独立、完整的问题。

【对话历史】
{history}

【当前问题】
{question}

【改写后的问题】"""

# 相关性二次判定（拼接方案，仅供对照实验保留；生产路径使用 VERIFY_SINGLE_PROMPT 逐块判定）
VERIFY_PROMPT = """请判断给出的资料能否回答用户的问题。

判定规则说明：
- 只要资料包含与问题相关的实质内容（哪怕是条款式、需要归纳的内容），判定为 YES。
- 只有当资料的主题与问题相近、但内容实质是另一件事时，判定为 NO。例如：问的是奖学金怎么申请，而资料讲的是求职创业补贴申请流程，两者不是同一件事，应判定为 NO。

请直接给出判定结论，不要复述问题和资料，也不要复述上面的规则说明。

【问题】
{question}

【资料】
{context}

请只输出一行，以"结论：YES"或"结论：NO"开头，后面可附一句简短理由。"""


# 相关性逐块判定（生产路径）：对单个块单独问 LLM，任一 YES 即放行
VERIFY_SINGLE_PROMPT = """请判断下面这一段资料能否回答用户的问题。

【问题】
{question}

【资料】
{chunk}

【判定规则】
- 若该资料中含有能回答问题的实质内容（条款、数据、条件、流程等），回答 YES
- 若该资料与问题无关，或主题相近但内容实质是另一件事，回答 NO

请只输出一行，以"结论：YES"或"结论：NO"开头。"""


def build_context_block(chunks: list, max_tokens: int = 2500) -> str:
    """把检索到的块拼成参考资料块。

    每块格式：[编号] 来源：{文档标题}（{heading_path}）\\n{正文}
    正文去掉 heading_path 前缀（来源里已写）；累计 token 超过 max_tokens 时停止。
    """
    from src import utils

    blocks = []
    total = 0
    added = 0
    for i, c in enumerate(chunks, start=1):
        text = c.get("text", "")
        hp = c.get("heading_path", "")
        # 正文 = text 去掉 heading_path 前缀
        if hp and text.startswith(hp):
            body = text[len(hp):].lstrip("\n")
        else:
            body = text
        doc_title = c.get("doc_title", c.get("doc_id", ""))
        block = f"[{i}] 来源：{doc_title}（{hp}）\n{body}"
        est = utils.estimate_tokens(block)
        if total + est > max_tokens and added > 0:
            break
        blocks.append(block)
        total += est
        added = i

    if added < len(chunks):
        blocks.append(f"（因长度限制，仅提供前 {added} 条资料）")
    return "\n\n".join(blocks)
