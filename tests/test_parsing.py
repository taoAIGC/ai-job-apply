# -*- coding: utf-8 -*-
"""核心解析/过滤纯函数的单元测试（无需浏览器，纯离线）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import send_greetings as sg  # noqa: E402


class TestParseTitle(unittest.TestCase):
    def test_new_card_format(self):
        text = "快速投递 | 不感兴趣 | AI产品经理 | 30-50K·15薪 | 1-3年 | 本科 | 某某科技 | × | 北京·海淀区"
        self.assertEqual(sg.parse_title(text), "AI产品经理")

    def test_old_card_format(self):
        text = "AI产品经理 | 30-50K·15薪 | 1-3年 | 本科 | 某某科技 | 深圳·南山区·科技园"
        self.assertEqual(sg.parse_title(text), "AI产品经理")

    def test_empty(self):
        self.assertEqual(sg.parse_title(""), "")
        self.assertEqual(sg.parse_title(None), "")


class TestCompanyOfCard(unittest.TestCase):
    def test_new_card_format(self):
        text = "快速投递 | 不感兴趣 | AI产品经理(FDE方向) | 30-50K | 经验不限 | 本科 | 某某科技 | × | 北京·海淀区·学院路"
        self.assertEqual(sg.company_of_card(text), "某某科技")

    def test_old_card_format(self):
        text = "AI产品经理 | 30-50K·15薪 | 1-3年 | 本科 | 进门 | 深圳·南山区·科技园"
        self.assertEqual(sg.company_of_card(text), "进门")

    def test_bare_city(self):
        text = "快速投递 | 不感兴趣 | AI产品经理 | 30-50K | 1-3年 | 本科 | 可梦AI | × | 北京"
        self.assertEqual(sg.company_of_card(text), "可梦AI")

    def test_no_city_fallback_to_last(self):
        text = "AI产品经理 | 30-50K | 1-3年 | 本科 | 某某科技"
        self.assertEqual(sg.company_of_card(text), "某某科技")


class TestCompanyBlocked(unittest.TestCase):
    KW = ["字节", "抖音", "腾讯", "阿里"]

    def test_hit(self):
        self.assertTrue(sg.company_blocked("a | b | 岗位 | 30-50K | x | 本科 | 北京字节跳动 | × | 北京", self.KW))

    def test_case_insensitive(self):
        self.assertTrue(sg.company_blocked("a | b | 岗位 | 30-50K | x | 本科 | OceanBase | × | 北京", ["oceanbase"]))

    def test_miss(self):
        self.assertFalse(sg.company_blocked("a | b | 岗位 | 30-50K | x | 本科 | 某某科技 | × | 北京", self.KW))

    def test_empty_company_safe(self):
        self.assertFalse(sg.company_blocked("", self.KW))


class TestParseKRange(unittest.TestCase):
    def test_range(self):
        self.assertEqual(sg.parse_k_range("30-50K"), (30, 50))
        self.assertEqual(sg.parse_k_range("40 - 60K"), (40, 60))

    def test_single_value(self):
        self.assertEqual(sg.parse_k_range("50K"), (50, 50))

    def test_unparsable(self):
        self.assertIsNone(sg.parse_k_range("面议"))


class TestRiskPattern(unittest.TestCase):
    """风控词表：必须命中平台告警固定措辞，且不能被 JD 正文常用词误伤。"""

    def test_alerts_hit(self):
        for t in ("系统检测到异常", "频繁过度爬取岗位", "请完成安全验证", "访问受限"):
            self.assertIsNotNone(sg.RISK_PATTERN.search(t), t)

    def test_normal_jd_not_hit(self):
        for t in ("负责机构网站数据爬取", "负责数据抓取与清洗", "爬虫工程师", "批量处理数据"):
            self.assertIsNone(sg.RISK_PATTERN.search(t), t)


class TestEnglishGate(unittest.TestCase):
    """英语门槛：硬要求要拦，加分项/海外经验不能误伤（2026-10-19 修）。"""

    def test_hard_requirement_blocked(self):
        for t in ("英语可作为工作语言", "英语流利，能与海外团队协作",
                  "英文读写可以作为工作语言", "英语口语流利"):
            self.assertTrue(sg.jd_requires_english(t), t)

    def test_soft_context_not_blocked(self):
        for t in ("英语可作为工作语言者优先", "英语流利为加分项",
                  "具备英文阅读能力者优先考虑"):
            self.assertEqual(sg.jd_requires_english(t), "", t)

    def test_overseas_experience_not_english(self):
        # 「海外产品经验」是业务经验，不是英语门槛
        self.assertEqual(sg.jd_requires_english("加分项：有 AI 产品、视频、海外产品经验"), "")

    def test_next_sentence_soft_label_not_leaking(self):
        """2026-10-20：下一句的「加分项」不能污染本句的硬要求判定。"""
        text = ("● 英语可作为工作语言,能与全球开发者和客户流畅沟通。"
                " 加分项 ● 有个人开发的AI Agent或开源项目贡献者优先。")
        self.assertTrue(sg.jd_requires_english(text))

    def test_leading_soft_label_still_soft(self):
        """「【加分项】…英语可作为工作语言」这种段首标签仍属加分项，要放行。"""
        text = "【加分项】 具备海外市场或跨文化消费场景经验,英语可作为工作语言"
        self.assertEqual(sg.jd_requires_english(text), "")

    def test_numbered_list_not_polluted_by_later_soft(self):
        """编号列表里第 3 条是英语硬要求，不能被第 5 条的「加分项」带跑。"""
        text = ("3.有海外产品或出海产品经验,英语可作为工作语言 "
                "4.懂AIGC内容生成管线(文生图/文生视频/TTS)的产品化 "
                "5.自己是重度用户,加分项:有开源项目")
        self.assertTrue(sg.jd_requires_english(text))

    def test_dash_list_hard_requirement(self):
        """「工作语言 - 英语可作为工作语言 - …」是硬要求，后面接加分项也不能放行。"""
        text = ("工作语言 - 英语可作为工作语言 - 能够直接研究海外产品、用户和市场 "
                "加分项 - 有开源项目贡献")
        self.assertTrue(sg.jd_requires_english(text))


if __name__ == "__main__":
    unittest.main()
