"""比較講者聲紋模型（sherpa-onnx，CPU）：速度、區分度、短句辨認、即時分組。

用法：uv run --extra asr python spike/speaker_bench.py
樣本：spike/make_speaker_samples.ps1 產生 spike/out/spk/s<講者>-<句>.wav（每人 4 長句＋2 短句）
"""

import itertools
import random
import time
from pathlib import Path

import numpy as np
import sherpa_onnx
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
MODELS = {
    "CAM++ zh_en": "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",
    "ERes2NetV2 zh": "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx",
    "WeSpeaker ResNet34 en": "wespeaker_en_voxceleb_resnet34_LM.onnx",
}
LONG, SHORT = range(4), (4, 5)

files = sorted((ROOT / "spike" / "out" / "spk").glob("s*-*.wav"))
utts = []
for f in files:
    spk, idx = (int(x) for x in f.stem[1:].split("-"))
    audio, sr = sf.read(f, dtype="float32")
    utts.append({"spk": spk, "idx": idx, "audio": audio, "dur": len(audio) / sr})
print(f"{len(utts)} 段，{len({u['spk'] for u in utts})} 個講者；短句長度 "
      f"{min(u['dur'] for u in utts if u['idx'] in SHORT):.2f}–{max(u['dur'] for u in utts if u['idx'] in SHORT):.2f} 秒")


def cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def eer(same, diff):
    best = (1.0, 0.0)
    for t in np.linspace(-1, 1, 401):
        far = np.mean(np.array(diff) >= t)
        frr = np.mean(np.array(same) < t)
        if abs(far - frr) < abs(best[0]):
            best = (far - frr, (far + frr) / 2)
    return best[1]


def online_cluster(embs, order, threshold):
    """模擬即時分組：同現有講者平均聲紋相似度 ≥ threshold 就歸入，否則開新講者。"""
    centroids, labels = [], {}
    for i in order:
        sims = [cos(embs[i], c / max(n, 1)) for c, n in centroids]
        if sims and max(sims) >= threshold:
            k = int(np.argmax(sims))
            centroids[k] = (centroids[k][0] + embs[i], centroids[k][1] + 1)
        else:
            k = len(centroids)
            centroids.append((embs[i].copy(), 1))
        labels[i] = k
    return labels, len(centroids)


def cluster_accuracy(labels, truth):
    """每個分組歸佢最多數嘅真實講者，計正確比例。"""
    correct = 0
    for k in set(labels.values()):
        members = [truth[i] for i, lab in labels.items() if lab == k]
        correct += max(members.count(s) for s in set(members))
    return correct / len(labels)


for name, filename in MODELS.items():
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(ROOT / "models" / "speaker" / filename), num_threads=2, provider="cpu")
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def embed(audio):
        stream = extractor.create_stream()
        stream.accept_waveform(16000, audio)
        stream.input_finished()
        return np.array(extractor.compute(stream))

    embed(utts[0]["audio"])  # 預熱
    times, embs = [], []
    for u in utts:
        start = time.perf_counter()
        embs.append(embed(u["audio"]))
        times.append((time.perf_counter() - start) * 1000)
    truth = [u["spk"] for u in utts]

    long_ids = [i for i, u in enumerate(utts) if u["idx"] in LONG]
    same = [cos(embs[a], embs[b]) for a, b in itertools.combinations(long_ids, 2) if truth[a] == truth[b]]
    diff = [cos(embs[a], embs[b]) for a, b in itertools.combinations(long_ids, 2) if truth[a] != truth[b]]

    # 短句：同每人 4 長句平均聲紋比較，揀最似嗰個
    cents = {s: np.mean([embs[i] for i in long_ids if truth[i] == s], axis=0) for s in set(truth)}
    short_ids = [i for i, u in enumerate(utts) if u["idx"] in SHORT]
    short_ok = sum(max(cents, key=lambda s: cos(embs[i], cents[s])) == truth[i] for i in short_ids)

    print(f"\n== {name}（{filename}）")
    print(f"  速度：每段中位數 {np.median(times):.0f} ms（CPU 2 threads），維度 {len(embs[0])}")
    print(f"  長句：同一人相似度 {np.mean(same):.2f}（最低 {min(same):.2f}），唔同人 {np.mean(diff):.2f}（最高 {max(diff):.2f}），"
          f"EER {eer(same, diff):.1%}")
    print(f"  短句（≤1 秒）辨認：{short_ok}/{len(short_ids)}")
    for threshold in (0.4, 0.5, 0.6):
        accs, counts = [], []
        for seed in range(20):
            order = list(range(len(utts)))
            random.Random(seed).shuffle(order)
            labels, n = online_cluster(embs, order, threshold)
            accs.append(cluster_accuracy(labels, truth))
            counts.append(n)
        print(f"  即時分組 門檻 {threshold}：準確度 {np.mean(accs):.0%}，分成 {np.mean(counts):.1f} 組（實際 5 人）")
