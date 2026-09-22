"""W08 v3 排错：最小隔离测试，只验证 ChatOpenAI 基础调用能否通。

目的：把 LangGraph 图摘掉，确认是「LLM API 调用本身」的问题（MODEL/BASE_URL 不兼容），
还是图逻辑的问题。报错 input.contents 说明网关期望 Gemini 格式，而 langchain_openai 发 OpenAI messages 格式。

运行（bat 环境，已设 API_KEY/BASE_URL/MODEL）：
  python test_llm.py
"""

import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage


def main():
    API_KEY = os.getenv("API_KEY")
    BASE_URL = os.getenv("BASE_URL")
    CHAT_MODEL = os.getenv("CHAT_MODEL") or os.getenv("MODEL", "deepseek-v4-flash")

    # 只打印模型/网关（不含 API_KEY），便于排查
    print("CHAT_MODEL =", CHAT_MODEL)
    print("BASE_URL   =", BASE_URL)
    print("has KEY    =", bool(API_KEY))

    m = ChatOpenAI(model=CHAT_MODEL, api_key=API_KEY, base_url=BASE_URL)
    try:
        r = m.invoke([HumanMessage("用一句话回复：测试成功")])
        print("调用成功 ->", r.content)
    except Exception as e:
        print("调用失败 ->", type(e).__name__)
        print(str(e)[:400])


if __name__ == "__main__":
    main()
