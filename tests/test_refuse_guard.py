"""生成侧拒答守卫的单元测试（src/pipeline.py::_is_generator_refusal）

★ 这个机制解决的是一个真实缺陷：
  判定层放行后，生成模型仍可能自己输出"知识库中未找到相关依据"。
  此时接口返回 refused=False（看似正常回答），但内容是拒答话术，
  且 sources 里还挂着无关引用 —— 用户无法分辨"没找到"和"这就是答案"。

★ 实现要点：用"以拒答话术开头"而非"包含该话术"来判断，
  避免正常回答中引用了这句话时被误判。
"""
from src.pipeline import _is_generator_refusal


class TestRefusalDetected:
    """应当判为拒答的情形"""

    def test_exact_refusal_text(self):
        assert _is_generator_refusal(
            "知识库中未找到相关依据。建议咨询学校相关部门获取准确信息。"
        ) is True

    def test_refusal_prefix_only(self):
        assert _is_generator_refusal("知识库中未找到相关依据。") is True

    def test_refusal_with_leading_whitespace(self):
        assert _is_generator_refusal("  知识库中未找到相关依据。") is True

    def test_refusal_with_following_guidance(self):
        """拒答话术后面只跟引导性语句，仍应判为拒答。

        实现方式：去掉话术本身后，若剩余部分能被"引导词白名单"完全吸收，
        则视为无实质内容的补充说明。
        """
        assert _is_generator_refusal(
            "知识库中未找到相关依据。建议咨询学校相关部门获取准确信息。"
        ) is True
        assert _is_generator_refusal(
            "知识库中未找到相关依据。请咨询辅导员老师。"
        ) is True

    def test_paraphrase_outside_whitelist(self):
        """★ 已知边界：白名单之外的措辞不会被识别为拒答。

        这里'您''处'不在引导词白名单内，残留字符超过阈值，故返回 False。
        这是【保守设计】的取舍：宁可漏判（当作正常回答）也不扩大白名单，
        以免把"拒答话术 + 真实内容"误判成纯拒答。
        该情形由生成 Prompt 约束（资料不足时只回复固定话术），实际发生概率很低。
        """
        assert _is_generator_refusal(
            "知识库中未找到相关依据。建议您咨询教务处或所在学院。"
        ) is False


class TestNormalAnswerNotMisjudged:
    """不应误判的情形 —— 这是修复中最容易出错的地方"""

    def test_normal_answer_with_citation(self):
        assert _is_generator_refusal(
            "根据规定，考试不及格可以参加补考，补考安排在下一学期第一、二周。[1]"
        ) is False

    def test_answer_quoting_refusal_phrase_mid_sentence(self):
        """★ 关键用例：正常回答中【引用】了拒答话术，不应误判"""
        assert _is_generator_refusal(
            "系统在无法回答时会回复「知识库中未找到相关依据」，"
            "但本条问题是有依据的：补考安排在下一学期第一、二周。[1]"
        ) is False

    def test_empty_answer(self):
        assert _is_generator_refusal("") is False

    def test_whitespace_only(self):
        assert _is_generator_refusal("   \n  ") is False

    def test_answer_mentioning_related_keywords(self):
        assert _is_generator_refusal(
            "关于补考，具体规定见《考试管理办法》第九条。"
        ) is False
