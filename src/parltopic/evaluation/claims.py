"""Recompute every number that README.md and technical_report.md report, from published files.

    parltopic fetch-results          # prediction files from the GitHub release into results/
    parltopic claims                 # recompute, compare with the stated values, exit 1 on mismatch

Each claim names its eval set, its prediction file (or the keyword baseline) and the metric.
Scoring uses `score_results`: undecided answers (uncertain, not_evaluable, failed) are left out
of precision/recall and reported as coverage.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from parltopic.evaluation.run import keyword_predictions, score_binary, score_results
from parltopic.topics import load_topic

E1_DEV = "data/eval/e1_digitalisation_dev.jsonl"
E1_TEST = "data/eval/e1_digitalisation_test.jsonl"
E4_DVS = "data/eval/e4_dvs.jsonl"
DIGI = "configs/topics/digitalisation.yaml"
RELEASE = "results-2026-10-18"


@dataclass(frozen=True)
class Claim:
    claim_id: str
    eval_set: str
    source: str  # results file, or "keyword:<topic yaml>"
    metric: str  # "f1", "precision", "recall", "macro_f1", "f1@lang=de", "assigned_count", ...
    stated: float


def _claims() -> list[Claim]:
    rows = []

    def add(claim_id, eval_set, source, **metrics):
        for metric, stated in metrics.items():
            rows.append(Claim(claim_id, eval_set, source, metric.replace("__", "@"), stated))

    kw = f"keyword:{DIGI}"
    # Headline: frozen configuration on the test split, and the keyword baseline.
    add("test.frozen", E1_TEST, "results/ma_test.jsonl", precision=0.875, recall=0.877,
        f1=0.876, macro_f1=0.907)
    rows += [Claim("test.frozen", E1_TEST, "results/ma_test.jsonl", f"f1@{g}", v)
             for g, v in (("lang=de", 0.897), ("lang=fr", 0.849), ("lang=it", 0.846),
                          ("level=federal", 0.854), ("level=cantonal", 0.898))]
    add("test.keyword", E1_TEST, kw, precision=0.87, recall=0.55, f1=0.674)
    rows += [Claim("test.keyword", E1_TEST, kw, f"f1@{g}", v)
             for g, v in (("lang=de", 0.644), ("lang=fr", 0.677), ("lang=it", 0.756))]
    add("test.v3_first_prompt", E1_TEST, "results/e1_test_70b_v3.jsonl", f1=0.849)
    add("test.v3_thinking", E1_TEST, "results/e1_test_70b_v3_think.jsonl", f1=0.872)
    # DVS list (positives only): affairs assigned.
    add("dvs.frozen", E4_DVS, "results/ma_dvs.jsonl", assigned_count=27)
    add("dvs.keyword", E4_DVS, kw, assigned_count=19)
    # Ad-hoc topics against Curia subject areas.
    for topic, final, frozen, kw_f1 in (("migration", 0.874, 0.762, 0.717),
                                        ("health", 0.805, 0.656, 0.571),
                                        ("transport", 0.784, 0.642, 0.545)):
        eval_set = f"data/eval/e2_adhoc_{topic}.jsonl"
        add(f"adhoc.{topic}.final", eval_set, f"results/final_adhoc_{topic}.jsonl", f1=final)
        add(f"adhoc.{topic}.frozen_policy", eval_set, f"results/ma_adhoc_{topic}.jsonl", f1=frozen)
        add(f"adhoc.{topic}.keyword", eval_set, f"keyword:configs/topics/adhoc/{topic}.yaml",
            f1=kw_f1)
    # Dev ladder.
    add("dev.keyword", E1_DEV, kw, f1=0.640)
    add("dev.v1", E1_DEV, "results/e1_dev_70b_v1.jsonl", f1=0.720)
    add("dev.v2", E1_DEV, "results/e1_dev_70b_v2.jsonl", f1=0.797)
    add("dev.v3", E1_DEV, "results/e1_dev_70b_v3.jsonl", f1=0.814)
    add("dev.frozen", E1_DEV, "results/m_dev_A.jsonl", precision=0.933, recall=0.839, f1=0.883,
        macro_f1=0.915)
    add("dev.8b", E1_DEV, "results/e1_dev_8b_v2.jsonl", f1=0.426)
    add("dev.fewshot", E1_DEV, "results/e1_dev_70b_v2_fewshot3.jsonl", f1=0.789)
    add("dev.v2_thinking", E1_DEV, "results/e1_dev_70b_v2_think.jsonl", f1=0.866)
    add("dev.documents_on_frozen", E1_DEV, "results/m_dev_B.jsonl", f1=0.886)
    add("dev.thinking_on_frozen", E1_DEV, "results/m_dev_C.jsonl", f1=0.883)
    return rows


def _value(claim: Claim, root: str | Path = ".") -> float:
    root = Path(root)
    eval_set = root / claim.eval_set
    if claim.source.startswith("keyword:"):
        predictions = keyword_predictions(eval_set, load_topic(root / claim.source[8:]))
        report = {"assigned": score_binary(eval_set, predictions)}
        assigned = sum(predictions.values())
    else:
        report = score_results(eval_set, root / claim.source)
        assigned = report["assigned"].get("statuses", {}).get("assigned", 0)
    if claim.metric == "assigned_count":
        return assigned
    metric, _, group = claim.metric.partition("@")
    return report["assigned"][group or "all"][metric]


def check(root: str | Path = ".", tolerance: float = 0.0005) -> dict:
    results = []
    for claim in _claims():
        path = Path(root) / claim.source
        if not claim.source.startswith("keyword:") and not path.exists():
            results.append({**claim.__dict__, "value": None, "ok": False, "note": "missing file"})
            continue
        value = _value(claim, root)
        results.append({**claim.__dict__, "value": value,
                        "ok": abs(value - claim.stated) <= tolerance})
    return {"claims": results, "all_ok": all(r["ok"] for r in results),
            "files": sorted({r["source"] for r in results if r["source"].startswith("results/")})}


def files_for_release() -> list[str]:
    """Prediction files (and manifests / thinking answers) that the claims need."""
    out = []
    for source in sorted({c.source for c in _claims() if c.source.startswith("results/")}):
        for candidate in (source, source + ".manifest.json",
                          source.replace(".jsonl", ".thinking.jsonl")):
            if Path(candidate).exists() and candidate not in out:
                out.append(candidate)
    return out


def describe(report: dict) -> str:
    lines = ["| Claim | Metric | Stated | Recomputed | OK |", "|---|---|---:|---:|---|"]
    for r in report["claims"]:
        value = "missing" if r["value"] is None else f"{r['value']:.3f}".rstrip("0").rstrip(".")
        lines.append(f"| {r['claim_id']} | {r['metric']} | {r['stated']} | {value} | "
                     f"{'yes' if r['ok'] else '**no**'} |")
    return "\n".join(lines)


if __name__ == "__main__":
    report = check()
    print(describe(report))
    print(json.dumps({"all_ok": report["all_ok"]}))
    raise SystemExit(0 if report["all_ok"] else 1)


RELEASE_URL = (
    "https://github.com/Felipe3052/hackapertus-openparldata/releases/download/"
    f"{RELEASE}/{RELEASE}.tar.gz"
)
RELEASE_SHA256 = "fbd69f15bf54c51104629e6f3629caca6722bb92323dbad752d98bdf450e38bd"


def fetch_results(root: str | Path = ".", url: str = RELEASE_URL,
                  expected_sha256: str = RELEASE_SHA256) -> list[str]:
    """Download the published prediction files and unpack them under results/."""
    import hashlib
    import io
    import subprocess
    import tarfile
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        if url != RELEASE_URL or error.code not in {403, 404}:
            raise
        # Private repositories require the user's existing gh authentication; no key is logged.
        payload = subprocess.run([
            "gh", "api", "repos/Felipe3052/hackapertus-openparldata/releases/assets/653741007",
            "-H", "Accept: application/octet-stream",
        ], check=True, capture_output=True).stdout
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("Published results archive SHA256 mismatch")
    base = (Path(root) / "results").resolve()
    pending = []
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            target = (Path(root) / member.name).resolve()
            if not member.isfile() or not target.is_relative_to(base):
                raise ValueError(f"Unexpected archive entry: {member.name}")
            contents = archive.extractfile(member).read()
            if target.exists() and target.read_bytes() != contents:
                raise FileExistsError(f"Existing local results differ: {target}")
            pending.append((member.name, target, contents))
    for _, target, contents in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(contents)
    return [name for name, _, _ in pending]


def pack_results(target: str | Path) -> list[str]:
    """Write the release archive with every file the claims need."""
    import tarfile

    files = files_for_release()
    with tarfile.open(target, "w:gz") as archive:
        for name in files:
            archive.add(name)
    return files
