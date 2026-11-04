"""从 docs/benchmarks/ 已提交的评测数据生成展示图表 → docs/assets/*.png。

只读已提交的基准数据（不读 data/），clone 后可原样复现全部图表：
    PYTHONPATH=src python scripts/make_charts.py
依赖：pip install matplotlib
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "docs" / "benchmarks"
ASSETS = ROOT / "docs" / "assets"

# 中文回退字体链（macOS 优先 PingFang；Linux CI 无 CJK 字体时仅产生警告不影响生成）
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

COLOR_BEFORE, COLOR_AFTER = "#9aa5b1", "#4f6ef7"
METRIC_LABELS = [
    ("recall", "来源召回率"),
    ("citation_precision", "引用正确率"),
    ("faithful_rate", "忠实度"),
    ("quote_exact_rate", "逐字引用通过率"),
    ("honest_refusal_rate", "否定题拒答率"),
]


def load(name: str) -> dict:
    return json.loads((BENCH / name).read_text(encoding="utf-8"))


def pct(value: float | None) -> float:
    return 0.0 if value is None else value * 100


def chart_metrics_current(ax: plt.Axes) -> None:
    """三数据集核心指标分组柱状图（重排序后当次评测）。"""
    runs = [("金标 seed", "after-wiki-gold-seed.json"), ("金标 full", "after-wiki-gold-full.json"),
            ("合成 50 题 full", "after-synthetic-full.json")]
    width = 0.2
    xs = range(len(METRIC_LABELS))
    for i, (label, name) in enumerate(runs):
        data = load(name)["summary"]
        values = [pct(data.get(key)) for key, _ in METRIC_LABELS]
        ax.bar([x + (i - 1) * width for x in xs], values, width, label=label)
    ax.set_xticks(list(xs), [lbl for _, lbl in METRIC_LABELS], fontsize=9)
    ax.set_ylabel("%")
    ax.set_title("核心指标（含来源重排序）")
    ax.set_ylim(0, 108)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=9)


def chart_rerank_before_after(ax: plt.Axes) -> None:
    """金标 seed/full 重排序前后对比。"""
    pairs = [("来源召回率", "recall"), ("引用正确率", "citation_precision"), ("忠实度", "faithful_rate")]
    groups = [("金标 seed", "seed"), ("金标 full", "full")]
    width = 0.19
    xs = range(len(pairs))
    for i, (label, tag) in enumerate(groups):
        before = load(f"baseline-wiki-gold-{tag}.json")["summary"]
        after = load(f"after-wiki-gold-{tag}.json")["summary"]
        xb = [x + (i * 2 - 1.5) * width for x in xs]
        ax.bar(xb, [pct(before.get(k)) for _, k in pairs], width, color=COLOR_BEFORE, alpha=0.85,
               label=f"{label}·重排前" if i == 0 else None)
        xa = [x + (i * 2 - 0.5) * width for x in xs]
        ax.bar(xa, [pct(after.get(k)) for _, k in pairs], width, color=COLOR_AFTER,
               label=f"{label}·重排后" if i == 0 else None)
    ax.set_xticks(list(xs), [lbl for lbl, _ in pairs], fontsize=10)
    ax.set_ylabel("%")
    ax.set_title("来源重排序前 → 后（金标 20 题）")
    ax.set_ylim(0, 108)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=9)


def chart_rank_distribution(ax: plt.Axes) -> None:
    """金标分块在候选列表中的排名分布：before/after（瓶颈②可视化）。"""
    data = load("rank_diagnosis.json")
    bins = list(range(0, 241, 20))
    before, after = [], []
    for row in data["rows"]:
        rb, ra = row["rank_before"], row["rank_after"]
        before.append(min(rb, 999) if rb is not None else 999)
        after.append(min(ra, 999) if ra is not None else 999)

    def counts(ranks: list[int]) -> list[int]:
        out = [0] * (len(bins) - 1)
        for r in ranks:
            if r == 999:  # 候选集中未出现金标块（图扩张未覆盖）
                out[-1] += 1
                continue
            for j in range(len(bins) - 1):
                if bins[j] < r <= bins[j + 1]:
                    out[j] += 1
                    break
        return out

    centers = [(bins[j] + bins[j + 1]) / 2 for j in range(len(bins) - 1)]
    labels = [f"{bins[j] + 1}-{bins[j + 1]}" if j < len(bins) - 2 else "未检出" for j in range(len(bins) - 1)]
    width = 8
    ax.bar([c - width / 2 for c in centers], counts(before), width, color=COLOR_BEFORE, label="重排前")
    ax.bar([c + width / 2 for c in centers], counts(after), width, color=COLOR_AFTER, label="重排后")
    ax.set_xticks(centers, labels, rotation=45, fontsize=8)
    ax.set_ylabel("题数")
    ax.set_title(f"金标分块排名分布（窗口上限 {data['max_answer_sources']}，"
                 f"进窗率 {pct(data['in_window_rate_before']):.0f}% → {pct(data['in_window_rate_after']):.0f}%）")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=9)



def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    figures = [
        ("benchmark-metrics.png", chart_metrics_current, (8, 4.5)),
        ("rerank-before-after.png", chart_rerank_before_after, (8, 4.5)),
        ("gold-rank-dist.png", chart_rank_distribution, (9, 4.5)),
    ]
    for name, drawer, size in figures:
        fig, ax = plt.subplots(figsize=size, dpi=150)
        drawer(ax)
        fig.tight_layout()
        out = ASSETS / name
        fig.savefig(out)
        plt.close(fig)
        print(f"生成 {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
