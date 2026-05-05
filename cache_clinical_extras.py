"""Cache clinical extras (LEDD, time-since-dose, demographics, MDS-UPDRS Part 1).

PURPOSE
-------
Extract intake patient-state covariates from the WearGait-PD demographic CSV for use as
Stage-1 Ridge regressors in the T3 (UPDRS-III) iter5 pipeline. All features are
RECORDED BEFORE the gait IMU session — there is no information leakage from the
target (MDS-UPDRS Part 3, hy, obs_subscore).

Output:
  results/clinical_extras.csv               — feature table (one row per PD subject)
  results/clinical_extras.csv.manifest.json — provenance + leakage attestation

Inputs:
  results/pd_demographic_clinical_v1.csv    — (header on row 2, encoded UTF-8 with stray bytes)
  results/ablation_v3_features.csv          — for V2 cohort SID cross-check

Tomlinson-2010 LEDD conversion table embedded below; entacapone/tolcapone applied
as a multiplier on TOTAL levodopa.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Tomlinson 2010 LEDD conversion factors (mg LED per mg drug).
# Reference: Tomlinson CL et al. Mov Disord. 2010;25(15):2649-53. PMID 21069833.
# Public, published table — no clinical-trial-secret status.
# ---------------------------------------------------------------------------
LEDD_FACTORS: dict[str, float] = {
    "levodopa_ir": 1.0,
    "levodopa_cr": 0.75,
    "levodopa_er": 0.75,            # Rytary, Sinemet ER
    "levodopa_gel": 1.11,            # Duopa intestinal gel
    "pramipexole": 100.0,
    "ropinirole": 20.0,
    "rotigotine": 30.0,              # 1 mg/24h patch ≈ 30 mg LED
    "selegiline_oral": 10.0,
    "selegiline_orodispersible": 80.0,
    "rasagiline": 100.0,
    "amantadine": 1.0,
    "safinamide": 100.0,
    "entacapone_multiplier": 0.33,   # multiplier on TOTAL LEVODOPA
    "tolcapone_multiplier": 0.50,
    "apomorphine": 10.0,
}

DRUG_LEVODOPA = {"levodopa_ir", "levodopa_cr", "levodopa_er", "levodopa_gel"}
DRUG_AGONIST = {"pramipexole", "ropinirole", "rotigotine", "apomorphine"}
DRUG_OTHER = {
    "selegiline_oral", "selegiline_orodispersible",
    "rasagiline", "amantadine", "safinamide",
}

# ---------------------------------------------------------------------------
# Word-to-int helper for "one tablet", "two times daily", etc.
# ---------------------------------------------------------------------------
WORD_TO_INT: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8,
}


@dataclass(frozen=True)
class DrugContribution:
    """One parsed medication line."""
    drug: str
    dose_mg: float
    freq_per_day: float
    daily_dose_mg: float
    factor: float
    led_mg: float


# ---------------------------------------------------------------------------
# Drug identification regexes (case-insensitive on lowercased line).
# Order matters: more-specific patterns first (Stalevo, CR, ER, gel) before
# the catch-all carbidopa-levodopa IR.
# ---------------------------------------------------------------------------
RE_STALEVO = re.compile(r"\b(stalevo|carbidopa.?levodopa.?entacapone)\b", re.I)
RE_LEVO_GEL = re.compile(r"\b(duopa|intestinal\s+gel)\b", re.I)
RE_LEVO_ER = re.compile(r"\b(rytary|extended.release|er\s+capsule|er\s+tablet)\b", re.I)
RE_LEVO_CR = re.compile(r"\b(sinemet\s*cr|controlled.release|\bcr\b)\b", re.I)
RE_LEVO_IR = re.compile(r"\b(carbidopa.?levodopa|sinemet)\b", re.I)
RE_PRAMIPEXOLE = re.compile(r"\b(pramipexole|mirapex)\b", re.I)
RE_ROPINIROLE = re.compile(r"\b(ropinirole|requip)\b", re.I)
RE_ROTIGOTINE = re.compile(r"\b(rotigotine|neupro)\b", re.I)
RE_SELEGILINE_ZELAPAR = re.compile(r"\b(zelapar|orodispersible)\b", re.I)
RE_SELEGILINE = re.compile(r"\b(selegiline|eldepryl)\b", re.I)
RE_RASAGILINE = re.compile(r"\b(rasagiline|azilect)\b", re.I)
RE_AMANTADINE = re.compile(r"\b(amantadine|symmetrel|gocovri)\b", re.I)
RE_SAFINAMIDE = re.compile(r"\b(safinamide|xadago)\b", re.I)
RE_APOMORPHINE = re.compile(r"\b(apomorphine|apokyn|kynmobi)\b", re.I)
RE_ENTACAPONE = re.compile(r"\b(entacapone|comtan)\b", re.I)
RE_TOLCAPONE = re.compile(r"\b(tolcapone|tasmar)\b", re.I)

# Levodopa "X-Y mg" / "X-Y-Z mg" — Y (or Y for Stalevo) is the levodopa dose.
RE_LEVO_HYPHEN_DOSE = re.compile(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?\s*mg", re.I)

# Generic "<NUMBER> mg" / "<NUMBER> MG" / "<NUMBER>mg" — for agonists, MAOI, etc.
# Excludes mcg by requiring exact 'mg' (with optional space) and no leading 'mc'.
RE_GENERIC_MG = re.compile(r"(?<![a-zA-Z])(\d+(?:\.\d+)?)\s*(?:mg|MG)\b")

# Time-list pattern: "at 7am, 10am, 1pm, 3:30pm and 10pm" → count of 5
RE_TIME_LIST = re.compile(
    r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
    re.I,
)

# "X x/day" / "X x day" / "Xx daily" / "X-x daily" — informal frequency
RE_FREQ_X_DAY = re.compile(r"(\d+)\s*x\s*(?:/|\s+)?\s*(?:day|daily)\b", re.I)

# Number-of-times via "Take ... 4 times per day" already covered by RE_FREQ_TIMES
# but plain numerals "4 times per day" without spaces also work.

# "Take N tablets" / "Take one capsule" / "Take 2 (two) tablets"
RE_TAKE_TABLETS = re.compile(
    r"take\s+(\d+(?:\.\d+)?|one|two|three|four|five|six)\s*(?:\(\w+\))?\s*"
    r"(?:tablets?|capsules?|caps?|pills?|patch(?:es)?)",
    re.I,
)

# "N tablets" generic (without "Take" prefix; supports "1.5 tablets", "TWO TABLETS")
RE_NUM_TABLETS = re.compile(
    r"(\d+(?:\.\d+)?|one|two|three|four|five|six)\s+(?:tablets?|capsules?|caps?|pills?)",
    re.I,
)

# Frequency: "X times a day", "X (xxx) times daily", "twice a day", "three times daily"
RE_FREQ_TIMES = re.compile(
    r"(\d+|one|two|three|four|five|six|once|twice|thrice)\s*(?:\(\w+\))?\s*times?\s+"
    r"(?:a\s+day|per\s+day|daily|day)",
    re.I,
)

# "every X hours" / "every 4 (four) hours"
RE_FREQ_HOURS = re.compile(r"every\s+(\d+)\s*(?:\(\w+\))?\s*hours?", re.I)

# Single-token frequency abbreviations (whole word)
RE_FREQ_ABBR = re.compile(r"(?<![A-Za-z])(BID|TID|QID|QHS|QID|QD)(?![A-Za-z])")

# "as needed" / "PRN" — skip
RE_PRN = re.compile(r"\b(as\s*needed|PRN)\b", re.I)

# Standalone scheduling words: "nightly", "daily", "every morning", "at night", "at bedtime"
RE_DAILY = re.compile(
    r"\b(daily|every\s+morning|every\s+evening|nightly|every\s+day|"
    r"at\s+night|at\s+bedtime|once\s+a\s+day|once\s+daily)\b",
    re.I,
)
RE_TWICE = re.compile(r"\btwice(?:\s+a\s+day|\s+daily|\s+per\s+day)?\b", re.I)


def _to_int(token: str) -> Optional[float]:
    """Convert numeric or word token to float; returns None if unparseable."""
    if token is None:
        return None
    s = str(token).strip().lower()
    if not s:
        return None
    if s in WORD_TO_INT:
        return float(WORD_TO_INT[s])
    if s == "once":
        return 1.0
    if s == "twice":
        return 2.0
    if s == "thrice":
        return 3.0
    try:
        return float(s)
    except ValueError:
        return None


def _identify_drug(line: str) -> tuple[Optional[str], int]:
    """Return (canonical drug key, start index of drug-name match) or (None, -1).

    NOTE: order matters. Stalevo and gel checked before generic levodopa; ER and CR
    before IR. The start-index is used to locate the drug-specific dose context.
    """
    m = RE_STALEVO.search(line)
    if m:
        return ("levodopa_ir", m.start())  # Stalevo's levodopa fraction is IR
    m = RE_LEVO_GEL.search(line)
    if m:
        return ("levodopa_gel", m.start())
    # ER markers
    er = RE_LEVO_ER.search(line)
    if er and (RE_LEVO_IR.search(line) or "rytary" in line.lower()):
        return ("levodopa_er", er.start())
    cr = RE_LEVO_CR.search(line)
    if cr and RE_LEVO_IR.search(line):
        return ("levodopa_cr", cr.start())
    m = RE_LEVO_IR.search(line)
    if m:
        return ("levodopa_ir", m.start())
    for rx, key in (
        (RE_PRAMIPEXOLE, "pramipexole"),
        (RE_ROPINIROLE, "ropinirole"),
        (RE_ROTIGOTINE, "rotigotine"),
        (RE_SELEGILINE_ZELAPAR, "selegiline_orodispersible"),
        (RE_SELEGILINE, "selegiline_oral"),
        (RE_RASAGILINE, "rasagiline"),
        (RE_AMANTADINE, "amantadine"),
        (RE_SAFINAMIDE, "safinamide"),
        (RE_APOMORPHINE, "apomorphine"),
    ):
        m = rx.search(line)
        if m:
            return (key, m.start())
    return (None, -1)


def _extract_dose_mg(line: str, drug: str, drug_pos: int = 0) -> Optional[float]:
    """Extract per-unit dose in mg, searching only NEAR the drug-name match.

    For levodopa drugs: pattern "X-Y mg" or "X-Y-Z mg" where Y is levodopa dose.
    For all others: first "<num> mg" match within ±90 chars of drug name (mostly after).

    Localizing the search avoids picking up doses from other drugs in comma-soup
    free-text columns (e.g., NLS036's "Clonazepam 1 mg, ... Rytary 780 mg").
    """
    # Local context: 30 chars before drug-name, up to 200 after (to capture
    # "Carbidopa-Levodopa Extended Release Capsules 735 mg" + frequency).
    start = max(0, drug_pos - 30)
    end = min(len(line), drug_pos + 200)
    ctx = line[start:end]

    if drug in DRUG_LEVODOPA:
        m = RE_LEVO_HYPHEN_DOSE.search(ctx)
        if m:
            # Stalevo "25-100-200" or Sinemet "25-100" — second number is levodopa
            return float(m.group(2))
        # Fallback: any "N mg" close to drug name (covers rare monotherapy levodopa)
        m2 = RE_GENERIC_MG.search(ctx)
        if m2:
            v = float(m2.group(1))
            # Sanity: a single levodopa unit is in [25, 250] mg. Reject obvious
            # totals or unrelated doses.
            if 10.0 <= v <= 300.0:
                return v
        return None
    # Agonists / MAOI / other — first "<num> mg" within drug context.
    m = RE_GENERIC_MG.search(ctx)
    if m:
        return float(m.group(1))
    return None


def _extract_tablets_per_dose(line: str) -> float:
    """Extract tablets/capsules per dose; default 1.0."""
    m = RE_TAKE_TABLETS.search(line)
    if m:
        v = _to_int(m.group(1))
        if v is not None and v > 0:
            return v
    m2 = RE_NUM_TABLETS.search(line)
    if m2:
        v = _to_int(m2.group(1))
        if v is not None and v > 0:
            return v
    return 1.0


def _extract_frequency_per_day(line: str, drug_pos: int = 0) -> Optional[float]:
    """Extract dosing frequency per day. Returns None if PRN/unschedulable.

    Searches a wider context after the drug-name match (~250 chars) to capture
    instructions like "Take 2 capsules at 7am, 10am, 1pm, 3:30pm and 10pm".
    """
    # Use wide context for frequency (instructions follow drug name in this dataset).
    end = min(len(line), drug_pos + 350)
    ctx = line[max(0, drug_pos - 10):end]

    if RE_PRN.search(ctx):
        return None
    m = RE_FREQ_TIMES.search(ctx)
    if m:
        v = _to_int(m.group(1))
        if v is not None:
            return v
    m = RE_FREQ_X_DAY.search(ctx)
    if m:
        v = _to_int(m.group(1))
        if v is not None:
            return v
    m = RE_FREQ_HOURS.search(ctx)
    if m:
        try:
            n = float(m.group(1))
            if n > 0:
                # "every 4 hours while awake" — common for PD; assume waking 16h ≈ 4 doses
                if "while awake" in ctx.lower() or "during the day" in ctx.lower():
                    return float(int(16.0 / n))
                return 24.0 / n
        except ValueError:
            pass
    m = RE_FREQ_ABBR.search(ctx)
    if m:
        abbr = m.group(1).upper()
        return {"BID": 2.0, "TID": 3.0, "QID": 4.0, "QHS": 1.0, "QD": 1.0}[abbr]
    if RE_TWICE.search(ctx):
        return 2.0
    # Time-list count: "at 7am, 10am, 1pm, 3:30pm and 10pm" → 5 doses
    times = RE_TIME_LIST.findall(ctx)
    if len(times) >= 2:
        return float(len(times))
    if RE_DAILY.search(ctx):
        return 1.0
    return None


def _is_patch(line: str) -> bool:
    """Rotigotine-style patches deliver continuous dose; freq=1/day, tablets=1."""
    return bool(re.search(r"\bpatch\b", line, re.I))


def _is_expired_or_not_taking(line: str) -> bool:
    """Skip 'Expired' or 'Patient not taking' annotations."""
    s = line.lower()
    if "(expired)" in s or "patient not taking" in s:
        return True
    return False


def _split_med_lines(text: str) -> list[str]:
    """Split free-text medication block into one drug per line.

    Heuristic: split on newlines/tabs, then merge orphan continuation tabs.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    # Replace tabs that act as field separators within a line — keep newlines as separators.
    parts = re.split(r"[\r\n]+", text)
    out = []
    for p in parts:
        p = p.strip().lstrip("\t ").strip()
        if p:
            out.append(p)
    return out


def parse_medications(current_meds: str, pd_med_dose: str) -> tuple[list[DrugContribution], list[str]]:
    """Parse the two medication free-text columns and return drug contributions.

    Returns:
        (contributions, unrecognized_lines)
    """
    seen: set[str] = set()
    contributions: list[DrugContribution] = []
    unrecognized: list[str] = []
    has_entacapone = False
    has_tolcapone = False

    lines: list[str] = []
    for src in (current_meds, pd_med_dose):
        if isinstance(src, str):
            for line in _split_med_lines(src):
                key = re.sub(r"\s+", " ", line).strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                lines.append(line)

    for line in lines:
        if _is_expired_or_not_taking(line):
            continue

        # Capture COMT modifiers regardless of whether line is a primary drug.
        if RE_ENTACAPONE.search(line):
            has_entacapone = True
        if RE_TOLCAPONE.search(line):
            has_tolcapone = True

        drug, drug_pos = _identify_drug(line)
        if drug is None:
            # Only flag lines that look like real PD drug attempts; skip non-PD lines silently.
            continue

        dose_mg = _extract_dose_mg(line, drug, drug_pos=drug_pos)
        if dose_mg is None or dose_mg <= 0:
            unrecognized.append(f"NO-DOSE: {line[:120]}")
            continue

        if _is_patch(line):
            tablets = 1.0
            freq = 1.0  # patch is continuous; one effective application per day
        else:
            tablets = _extract_tablets_per_dose(line)
            freq = _extract_frequency_per_day(line, drug_pos=drug_pos)

        if freq is None or freq <= 0:
            # Without frequency we cannot compute LEDD honestly — skip rather than guess.
            unrecognized.append(f"NO-FREQ: {line[:120]}")
            continue

        daily_dose = dose_mg * tablets * freq
        factor = LEDD_FACTORS[drug]
        led = daily_dose * factor

        contributions.append(DrugContribution(
            drug=drug,
            dose_mg=dose_mg,
            freq_per_day=freq,
            daily_dose_mg=daily_dose,
            factor=factor,
            led_mg=led,
        ))

    # Dedup conflicting prescriptions for the SAME (drug, dose) by keeping the
    # entry with the LARGEST daily_dose (handles both verbatim duplicates between
    # CM and PD-Med-Dose AND contradictory parses like "14 caps once daily" vs
    # "3 caps 4x daily AND 2 nightly" where both describe 14 caps/day total).
    by_key: dict[tuple, DrugContribution] = {}
    for c in contributions:
        key = (c.drug, round(c.dose_mg, 2))
        prev = by_key.get(key)
        if prev is None or c.daily_dose_mg > prev.daily_dose_mg:
            by_key[key] = c
    contributions = list(by_key.values())

    # Apply COMT multiplier on TOTAL levodopa (post-sum).
    if has_entacapone or has_tolcapone:
        boosted = []
        bonus_mult = 1.0
        if has_entacapone:
            bonus_mult *= (1.0 + LEDD_FACTORS["entacapone_multiplier"])  # ×1.33
        if has_tolcapone:
            bonus_mult *= (1.0 + LEDD_FACTORS["tolcapone_multiplier"])   # ×1.50
        for c in contributions:
            if c.drug in DRUG_LEVODOPA:
                boosted.append(DrugContribution(
                    drug=c.drug,
                    dose_mg=c.dose_mg,
                    freq_per_day=c.freq_per_day,
                    daily_dose_mg=c.daily_dose_mg,
                    factor=c.factor * bonus_mult,
                    led_mg=c.led_mg * bonus_mult,
                ))
            else:
                boosted.append(c)
        contributions = boosted

    return contributions, unrecognized


def aggregate_ledd(contribs: list[DrugContribution]) -> dict[str, float]:
    """Sum LED contributions by drug class."""
    total_levo = sum(c.led_mg for c in contribs if c.drug in DRUG_LEVODOPA)
    total_ag = sum(c.led_mg for c in contribs if c.drug in DRUG_AGONIST)
    total_other = sum(c.led_mg for c in contribs if c.drug in DRUG_OTHER)
    total = total_levo + total_ag + total_other
    return {
        "ledd_levodopa": float(total_levo),
        "ledd_dopamine_agonist": float(total_ag),
        "ledd_other": float(total_other),
        "ledd_total": float(total),
        "ledd_on_levodopa": int(total_levo > 0),
        "ledd_on_agonist": int(total_ag > 0),
    }


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------
def _parse_time_of_day(s: object) -> Optional[datetime]:
    """Parse times like '12:30 PM', '12:00pm', '8:00AM', '1:45 PM' into a datetime
    on a fixed reference date (1970-01-01).

    Returns None for missing / unparseable.
    """
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    text = str(s).strip()
    if not text or text in {"-", "Unknown"}:
        return None
    # Normalize: remove spaces between time and AM/PM
    norm = re.sub(r"\s+", " ", text).strip()
    # Some entries have lowercase 'pm' attached: "12:00pm"
    norm = re.sub(r"(\d)(am|pm|AM|PM)\b", r"\1 \2", norm)
    norm_upper = norm.upper()
    for fmt in ("%I:%M %p", "%I %p", "%H:%M"):
        try:
            return datetime.strptime(norm_upper, fmt)
        except ValueError:
            continue
    return None


def hours_between(test_str: object, dose_str: object) -> float:
    """Hours between last dose and test session. Wraps to next day if dose appears
    after test (assume dose was previous day). Caps at 24h. NaN if either missing."""
    t_test = _parse_time_of_day(test_str)
    t_dose = _parse_time_of_day(dose_str)
    if t_test is None or t_dose is None:
        return float("nan")
    delta = (t_test - t_dose).total_seconds() / 3600.0
    if delta < 0:
        delta += 24.0
    if delta > 24.0:
        delta = 24.0
    return float(delta)


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------
MISSING_TOKENS = {"-", "", "Unknown", "unknown", "n/a", "N/A", "NA", "nan"}


def coerce_yn(val: object) -> float:
    """Coerce 'Yes'/'No' to 1.0/0.0; missing → NaN. 'Cane' (a device name) → 1.0."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return float("nan")
    s = str(val).strip()
    if s in MISSING_TOKENS:
        return float("nan")
    sl = s.lower()
    if sl in {"yes", "y", "true"}:
        return 1.0
    if sl in {"no", "n", "false"}:
        return 0.0
    # Unknown free-text answers (e.g. specific device names) → treat as Yes.
    return 1.0


def coerce_int_or_nan(val: object) -> float:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return float("nan")
    s = str(val).strip()
    if s in MISSING_TOKENS:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def coerce_part1(val: object) -> float:
    """MDS-UPDRS Part 1 item 0-4, missing → NaN."""
    return coerce_int_or_nan(val)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
REQUIRED_COLS = [
    "Subject ID",
    "Current Medications",
    "PD Medication Dose",
    "Time of last medication dose",
    "Time of research session",
    "Days since Part III Clinical Evaluation",
    "Assistive Device used during testing?",
    "PT/OT status",
    "Race",
    "MDSUPDRS_1-1",
    "MDSUPDRS_1-2",
    "MDSUPDRS_1-3",
    "MDSUPDRS_1-4",
    "MDSUPDRS_1-5",
    "MDSUPDRS_1-6",
    "MDSUPDRS_1-7",
    "MDSUPDRS_1-8",
    "MDSUPDRS_1-9",
    "MDSUPDRS_1-10",
    "MDSUPDRS_1-11",
    "MDSUPDRS_1-12",
    "MDSUPDRS_1-13",
]

PART1_COLS = [f"MDSUPDRS_1-{i}" for i in range(1, 14)]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, stderr=subprocess.DEVNULL
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default="results/pd_demographic_clinical_v1.csv")
    ap.add_argument("--output", default="results/clinical_extras.csv")
    ap.add_argument("--manifest", default="results/clinical_extras.csv.manifest.json")
    ap.add_argument(
        "--verify_against_v2",
        default="results/ablation_v3_features.csv",
        help="Cross-check sids match the V2 PD cohort",
    )
    args = ap.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    manifest_path = Path(args.manifest)

    if not input_path.exists():
        print(f"ERROR: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # NOTE: header is on row 2 (row 0 = category labels).
    df = pd.read_csv(input_path, header=1, low_memory=False, encoding_errors="ignore")

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        print(f"ERROR: required columns missing from input: {missing}", file=sys.stderr)
        sys.exit(2)

    print(f"Loaded {len(df)} rows × {len(df.columns)} cols from {input_path}")
    print(f"Cohort sample: {df['Subject ID'].head(5).tolist()}")
    print()

    # --- Per-subject extraction ---
    rows: list[dict] = []
    all_unrecognized: list[tuple[str, str]] = []  # (sid, line)
    n_validation_print = 5
    n_printed = 0

    for _, r in df.iterrows():
        sid = str(r["Subject ID"]).strip()
        contribs, unrec = parse_medications(
            r.get("Current Medications", ""), r.get("PD Medication Dose", "")
        )
        for u in unrec:
            all_unrecognized.append((sid, u))

        led = aggregate_ledd(contribs)
        h_since = hours_between(
            r.get("Time of research session"), r.get("Time of last medication dose")
        )

        race_raw = r.get("Race")
        race_str = "" if (race_raw is None or (isinstance(race_raw, float) and np.isnan(race_raw))) else str(race_raw).strip()
        race_white = int(race_str.lower() == "white")

        part1_vals = [coerce_part1(r.get(c)) for c in PART1_COLS]
        part1_arr = np.array(part1_vals, dtype=float)
        n_present = int(np.sum(~np.isnan(part1_arr)))
        if n_present == 0:
            part1_sum = float("nan")
        else:
            part1_sum = float(np.nansum(part1_arr))

        out_row: dict = {
            "sid": sid,
            "ledd_total": led["ledd_total"],
            "ledd_levodopa": led["ledd_levodopa"],
            "ledd_dopamine_agonist": led["ledd_dopamine_agonist"],
            "ledd_other": led["ledd_other"],
            "ledd_on_levodopa": led["ledd_on_levodopa"],
            "ledd_on_agonist": led["ledd_on_agonist"],
            "hours_since_last_dose": h_since,
            "assistive_device_yn": coerce_yn(r.get("Assistive Device used during testing?")),
            "pt_ot_status_yn": coerce_yn(r.get("PT/OT status")),
            "race_white": race_white,
            "days_since_part3": coerce_int_or_nan(r.get("Days since Part III Clinical Evaluation")),
            "part1_sum": part1_sum,
            "part1_cognitive": coerce_part1(r.get("MDSUPDRS_1-1")),
            "part1_hallucinations": coerce_part1(r.get("MDSUPDRS_1-2")),
            "part1_sleep": coerce_part1(r.get("MDSUPDRS_1-7")),
            "part1_daytime_sleepiness": coerce_part1(r.get("MDSUPDRS_1-8")),
        }
        rows.append(out_row)

        # Validation print for first 5 subjects: show parsed drug tuples (no PII strings).
        if n_printed < n_validation_print:
            print(f"=== {sid} ===")
            for c in contribs:
                print(
                    f"  drug={c.drug:<30s} dose_mg={c.dose_mg:7.2f} "
                    f"freq/day={c.freq_per_day:5.2f} daily_dose_mg={c.daily_dose_mg:8.2f} "
                    f"factor={c.factor:6.3f} LED={c.led_mg:8.2f}"
                )
            print(
                f"  -> ledd_levodopa={led['ledd_levodopa']:.1f}  "
                f"agonist={led['ledd_dopamine_agonist']:.1f}  "
                f"other={led['ledd_other']:.1f}  total={led['ledd_total']:.1f}"
            )
            print(f"  hours_since_last_dose={h_since:.2f}, part1_sum={part1_sum}")
            n_printed += 1

    out_df = pd.DataFrame(rows).sort_values("sid").reset_index(drop=True)

    # --- V2 cohort cross-check ---
    n_v2_match = -1
    v2_only_missing: list[str] = []
    if args.verify_against_v2 and Path(args.verify_against_v2).exists():
        v2 = pd.read_csv(args.verify_against_v2, low_memory=False, usecols=["sid"])
        v2_pd = sorted(v2.loc[v2["sid"].astype(str).str.match(r"^(NLS|WPD)"), "sid"].astype(str).tolist())
        cache_sids = set(out_df["sid"].astype(str))
        n_v2_match = sum(1 for s in v2_pd if s in cache_sids)
        v2_only_missing = [s for s in v2_pd if s not in cache_sids]
        print()
        print(f"V2 cohort cross-check: {n_v2_match}/{len(v2_pd)} V2-PD SIDs found in cache.")
        if v2_only_missing:
            print(f"  V2-PD subjects missing from clinical CSV: {v2_only_missing}")
        not_in_v2 = sorted(cache_sids - set(v2_pd))
        if not_in_v2:
            print(f"  Cache subjects NOT in V2 cohort (will not be used by T3 pipeline): {not_in_v2}")

    # --- Write output ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output_path, index=False)
    print()
    print(f"Wrote {len(out_df)} rows × {len(out_df.columns)} cols → {output_path}")

    # --- Coverage summary ---
    n_total = len(out_df)
    ledd_nonzero = int((out_df["ledd_total"] > 0).sum())
    part1_cov = int(out_df["part1_sum"].notna().sum())
    h_cov = int(out_df["hours_since_last_dose"].notna().sum())
    print()
    print("=== Coverage summary ===")
    print(f"  N subjects            : {n_total}")
    print(f"  ledd_total > 0        : {ledd_nonzero}/{n_total}")
    print(f"     min/median/mean/max: "
          f"{out_df['ledd_total'].min():.1f} / "
          f"{out_df['ledd_total'].median():.1f} / "
          f"{out_df['ledd_total'].mean():.1f} / "
          f"{out_df['ledd_total'].max():.1f}")
    print(f"  part1_sum non-null    : {part1_cov}/{n_total}")
    print(f"  hours_since_dose non-null : {h_cov}/{n_total}")
    print(f"  V2 cohort SIDs matched: {n_v2_match}/98")
    print()
    print("=== Output head ===")
    print(out_df.head(10).to_string(index=False))
    print()
    print("=== Output describe ===")
    print(out_df.describe(include="all").to_string())

    if all_unrecognized:
        print()
        print(f"=== Unrecognized lines ({len(all_unrecognized)} total; first 30) ===")
        for sid, ln in all_unrecognized[:30]:
            print(f"  [{sid}] {ln}")

    # --- Manifest ---
    script_path = Path(__file__).resolve()
    manifest = {
        "script": script_path.name,
        "script_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
        "git_sha": _git_sha(),
        "command": " ".join(sys.argv),
        "created_at_utc": datetime.utcnow().isoformat() + "Z",
        "data_sha256": _sha256(output_path),
        "labels_used": False,
        "fold_scope": "none",
        "cohort_statistics_used": False,
        "normalization_scope": "none",
        "leakage_status": "clean_by_construction",
        "leakage_rationale": (
            "All extracted features are intake patient-state (medication regimen, "
            "time-since-dose, demographics, non-motor MDS-UPDRS Part 1, treatment "
            "history) recorded BEFORE the gait IMU session. No use of MDS-UPDRS "
            "Part 3, updrs3, hy, or obs_subscore. Tomlinson-2010 LEDD conversion is "
            "a published, publicly-known table."
        ),
        "tomlinson2010_factors": LEDD_FACTORS,
        "n_subjects_total": int(n_total),
        "n_subjects_v2_match": int(n_v2_match),
        "ledd_coverage": int(ledd_nonzero),
        "part1_coverage": int(part1_cov),
        "hours_since_last_dose_coverage": int(h_cov),
        "n_unrecognized_lines": len(all_unrecognized),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    print()
    print(f"Wrote manifest → {manifest_path}")


if __name__ == "__main__":
    main()
