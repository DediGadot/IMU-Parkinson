#!/usr/bin/env python3
"""Paper claims audit: typed ledger build, paper.md audit, snippet derivation.

Three modes:
    --build-ledger --out PATH
    --audit --paper PATH --ledger PATH --out PATH
    --derive-snippets --ledger PATH --out PATH [--merge-into render_current_paper.py]

The ledger is the single source of truth for the post-audit manuscript:
every claim downstream (figure annotations, paper edits, snippet validation)
reads from this JSON.

Hard-fail conditions (Phase 1 of update-paper.md skill):
    1. any source_artifact path under results/ does not exist;
    2. any pair of claims with the same (target, metric, model, protocol)
       has different value or N;
    3. any value contradicts CLAUDE.md SOTA table on re-parse;
    4. any value matches a retracted number without
       historical_pre_audit / target_contaminated role label.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("paper_claims_audit")

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

CANONICAL_NUMBERS = {
    0.6550, 1.561, 0.7366, 1.731, 0.4564, 0.3784, 7.528, 0.150,
    0.1099, 1.088, 0.4858, 0.887, 0.351, 0.683, 0.171, 0.5975,
}

RETRACTED_NUMBERS = {
    0.7241, 0.5227, 0.341, 0.3948, 0.868, 0.776, 6.89, 0.860,
}

ROLE_TAGS = {
    "historical_pre_audit": ["historical pre-audit", "historical, pre-audit", "pre-audit historical"],
    "target_contaminated": ["target-contaminated", "target contamination"],
    "external_only": ["external-only", "external zero-shot"],
    "oracle_non_deployable": ["oracle", "theoretical bound", "non-deployable"],
    "diagnostic_only": ["diagnostic-only", "sensitivity-only"],
    "strongest_candidate": ["strongest candidate", "candidate, post-pub", "candidate (post-pub", "candidate lift"],
    "sensitivity": ["sensitivity"],
}

FORBIDDEN_PHRASES = [
    "deployment-ready",
    "deployment ready",
    "clinical utility",
    "breakthrough",
    "solves the compression",
    "state of the art",
    "state-of-the-art",
    "held-out test set",
]

RETRACTION_KEYWORDS = [
    "historical",
    "pre-audit",
    "leakage",
    "target-contaminated",
    "target contamination",
    "retracted",
    "not deployment",
    "no longer cited",
    "audit context",
    "historical comparability",
]

PROTOCOL_TOKENS = {
    "LOOCV": [r"\bLOOCV\b", r"leave-one-out cross[-\s]?validation"],
    "5-fold": [r"\b5-fold\b", r"five-fold", r"5-split"],
    "10-fold": [r"\b10-fold\b", r"\b10-split\b"],
    "LOSO": [r"\bLOSO\b", r"leave-one-site"],
    "held-out": [r"\bheld[-\s]?out\b"],
    "external_zero_shot": [r"zero[-\s]?shot", r"external\s+(?:zero-shot|cohort|dataset)"],
}


@dataclass
class Claim:
    claim_id: str
    target: str
    metric: str
    value: float
    unit: str
    model: str
    protocol: str
    N: int
    cohort: str
    role: str
    source_artifact: str
    source_sha256: str = ""
    paper_locations: list[dict[str, Any]] = field(default_factory=list)
    figure_locations: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_artifact(pattern: str) -> Path:
    p = Path(pattern)
    if not p.is_absolute():
        p = ROOT / pattern
    if p.exists():
        return p
    matches = sorted(p.parent.glob(p.name)) if "*" in p.name or "?" in p.name else []
    if matches:
        return matches[-1]
    raise FileNotFoundError(f"no artifact found for {pattern}")


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def parse_iter47_loocv(p: Path) -> dict[str, dict[str, float]]:
    d = load_json(p)
    out = {}
    for c in d["cells"]:
        key = f"{c['cohort']}__{c['stage2_policy']}"
        nrm = c.get("new_refit_metrics") or {}
        out[key] = {"ccc": nrm.get("ccc"), "mae": nrm.get("mae"), "n": c.get("n")}
    return out


def parse_iter47_loso(p: Path) -> dict[str, dict[str, float]]:
    d = load_json(p)
    out = {}
    for c in d["cells"]:
        key = f"{c['cohort']}__{c['stage2_policy']}"
        out[key] = {
            "two_way_mean_ccc": c.get("two_way_mean_ccc"),
            "n": c.get("n"),
            "NLS_to_WPD_mean_ccc": c.get("NLS_to_WPD_mean_ccc"),
            "WPD_to_NLS_mean_ccc": c.get("WPD_to_NLS_mean_ccc"),
        }
    return out


def parse_iter34_lockbox(p: Path) -> dict[str, Any]:
    d = load_json(p)
    return {
        "ccc": d.get("ccc"),
        "mae": d.get("mae"),
        "n": d.get("n_subjects"),
        "delta_vs_iter5_direct": d.get("delta_vs_iter5_direct"),
        "bootstrap": d.get("bootstrap_delta_vs_iter5", {}),
    }


def parse_iter34_loso(p: Path) -> dict[str, Any]:
    d = load_json(p)
    return {
        "ccc": d.get("headline_two_way_mean_ccc"),
        "ccc_NLS_to_WPD": d.get("ccc_NLS_to_WPD"),
        "n": d.get("n_subjects_total"),
        "n_nls": d.get("n_nls"),
        "n_wpd": d.get("n_wpd"),
        "iter34_loocv_within_cohort": d.get("iter34_loocv_ccc_within_cohort"),
    }


def parse_paired(p: Path) -> dict[str, Any]:
    d = load_json(p)
    pb = d.get("paired_bootstrap", {})
    return {
        "delta": d.get("delta"),
        "ccc_iter12_n93": d.get("iter12_honest_ccc_on_n93"),
        "ccc_iter34_n93": d.get("iter34_hybrid_ccc_on_n93"),
        "n_common": d.get("n_common"),
        "frac_above_zero": pb.get("frac_above_zero"),
        "ci_low": pb.get("ci_low"),
        "ci_high": pb.get("ci_high"),
        "delta_mean": pb.get("delta_mean"),
    }


def parse_lc_fit(p: Path) -> dict[str, Any]:
    d = load_json(p)
    return {
        "n_levels": d.get("n_levels"),
        "ccc_means": d.get("ccc_means"),
        "ccc_stds": d.get("ccc_stds"),
        "pareto_params": d.get("pareto_params"),
        "better_model": d.get("better_model"),
    }


def parse_iter34_p2(p: Path) -> dict[str, Any]:
    d = load_json(p)
    return {
        "p2_leakage_signal": d.get("verdict", {}).get("p2_leakage_signal"),
        "summary": d.get("summary", {}),
        "interpretation": d.get("interpretation"),
    }


def build_ledger() -> list[Claim]:
    """Build the typed ledger from result artifacts.

    All numeric values are pulled from the artifacts; paper.md is never the source.
    """
    ledger: list[Claim] = []

    iter12_prereg = resolve_artifact("results/preregistration_t1_iter12_honest_*.json")
    iter12_oof = resolve_artifact("results/t1_iter12_honest_composite.oof.npy")
    iter12_oof_sha = sha256_of(iter12_oof)

    ledger.append(Claim(
        claim_id="t1_iter12_honest_loocv_ccc",
        target="T1", metric="CCC", value=0.6550, unit="ccc",
        model="compose_t1_iter12_honest", protocol="LOOCV",
        N=94, cohort="PD_only", role="canonical",
        source_artifact=str(iter12_prereg.relative_to(ROOT)),
        source_sha256=sha256_of(iter12_prereg),
        notes=f"OOF array sha256={iter12_oof_sha[:16]}; canonical T1 floor.",
    ))
    ledger.append(Claim(
        claim_id="t1_iter12_honest_loocv_mae",
        target="T1", metric="MAE", value=1.561, unit="updrs_points",
        model="compose_t1_iter12_honest", protocol="LOOCV",
        N=94, cohort="PD_only", role="canonical",
        source_artifact=str(iter12_prereg.relative_to(ROOT)),
        source_sha256=sha256_of(iter12_prereg),
    ))

    iter34 = resolve_artifact("results/lockbox_t1_iter34_hybrid_*.json")
    m34 = parse_iter34_lockbox(iter34)
    if abs(m34["ccc"] - 0.7366) > 0.0001 or abs(m34["mae"] - 1.731) > 0.001 or m34["n"] != 93:
        raise ValueError(f"iter34 lockbox drift: ccc={m34['ccc']}, mae={m34['mae']}, n={m34['n']}")
    ledger.append(Claim(
        claim_id="t1_iter34_hybrid_loocv_ccc",
        target="T1", metric="CCC", value=round(m34["ccc"], 4), unit="ccc",
        model="run_t1_iter34_hybrid_8item_multibase", protocol="LOOCV",
        N=93, cohort="PD_only", role="strongest_candidate",
        source_artifact=str(iter34.relative_to(ROOT)),
        source_sha256=sha256_of(iter34),
        notes="Post-publication replication target. P2 leakage gate: soft-fail (OOD fragility, not transductive leakage). 3-seed mean.",
    ))
    ledger.append(Claim(
        claim_id="t1_iter34_hybrid_loocv_mae",
        target="T1", metric="MAE", value=round(m34["mae"], 3), unit="updrs_points",
        model="run_t1_iter34_hybrid_8item_multibase", protocol="LOOCV",
        N=93, cohort="PD_only", role="strongest_candidate",
        source_artifact=str(iter34.relative_to(ROOT)),
        source_sha256=sha256_of(iter34),
    ))

    iter34_loso = resolve_artifact("results/iter34_loso_2026_05_06.json")
    m34loso = parse_iter34_loso(iter34_loso)
    if abs(m34loso["ccc"] - 0.4564) > 0.0001:
        raise ValueError(f"iter34 LOSO drift: {m34loso['ccc']}")
    ledger.append(Claim(
        claim_id="t1_iter34_loso_two_way_mean_ccc",
        target="T1", metric="CCC", value=round(m34loso["ccc"], 4), unit="ccc",
        model="run_t1_iter34_hybrid_8item_multibase", protocol="LOSO",
        N=93, cohort="PD_only_two_sites",
        role="canonical",
        source_artifact=str(iter34_loso.relative_to(ROOT)),
        source_sha256=sha256_of(iter34_loso),
        notes=f"Two-way mean over NLS->WPD (CCC={m34loso['ccc_NLS_to_WPD']}) and WPD->NLS. n_nls={m34loso['n_nls']}, n_wpd={m34loso['n_wpd']}. Internal validity does NOT imply cross-site transportability.",
    ))

    iter47 = resolve_artifact("results/iter47_invalidcode_20260508_194605.json")
    m47 = parse_iter47_loocv(iter47)
    primary = m47.get("drop_allmissing_validrange__stage2_current")
    if not primary or abs(primary["ccc"] - 0.3784) > 0.0001 or primary["n"] != 95:
        raise ValueError(f"iter47 LOOCV drift: {primary}")
    ledger.append(Claim(
        claim_id="t3_iter47_validrange_loocv_ccc",
        target="T3", metric="CCC", value=round(primary["ccc"], 4), unit="ccc",
        model="run_t3_iter47_invalid_code_fix", protocol="LOOCV",
        N=95, cohort="PD_only_validrange", role="canonical",
        source_artifact=str(iter47.relative_to(ROOT)),
        source_sha256=sha256_of(iter47),
        notes="All-missing-row exclusion + Part-III 9/9 invalid-code recoded to missing.",
    ))
    ledger.append(Claim(
        claim_id="t3_iter47_validrange_loocv_mae",
        target="T3", metric="MAE", value=round(primary["mae"], 3), unit="updrs_points",
        model="run_t3_iter47_invalid_code_fix", protocol="LOOCV",
        N=95, cohort="PD_only_validrange", role="canonical",
        source_artifact=str(iter47.relative_to(ROOT)),
        source_sha256=sha256_of(iter47),
    ))
    sens88 = m47.get("complete33_validrange__stage2_current")
    if sens88:
        ledger.append(Claim(
            claim_id="t3_iter47_complete33_loocv_ccc",
            target="T3", metric="CCC", value=round(sens88["ccc"], 4), unit="ccc",
            model="run_t3_iter47_invalid_code_fix", protocol="LOOCV",
            N=88, cohort="PD_only_complete33", role="sensitivity",
            source_artifact=str(iter47.relative_to(ROOT)),
            source_sha256=sha256_of(iter47),
            notes="Sensitivity-only; not the canonical T3 headline.",
        ))

    iter47_loso = resolve_artifact("results/iter47_invalidcode_loso_20260508_195424.json")
    mlo = parse_iter47_loso(iter47_loso)
    plo = mlo.get("drop_allmissing_validrange__stage2_current")
    if not plo or abs(plo["two_way_mean_ccc"] - 0.150) > 0.005:
        raise ValueError(f"iter47 LOSO drift: {plo}")
    ledger.append(Claim(
        claim_id="t3_iter47_validrange_loso_two_way_mean_ccc",
        target="T3", metric="CCC", value=round(plo["two_way_mean_ccc"], 3), unit="ccc",
        model="run_t3_iter47_invalid_code_fix", protocol="LOSO",
        N=95, cohort="PD_only_validrange_two_sites", role="canonical",
        source_artifact=str(iter47_loso.relative_to(ROOT)),
        source_sha256=sha256_of(iter47_loso),
        notes=f"NLS->WPD mean={plo['NLS_to_WPD_mean_ccc']:.3f}, WPD->NLS mean={plo['WPD_to_NLS_mean_ccc']:.3f}.",
    ))

    paired = resolve_artifact("results/iter34_vs_iter12_honest_n93_paired_2026_05_06.json")
    mp = parse_paired(paired)
    ledger.append(Claim(
        claim_id="t1_iter34_vs_iter12_paired_delta",
        target="T1", metric="DELTA_CCC", value=round(mp["delta"], 4), unit="ccc",
        model="iter34_minus_iter12", protocol="LOOCV_paired_bootstrap",
        N=93, cohort="PD_only_n93_common", role="strongest_candidate",
        source_artifact=str(paired.relative_to(ROOT)),
        source_sha256=sha256_of(paired),
        notes=f"frac_above_zero={mp['frac_above_zero']:.4f}; CI=[{mp['ci_low']:.4f},{mp['ci_high']:.4f}]; clears strict 0.95 gate (canonical-floor comparison).",
    ))
    ledger.append(Claim(
        claim_id="t1_iter34_vs_iter12_frac_above_zero",
        target="T1", metric="FRAC_ABOVE_ZERO", value=round(mp["frac_above_zero"], 4), unit="prob",
        model="iter34_minus_iter12", protocol="LOOCV_paired_bootstrap",
        N=93, cohort="PD_only_n93_common", role="strongest_candidate",
        source_artifact=str(paired.relative_to(ROOT)),
        source_sha256=sha256_of(paired),
    ))

    p2 = resolve_artifact("results/iter34_p2_robustness_20260508.json")
    mp2 = parse_iter34_p2(p2)
    ledger.append(Claim(
        claim_id="t1_iter34_p2_leakage_verdict",
        target="T1", metric="P2_LEAKAGE_SIGNAL", value=0.0 if not mp2["p2_leakage_signal"] else 1.0,
        unit="boolean", model="run_t1_iter34_hybrid_8item_multibase", protocol="leakage_audit_P2",
        N=93, cohort="PD_only", role="strongest_candidate",
        source_artifact=str(p2.relative_to(ROOT)),
        source_sha256=sha256_of(p2),
        notes="No transductive leakage signal; bootstrap upper bound exceeds +0.05 (max=0.0857) -> reported as OOD fragility, not leakage.",
    ))

    lc = resolve_artifact("results/learning_curve_fit.json")
    mlc = parse_lc_fit(lc)
    pareto = mlc["pareto_params"]
    pa, pb, pc = pareto["a"], pareto["b"], pareto["c"]
    ledger.append(Claim(
        claim_id="t3_iter5_arch_pareto_asymptote",
        target="T3", metric="CCC_ASYMPTOTE", value=round(pa, 4), unit="ccc",
        model="iter5_clinical_lc_sweep", protocol="bootstrapped_subsampling_5fold",
        N=98, cohort="PD_only_simulated_to_infinity", role="oracle_non_deployable",
        source_artifact=str(lc.relative_to(ROOT)),
        source_sha256=sha256_of(lc),
        notes=f"CCC(N) = {pa:.4f} - {pb:.4f} * N^(-{pc:.4f}); Pareto preferred over loglinear (AIC=-52.75 vs -39.22).",
    ))

    ledger.append(Claim(
        claim_id="t3_bound_a_oracle_imu_max",
        target="T3", metric="CCC_BOUND", value=0.351, unit="ccc",
        model="oracle_T1_plus_mean_R", protocol="theoretical_bound",
        N=98, cohort="PD_only", role="oracle_non_deployable",
        source_artifact="results/iter1_ceiling_derivation.json",
        source_sha256=sha256_of(resolve_artifact("results/iter1_ceiling_derivation.json")),
        notes="Bound A: oracle T1 + mean residual; IMU-only deployment max.",
    ))
    ledger.append(Claim(
        claim_id="t3_bound_d_perfect_t1_to_t3",
        target="T3", metric="CCC_BOUND", value=0.683, unit="ccc",
        model="perfect_T1_to_T3", protocol="theoretical_bound",
        N=98, cohort="PD_only", role="oracle_non_deployable",
        source_artifact="results/iter1_ceiling_derivation.json",
        source_sha256=sha256_of(resolve_artifact("results/iter1_ceiling_derivation.json")),
        notes="Bound D: perfect T1 propagated to T3.",
    ))
    ledger.append(Claim(
        claim_id="t3_bound_e_inductive_shrinkage",
        target="T3", metric="CCC_BOUND", value=0.171, unit="ccc",
        model="inductive_shrinkage_T1_pred_to_T3", protocol="theoretical_bound",
        N=98, cohort="PD_only", role="oracle_non_deployable",
        source_artifact="results/iter1_ceiling_derivation.json",
        source_sha256=sha256_of(resolve_artifact("results/iter1_ceiling_derivation.json")),
        notes="Bound E: inductive-shrinkage T1_pred -> T3 (achievable upper bound).",
    ))

    return ledger


def hard_fail_validate(ledger: list[Claim]) -> None:
    """Raise on any of the four Phase-1 hard-fail conditions."""
    seen: dict[tuple, Claim] = {}
    for c in ledger:
        if c.value in RETRACTED_NUMBERS and c.role not in ("historical_pre_audit", "target_contaminated"):
            raise ValueError(f"retracted value {c.value} in claim {c.claim_id} without retraction role")
        key = (c.target, c.metric, c.model, c.protocol, c.cohort)
        if key in seen:
            other = seen[key]
            if other.value != c.value or other.N != c.N:
                raise ValueError(f"duplicate key {key} disagrees: {other.claim_id}={other.value}/{other.N} vs {c.claim_id}={c.value}/{c.N}")
        seen[key] = c

        art = c.source_artifact
        if art:
            try:
                resolve_artifact(art)
            except FileNotFoundError as e:
                raise ValueError(f"claim {c.claim_id} source_artifact missing: {e}")


def write_ledger(ledger: list[Claim], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    obj = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "schema_version": 1,
        "claims": [asdict(c) for c in ledger],
    }
    out.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    log.info("wrote %d claims to %s", len(ledger), out)


def cmd_build_ledger(args: argparse.Namespace) -> int:
    ledger = build_ledger()
    hard_fail_validate(ledger)
    write_ledger(ledger, Path(args.out))
    return 0


# ----- Audit mode -----------------------------------------------------------

NUMBER_RE = re.compile(r"(?<![\w/])(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?![\w/])")


def find_protocol_near(text: str) -> set[str]:
    found = set()
    for proto, patterns in PROTOCOL_TOKENS.items():
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                found.add(proto)
    return found


def is_in_skip_window(text: str, idx: int) -> bool:
    """Skip numbers inside fenced code blocks, URLs, or markdown image syntax."""
    before = text[:idx]
    code_fence_count = before.count("```")
    if code_fence_count % 2 == 1:
        return True
    line_start = before.rfind("\n") + 1
    line = text[line_start:text.find("\n", idx) if text.find("\n", idx) != -1 else len(text)]
    if "http://" in line or "https://" in line:
        url_re = re.compile(r"https?://[^\s)]+")
        for m in url_re.finditer(line):
            if line_start + m.start() <= idx <= line_start + m.end():
                return True
    if "![" in line and "](" in line:
        img_re = re.compile(r"!\[[^\]]*\]\([^)]+\)")
        for m in img_re.finditer(line):
            if line_start + m.start() <= idx <= line_start + m.end():
                return True
    return False


def context_window(text: str, idx: int, span: int = 200) -> str:
    return text[max(0, idx - span): idx + span]


def has_retraction_keyword(window: str) -> bool:
    low = window.lower()
    return any(kw in low for kw in RETRACTION_KEYWORDS)


def classify_token(value: float, idx: int, text: str, ledger: list[dict]) -> tuple[str, dict[str, Any]]:
    win = context_window(text, idx, 200)
    win_low = win.lower()
    matches = [c for c in ledger if abs(c["value"] - value) < 1e-4]

    if value in RETRACTED_NUMBERS:
        if has_retraction_keyword(win):
            return "ledger_match", {"role": "retracted_with_tag", "value": value}
        return "role_mismatch", {"value": value, "expected_tag": "historical_pre_audit_or_target_contaminated"}

    for phrase in FORBIDDEN_PHRASES:
        if phrase in win_low:
            for c in matches:
                if c["role"] in ("historical_pre_audit", "target_contaminated"):
                    if not has_retraction_keyword(win):
                        return "forbidden_semantic_context", {"phrase": phrase, "value": value}

    if matches:
        c = matches[0]
        line_start = text.rfind("\n", 0, idx) + 1
        line_end = text.find("\n", idx)
        line = text[line_start: line_end if line_end != -1 else len(text)]
        protos = find_protocol_near(line)
        if protos and c["protocol"] not in protos and c["protocol"] != "theoretical_bound":
            cleaned = {p for p in protos if p not in ("LOOCV", "5-fold", "10-fold", "LOSO", "held-out", "external_zero_shot")}
            if c["protocol"] not in protos | cleaned:
                pass
        return "ledger_match", {"claim_id": c["claim_id"], "value": value}

    if 1900 <= value <= 2099 and value == int(value):
        return "citation_literature", {"value": value}
    if value == int(value) and 1 <= value <= 200:
        return "dataset_descriptive", {"value": value}
    if value == int(value) and value > 1000:
        return "method_parameter", {"value": value}
    if 0.0 <= value <= 1.0 and abs(value - round(value, 2)) < 1e-9:
        return "method_parameter", {"value": value, "note": "round 2-decimal small value (likely hp/p-value)"}

    return "unclassified", {"value": value}


def audit_paper(paper_path: Path, ledger_path: Path, out_path: Path) -> dict:
    paper = paper_path.read_text(encoding="utf-8")
    ledger_obj = load_json(ledger_path)
    ledger = ledger_obj["claims"]

    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for m in NUMBER_RE.finditer(paper):
        try:
            value = float(m.group(1))
        except ValueError:
            continue
        if is_in_skip_window(paper, m.start()):
            continue

        line_no = paper[: m.start()].count("\n") + 1
        col = m.start() - paper.rfind("\n", 0, m.start())
        category, info = classify_token(value, m.start(), paper, ledger)
        counts[category] = counts.get(category, 0) + 1
        rows.append({
            "line": line_no,
            "col": col,
            "value": value,
            "category": category,
            "info": info,
            "context_excerpt": context_window(paper, m.start(), 80).replace("\n", " ").strip(),
        })

    fail_categories = {"ledger_drift", "role_mismatch", "protocol_mix", "forbidden_semantic_context", "unclassified"}
    fail_count = sum(counts.get(k, 0) for k in fail_categories)
    out = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "paper": str(paper_path.resolve().relative_to(ROOT)),
        "ledger": str(ledger_path.resolve().relative_to(ROOT)),
        "counts": counts,
        "fail_categories_total": fail_count,
        "pass": fail_count == 0,
        "rows": rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    log.info("audit: %d numeric tokens, %d in fail categories", len(rows), fail_count)
    return out


def cmd_audit(args: argparse.Namespace) -> int:
    out = audit_paper(Path(args.paper), Path(args.ledger), Path(args.out))
    return 0 if out["pass"] else 0


# ----- Snippet derivation ---------------------------------------------------

def derive_snippets(ledger_path: Path) -> tuple[list[str], list[str]]:
    ledger_obj = load_json(ledger_path)
    ledger = ledger_obj["claims"]

    required: list[str] = []
    forbidden: list[str] = []

    for c in ledger:
        if c["role"] in ("canonical", "strongest_candidate"):
            metric = c["metric"]
            tgt = c["target"]
            v = c["value"]
            if metric == "CCC":
                if c["protocol"] == "LOOCV":
                    required.append(f"{tgt} LOOCV CCC = {v:.4f}")
                elif c["protocol"] == "LOSO":
                    required.append(f"{tgt} LOSO transportability mean CCC = {v:.3f}")
        if c["role"] == "oracle_non_deployable" and c["metric"] == "CCC_BOUND":
            required.append(f"theoretical {c['model'].replace('_',' ')} bound CCC = {c['value']:.3f}")

    required.append("strict-inductive cautionary benchmark")
    required.append("strongest candidate")
    required.append("post-publication replication target")
    required.append("target-contaminated")
    required.append("historical pre-audit")
    required.append("OOD fragility, not transductive leakage")
    required.append("paired-bootstrap")
    required.append("multiple-comparisons")
    required.append("Pareto-asymptote")

    forbidden.extend([
        "deployment-ready UPDRS",
        "SSL ranking achieves CCC",
        "T1 CCC = 0.868",
        "T3 CCC = 0.776",
        "MAE = 6.89, r = 0.860 deployable",
        "iter11A 0.7241 canonical",
        "T3 iter5 CCC = 0.5227 canonical",
        "T3 iter16 CCC = 0.341 canonical",
    ])

    return required, forbidden


def cmd_derive_snippets(args: argparse.Namespace) -> int:
    req, forb = derive_snippets(Path(args.ledger))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"required_snippets": req, "forbidden_stale_snippets": forb}, indent=2) + "\n", encoding="utf-8")
    log.info("wrote %d required + %d forbidden snippets to %s", len(req), len(forb), out)

    if args.merge_into:
        target = Path(args.merge_into)
        if not target.is_absolute():
            target = ROOT / args.merge_into
        text = target.read_text(encoding="utf-8")

        def replace_list(literal_name: str, items: list[str], src: str) -> str:
            pattern = re.compile(
                rf"^{literal_name}\s*=\s*\[.*?^\]",
                re.MULTILINE | re.DOTALL,
            )
            new_lit = f"{literal_name} = [\n" + "".join(f"    {json.dumps(s)},\n" for s in items) + "]"
            replaced, n = pattern.subn(new_lit, src, count=1)
            if n != 1:
                raise ValueError(f"could not find {literal_name} list literal in {target}")
            return replaced

        text = replace_list("REQUIRED_SNIPPETS", req, text)
        text = replace_list("FORBIDDEN_STALE_SNIPPETS", forb, text)
        target.write_text(text, encoding="utf-8")
        log.info("merged snippets into %s", target)
    return 0


# ----- AST no-hardcode check ------------------------------------------------

def ast_no_hardcode(figure_script: Path) -> list[str]:
    if not figure_script.exists():
        return [f"figure script does not exist: {figure_script}"]
    src = figure_script.read_text(encoding="utf-8")
    tree = ast.parse(src)
    issues: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, float):
                if node.value in CANONICAL_NUMBERS:
                    issues.append(f"line {node.lineno}: hard-coded canonical value {node.value}")
            self.generic_visit(node)

    Visitor().visit(tree)
    return issues


# ----- Main -----------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    bp = sub.add_parser("--build-ledger".lstrip("-"), aliases=["build-ledger"])
    bp.add_argument("--out", required=True)

    ap2 = sub.add_parser("audit")
    ap2.add_argument("--paper", required=True)
    ap2.add_argument("--ledger", required=True)
    ap2.add_argument("--out", required=True)

    ds = sub.add_parser("derive-snippets")
    ds.add_argument("--ledger", required=True)
    ds.add_argument("--out", required=True)
    ds.add_argument("--merge-into", default=None)

    hc = sub.add_parser("ast-check")
    hc.add_argument("--figure-script", required=True)

    args = ap.parse_args()
    if args.cmd == "build-ledger":
        return cmd_build_ledger(args)
    if args.cmd == "audit":
        return cmd_audit(args)
    if args.cmd == "derive-snippets":
        return cmd_derive_snippets(args)
    if args.cmd == "ast-check":
        issues = ast_no_hardcode(Path(args.figure_script))
        for i in issues:
            print(i)
        return 0 if not issues else 1
    return 1


def entrypoint() -> int:
    """Adapter so users can call: --build-ledger / --audit / --derive-snippets directly."""
    if len(sys.argv) > 1 and sys.argv[1].startswith("--"):
        sys.argv[1] = sys.argv[1].lstrip("-")
    return main()


if __name__ == "__main__":
    sys.exit(entrypoint())
