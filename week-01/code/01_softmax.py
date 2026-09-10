# -*- coding: utf-8 -*-
"""
W01 第 2 节实验：手搓 softmax / temperature / top_p
无需 API Key、无需任何第三方包，Python 3.8+ 直接跑。

跑法：
    python softmax.py
    python softmax.py 123     # 传个随机种子，结果可复现
"""
import math
import random
import sys

# 假设模型在这一步算出 6 个候选 token 的得分（logits）
# 场景：信息抽取时，模型看到"归母净"，下一个词可能是：
LOGITS = {"利润": 3.2, "资产": 2.1, "现金": 1.4, "收益": 0.9, "亏损": 0.3, "苹果": -0.5}


def softmax(logits, T=1.0):
    """logits 除以 T 再做 softmax。减最大值是为了防止 exp() 溢出。"""
    m = max(logits.values())
    ex = {k: math.exp((v - m) / T) for k, v in logits.items()}
    s = sum(ex.values())
    return {k: v / s for k, v in ex.items()}


def top_p_keep(probs, p):
    """按累积概率从高到低截断，返回被保留的 token 列表。"""
    kept, cum = [], 0.0
    for k, v in sorted(probs.items(), key=lambda x: -x[1]):
        cum += v
        kept.append(k)
        if cum >= p:
            break
    return kept


def sample(probs, kept):
    """只在保留集合内做加权随机抽样 —— 模型真正的"吐字"动作。"""
    pool = {k: probs[k] for k in kept}
    s = sum(pool.values())
    r = random.random() * s
    acc = 0.0
    for k, v in pool.items():
        acc += v
        if r <= acc:
            return k
    return kept[-1]


def main():
    if len(sys.argv) > 1:
        random.seed(int(sys.argv[1]))

    print("=" * 62)
    print("1. temperature 对概率分布的影响（同一个 logits）")
    print("=" * 62)
    print(f"{'T':<6}" + "".join(f"{k:>9}" for k in LOGITS))
    for T in (0.1, 0.5, 1.0, 2.0):
        p = softmax(LOGITS, T)
        row = "".join(f"{v*100:>8.2f}%" for v in p.values())
        print(f"{T:<6}{row}")

    print()
    print("=" * 62)
    print("2. 固定 top_p=0.9，看不同温度下候选集有多大")
    print("=" * 62)
    for T in (0.1, 0.5, 1.0, 2.0):
        p = softmax(LOGITS, T)
        kept = top_p_keep(p, 0.9)
        print(f"T={T:<5} 保留 {len(kept)} 个候选 -> {kept}")

    print()
    print("=" * 62)
    print("3. 同一个输入抽 20 次，看输出稳不稳（top_p=0.9）")
    print("=" * 62)
    for T in (0.1, 1.0, 2.0):
        p = softmax(LOGITS, T)
        kept = top_p_keep(p, 0.9)
        draws = [sample(p, kept) for _ in range(20)]
        kinds = len(set(draws))
        print(f"T={T:<5} 出现 {kinds} 种结果: {' '.join(draws)}")

    print()
    print("=" * 62)
    print("4. 关键对照：把 '利润' 的分差改小，T=0 还稳吗？")
    print("=" * 62)
    # 模型没把握时：前两名只差 0.05
    close = {"利润": 3.20, "资产": 3.15, "现金": 1.4, "收益": 0.9, "亏损": 0.3, "苹果": -0.5}
    #for T in (0.1, 0.7, 1.0):
    # 修改参数测试
    for T in (0.01, 0.05, 0.1):
        p = softmax(close, T)
        kept = top_p_keep(p, 0.9)
        draws = [sample(p, kept) for _ in range(20)]
        kinds = len(set(draws))
        print(f"T={T:<5} 利润={p['利润']*100:.1f}% 资产={p['资产']*100:.1f}% "
              f"-> 20 次抽到 {kinds} 种: {' '.join(draws)}")
    print()
    print("注意：T=0.1 时'利润'概率再高，它也只是【每次都一样】，")
    print("      不代表【抽对了】。正确性靠 schema 和字典校验，不靠温度。")


if __name__ == "__main__":
    main()
