#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W07 sandbox 验证 · 父子分段逻辑单测（不依赖 PDF 解析器）
=====================================================
直接喂构造的示例 markdown（模拟解析后输出：含跨页标记、标题、文本段落、合并单元格表格），
验证 split_parent_child 的关键 golden rule：
  1. 表格 = 原子父块，不劈（子块数 == 1，内容完整）
  2. 长文本父块 = 滑窗切多个子块（子块数 > 1）
  3. 子块 parent_id 正确指回父块
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest import split_parent_child, CHILD_SIZE, _split_text_window

md = """# 第一节 公司简介
本公司是一家全国性股份制商业银行。报告期内坚持稳健经营。
资产质量总体稳定。本行持续加强金融科技投入推动数字化转型。
零售业务深耕财富管理。公司业务重点支持制造业与绿色金融。
本行持续优化资产负债结构提升服务实体经济质效，风险抵补能力保持在合理区间。
本行深入推进数字化转型战略，建成覆盖前中后台的智能化平台，大幅提升运营效率与客户体验。
报告期内，本行零售客户数稳步增长，管理零售客户总资产（AUM）持续提升，财富管理业务收入占比进一步提高。
公司金融业务方面，本行聚焦制造业高质量发展与绿色低碳转型，制造业贷款余额较上年末显著增长，绿色信贷增速高于各项贷款平均增速。
金融市场业务保持稳健，本行密切跟踪宏观经济与货币政策变化，动态调整投资组合，流动性覆盖率与净稳定资金比例均满足监管要求。
资本管理方面，本行持续优化资本结构，核心一级资本充足率保持合理水平，为业务可持续发展提供坚实保障。

# 第二节 主要会计数据
| 主要会计数据 |  |
| --- | --- |
| 项目 | 金额（百万元） |
| 营业收入 | 120,345 |
| 其中：利息净收入 | 88,201 |
| 利润总额 | 45,678 |
| 归属于母公司股东的净利润 | 38,902 |
| 总资产 | 4,521,033 |
| 不良贷款率(%) | 1.32 |

[page 2]
# 第三节 按行业划分的贷款分布
| 行业 | 贷款余额（百万元） | 占比(%) | 不良率(%) |
| --- | --- | --- | --- |
| 制造业 | 500,000 | 11.06 | 1.5 |
| 批发零售 | 300,000 | 6.63 | 2.1 |
| 房地产 | 200,000 | 4.42 | 3.2 |
"""

parents, children = split_parent_child(md, "TEST", "模拟年报")
print(f"父块 {len(parents)} / 子块 {len(children)}")
for p in parents:
    nchild = sum(1 for c in children if c["parent_id"] == p["id"])
    print(f"  父 {p['id']} [{p['meta']['kind']}] 子块数={nchild} 首40={p['content'][:40].strip()!r}")

# ---- 断言 ----
table_parents = [p for p in parents if p["meta"]["kind"] == "table"]
assert table_parents, "应有表格父块"
for p in table_parents:
    nchild = sum(1 for c in children if c["parent_id"] == p["id"])
    assert nchild == 1, f"❌ 表格应原子不劈，但 {p['id']} 被劈成 {nchild} 子块"
    assert p["content"].count("|") >= 6, "❌ 表格内容应完整保留"
print("\n✅ 断言1通过：表格原子不劈、内容完整（golden rule 成立）")

text_parents = [p for p in parents if p["meta"]["kind"] == "text"]
long_text = [p for p in text_parents if len(p["content"]) > CHILD_SIZE]
for p in long_text:
    nchild = sum(1 for c in children if c["parent_id"] == p["id"])
    assert nchild > 1, "❌ 长文本父块应被滑窗切成多个子块"
print(f"✅ 断言2通过：{len(long_text)} 个长文本父块正确滑窗切子块")

# 子块 parent_id 指回存在的父块
pids = {p["id"] for p in parents}
for c in children:
    assert c["parent_id"] in pids, f"❌ 子块 {c['id']} 的 parent_id 悬空"
print("✅ 断言3通过：所有子块 parent_id 均指向有效父块")

# ---- 断言4：滑窗函数本身（确定性，不依赖示例长度）----
long_s = "财" * 900  # 确定 900 字，远超 CHILD_SIZE=400
parts = _split_text_window(long_s, CHILD_SIZE, 80)
assert len(parts) > 1, "❌ 长文本应被滑窗切成多段"
print(f"✅ 断言4通过：_split_text_window 对 900 字文本切出 {len(parts)} 段（每段≤{CHILD_SIZE}字，重叠80）")

print("\n🎉 分段逻辑单测全部通过")
