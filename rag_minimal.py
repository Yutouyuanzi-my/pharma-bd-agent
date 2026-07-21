"""
最小 RAG 演示（学习用 · 纯标准库，零原生依赖）
==============================================
知识库：本项目 README.md
检索：手写 TF-IDF 向量化 + 余弦相似度
生成：把检索片段塞进 prompt，用标准库 urllib 直接调 DeepSeek API

说明：TF-IDF 按词频匹配（关键词重合高=相关），比真实语义 embedding 简单。
可升级：把 _tfidf 换成 OpenAI/DashScope embedding 即变语义检索。
"""
import os
import re
import sys
import json
import math
import urllib.request


# ---------- 0. 读取 .env（手写，不依赖 python-dotenv） ----------
def load_dotenv():
    p = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()


# ---------- 1. 构建知识库（语料） ----------
def load_corpus():
    docs = []
    readme = os.path.join(os.path.dirname(__file__), "README.md")
    if os.path.exists(readme):
        with open(readme, encoding="utf-8") as f:
            docs.append(("README.md", f.read()))
    return docs


def chunk_text(text, size=400, overlap=80):
    """按空行分段；超长段再滑动窗口切。"""
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks = []
    for p in paras:
        if len(p) <= size:
            chunks.append(p.strip())
        else:
            for i in range(0, len(p), size - overlap):
                piece = p[i : i + size].strip()
                if piece:
                    chunks.append(piece)
    return chunks


# ---------- 2. 检索（手写 TF-IDF + 余弦相似度） ----------
def tokenize(text):
    """英文按单词、中文按单字切分（演示够用）。"""
    return re.findall(r"[a-zA-Z]+|[一-龥]", text.lower())


class Retriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.docs = [tokenize(c) for c in chunks]
        n = len(self.docs)
        df = {}
        for d in self.docs:
            for t in set(d):
                df[t] = df.get(t, 0) + 1
        self.idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
        self.doc_vecs = [self._tfidf(d) for d in self.docs]

    def _tfidf(self, tokens):
        tf = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        return {t: c * self.idf.get(t, 0) for t, c in tf.items()}

    @staticmethod
    def _cosine(a, b):
        common = set(a) & set(b)
        num = sum(a[t] * b[t] for t in common)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return num / (na * nb) if na and nb else 0.0

    def retrieve(self, query, k=3):
        qvec = self._tfidf(tokenize(query))
        sims = [self._cosine(qvec, dv) for dv in self.doc_vecs]
        top = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)[:k]
        return [(self.chunks[i], sims[i]) for i in top]


# ---------- 3. 生成（标准库 urllib 调 DeepSeek） ----------
def generate(query, chunks):
    context = "\n\n".join(f"[资料 {i+1}]\n{c}" for i, (c, _) in enumerate(chunks))
    prompt = (
        "你是项目问答助手。请仅基于以下资料回答用户问题；"
        "若资料未提及，请说'资料中未提及'。\n\n"
        f"{context}\n\n问题：{query}"
    )
    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }
    url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    corpus = load_corpus()
    all_chunks = []
    for _name, text in corpus:
        all_chunks.extend(chunk_text(text))
    print(f"[知识库] 共 {len(all_chunks)} 个片段（来自 {len(corpus)} 个文档）")

    retriever = Retriever(all_chunks)
    query = sys.argv[1] if len(sys.argv) > 1 else input("请输入关于本项目的问题：")

    top = retriever.retrieve(query, k=3)
    print(f"\n[检索] 与「{query}」最相关的 3 个片段：")
    for i, (c, s) in enumerate(top):
        print(f"--- 片段{i+1} 相似度={s:.3f} ---\n{c[:300]}\n")

    try:
        ans = generate(query, top)
        print(f"[生成] 基于检索资料作答：\n{ans}")
    except Exception as e:
        print(f"[生成] 调用 DeepSeek 失败（可能无网络/Key）：{e}")
        print("检索部分已正常工作，生成步需联网 + 有效 Key。")
