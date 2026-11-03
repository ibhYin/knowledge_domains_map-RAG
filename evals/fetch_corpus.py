"""评测语料拉取：从中文维基百科镜像数据集提取精选词条并入库。

数据源：hf-mirror.com 上的 ffatty/plaintext-wikipedia-full-chinese
（zhwiki 明文全文，10 个 gzip 分片，片内按词条重要性排序，格式为
「标题行\\n正文行\\n空行」循环）。

流程：下载分片（带缓存）→ 流式扫描匹配 corpus_titles.json 精选词条 →
长度过滤（1200-4500 字符，保证每篇 2-7 个分块）→ 缺漏用片内高重要性
词条补足 → 走 service.ingest 入库 → 写 corpus_index.json。

运行：PYTHONPATH=src python evals/fetch_corpus.py [--limit 50] [--no-ingest]
"""

import argparse
import gzip
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SHARD_URLS = [
    "https://hf-mirror.com/datasets/ffatty/plaintext-wikipedia-full-chinese/resolve/main/data/zhwiki_01_of_10.txt.gz",
    "https://huggingface.co/datasets/ffatty/plaintext-wikipedia-full-chinese/resolve/main/data/zhwiki_01_of_10.txt.gz",
]
SHARD_CACHE = ROOT / "data" / "cache" / "zhwiki_01_of_10.txt.gz"
MIN_CHARS, MAX_CHARS = 1200, 4500


def download_shard(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载分片: {url}")
    start = time.monotonic()
    with urllib.request.urlopen(url, timeout=60) as resp, dest.open("wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            out.write(block)
            done += len(block)
            if total and done % (16 << 20) < (1 << 20):
                print(f"  {done / 1e6:.0f}/{total / 1e6:.0f} MB ({time.monotonic() - start:.0f}s)")
    print(f"分片就绪: {dest} ({dest.stat().st_size / 1e6:.0f} MB, {time.monotonic() - start:.0f}s)")


def iter_articles(shard: Path):
    """流式解析「标题\\n正文\\n空行」循环。"""
    with gzip.open(shard, "rt", encoding="utf-8") as f:
        title, body = None, []
        for line in f:
            line = line.rstrip("\n")
            if not line:
                if title is not None and body:
                    yield title, "\n".join(body)
                title, body = None, []
                continue
            if title is None:
                title = line
            else:
                body.append(line)
        if title is not None and body:
            yield title, "\n".join(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="目标语料篇数")
    parser.add_argument("--no-ingest", action="store_true", help="只提取文本不调用入库")
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args()

    manifest = json.loads((ROOT / "evals" / "corpus_titles.json").read_text(encoding="utf-8"))
    wanted: dict[str, str] = {t["title"]: t["category"] for t in manifest["titles"]}
    print(f"精选候选词条 {len(wanted)} 个，目标 {args.limit} 篇")

    if args.force_download or not SHARD_CACHE.exists():
        for url in SHARD_URLS:
            try:
                download_shard(url, SHARD_CACHE)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  源不可用（{type(exc).__name__}），尝试下一个")
        else:
            sys.exit("所有数据源均不可达，请检查网络或手动放置分片到 data/cache/")
    else:
        print(f"使用缓存分片: {SHARD_CACHE}")

    matched: dict[str, tuple[str, str]] = {}   # title -> (category, text)
    fill_candidates: list[tuple[str, str]] = []  # (title, text) 高重要性补足候选
    scanned = 0
    for title, body in iter_articles(SHARD_CACHE):
        scanned += 1
        if len(body) < 300:
            continue
        if title in wanted and title not in matched:
            # 精选词条不限原始长度，统一截取前 MAX_CHARS（首段事实密度最高，口径一致）
            matched[title] = (wanted[title], body[:MAX_CHARS])
        elif len(fill_candidates) < 200 and MIN_CHARS <= len(body) <= MAX_CHARS:
            fill_candidates.append((title, body))
    print(f"扫描 {scanned} 篇；精选命中 {len(matched)}，补足候选 {len(fill_candidates)}")

    selected = list(matched.items())
    if len(selected) < args.limit:
        for title, body in fill_candidates:
            if len(selected) >= args.limit:
                break
            if title not in matched:
                matched[title] = ("general", body)
                selected.append((title, matched[title]))
    selected = selected[:args.limit]

    files = []
    index = []
    for title, (category, body) in selected:
        text = f"{title}\n\n{body}\n"
        files.append((f"{title}.md", text.encode("utf-8")))
        index.append({"title": title, "category": category, "chars": len(body)})
    print(f"选定 {len(files)} 篇")

    if args.no_ingest:
        out_dir = ROOT / "data" / "cache" / "corpus_preview"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, content in files:
            (out_dir / name).write_bytes(content)
        print(f"预览文本写入 {out_dir}")
        return

    from graphrag.pipeline.service import service

    ingested = service.ingest(files)
    by_name = {r["filename"]: r for r in ingested}
    for item in index:
        doc = by_name.get(f"{item['title']}.md", {})
        item["doc_id"] = doc.get("doc_id")
        item["chunk_count"] = doc.get("chunk_count")
    out = ROOT / "data" / "evals" / "corpus_index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": "ffatty/plaintext-wikipedia-full-chinese (zhwiki)",
                               "shard": SHARD_CACHE.name, "count": len(index),
                               "documents": index}, ensure_ascii=False, indent=2), encoding="utf-8")
    total_chunks = sum(i.get("chunk_count") or 0 for i in index)
    print(f"入库完成：{len(index)} 篇 / {total_chunks} 分块，索引写入 {out}")


if __name__ == "__main__":
    main()
