"""Generate the corrected protocol-audited manuscript as paper3.html."""
from __future__ import annotations

from pathlib import Path

from paper2_renderer import PaperBuilder
from paper3_data import (
    AFFILIATIONS,
    AUTHORS,
    CODE_AVAILABILITY,
    CORRESPONDENCE,
    REFERENCES,
    TITLE,
    load_paper3_data,
)


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "paper3.html"


def build_paper() -> str:
    data = load_paper3_data(ROOT)
    summary = data.summary
    builder = PaperBuilder(ROOT, TITLE)

    builder.add_title_block(TITLE, AUTHORS, AFFILIATIONS, CORRESPONDENCE)
    builder.add_abstract(
        [
            (
                "<strong>Background:</strong> The original WearGait-PD manuscript captured a "
                "promising engineered-feature signal, but several headline claims were stronger "
                "than the saved artifacts and evaluation protocol justified."
            ),
            (
                "<strong>Objective:</strong> To produce a corrected manuscript that preserves "
                "only internally verified results, documents code-level fixes to the affected "
                "runners, and separates artifact-backed evidence from claims that still require "
                "raw-data reruns."
            ),
            (
                "<strong>Methods:</strong> We audited the saved JSON artifacts, recomputed MAE "
                "and correlation from stored per-subject predictions, patched the runners that "
                "caused the main protocol issues, and rebuilt the manuscript from a structured "
                "data layer rather than a monolithic HTML string."
            ),
            (
                f"<strong>Results:</strong> On the new 36-subject outer test split, the pre-specified "
                f"deployable stack ({summary.primary_name}) achieves MAE = {summary.stack_mae:.2f}, "
                f"r = {summary.stack_r:.3f}; the clean LightGBM baseline reaches MAE = "
                f"{summary.baseline_mae:.2f}, r = {summary.baseline_r:.3f}; and the H&amp;Y ceiling "
                f"reaches MAE = {summary.ceiling_mae:.2f}, r = {summary.ceiling_r:.3f}. The corrected "
                f"sensor ablation now shows wrists-only at MAE = {summary.wrists_mae:.2f} and no-lower-back "
                f"at MAE = {summary.no_lower_back_mae:.2f}. The axial composite result "
                f"(MAE = {summary.axial_mae:.2f}, r = {summary.axial_r:.3f}) remains supported. Several "
                "longer-running side analyses are still kept conservative until their reruns finish."
            ),
            (
                "<strong>Conclusions:</strong> The engineered-feature booster family remains the right "
                "research direction, but the clean rerun shows that the old headline was materially optimistic. "
                "The remaining path forward is disciplined model selection inside development data, subset-faithful "
                "ablations, protocol-matched comparisons, and targeted work on the severe-score tail."
            ),
        ],
        "Parkinson's disease, MDS-UPDRS-III, IMU, gait analysis, evaluation protocol, stacking ensemble, artifact audit",
    )

    builder.add_toc(
        [
            ("sec1", "1. Why Paper3"),
            ("sec2", "2. Verified Results"),
            ("sec3", "3. Fixes Applied"),
            ("sec4", "4. Claims Withdrawn Pending Rerun"),
            ("sec5", "5. Aggressive Next Steps"),
            ("sec6", "6. Conclusion"),
            ("refs", "References"),
        ]
    )

    builder.section("1. Why Paper3", "sec1")
    builder.paragraph(
        "This manuscript is a correction layer, not a cosmetic refresh. The prior paper mixed "
        "historical results, exploratory held-out sweeps, and partially validated downstream "
        "analyses in ways that made the headline narrative more confident than the repository "
        "state warranted."
    )
    builder.paragraph(
        "Paper3 therefore adopts a stricter rule: if a number cannot be recomputed from the saved "
        "predictions, or if the underlying analysis is known to be protocol-mismatched, it does not "
        "get promoted as a supported finding. The manuscript itself is generated locally from rerun "
        "artifacts; the raw-data reruns were executed on the attached GPU host."
    )
    dist_ref = builder.add_figure(
        "fig10_updrs_dist.png",
        "Saved development and held-out test score distributions for the 142/36 subject split used throughout the historical experiments.",
    )
    pipeline_ref = builder.add_figure(
        "fig5_pipeline.png",
        "Feature-engineering and stacking workflow retained as the central modeling direction in the repository.",
    )
    builder.paragraph(
        f"{dist_ref.label} and {pipeline_ref.label} are still useful context: the cohort and the "
        "engineered-feature stack remain the right objects of study. What changes in Paper3 is the "
        "interpretation discipline around those artifacts."
    )
    builder.add_table(
        "Provenance and audit status for the current workspace.",
        ["Audit item", "Status", "Interpretation"],
        data.provenance_rows,
    )

    builder.section("2. Verified Results", "sec2")
    builder.paragraph(
        "Tabled below are the results that remain defensible in the current workspace because the "
        "stored predictions reproduce the reported metrics exactly or to within rounding tolerance."
    )
    builder.add_table(
        "Artifact-backed results retained in Paper3.",
        ["Result", "MAE", "r", "Verification basis", "Interpretation"],
        data.verified_rows,
        row_classes=data.verified_row_classes,
    )
    stack_ref = builder.add_figure(
        "fig8_scatter.png",
        "Predicted versus actual UPDRS-III for the best saved deployable stack. The figure is retained as an internally verified exploratory result rather than a pristine final benchmark.",
    )
    ceil_ref = builder.add_figure(
        "fig8b_scatter_ceiling.png",
        "Predicted versus actual UPDRS-III for the H&Y-augmented ceiling stack on the same saved test subjects.",
    )
    ba_ref = builder.add_figure(
        "fig9_residuals.png",
        "Residual view for the saved deployable stack. This plot remains useful diagnostically even though the model-selection protocol must be framed as exploratory.",
    )
    builder.paragraph(
        f"{stack_ref.label}, {ceil_ref.label}, and {ba_ref.label} remain informative because they are "
        "tied to saved per-subject predictions that paper3 re-verifies directly. The crucial difference "
        "from the earlier manuscript is that these plots now come from a fresh outer split evaluated with "
        "a pre-specified primary architecture."
    )
    if summary.wrists_mae is not None and summary.full_sensor_mae is not None:
        builder.paragraph(
            f"The clean sensor rerun materially changes the deployment narrative. On this split, "
            f"`all_13` reaches MAE = {summary.full_sensor_mae:.2f}, while `wrists_2` reaches "
            f"{summary.wrists_mae:.2f} and `no_LowerBack` reaches {summary.no_lower_back_mae:.2f}. "
            "That result is now methodologically cleaner than the legacy version because the reduced-sensor "
            "configs no longer inherit privileged distilled walkway proxies by default."
        )

    builder.section("3. Fixes Applied", "sec3")
    builder.paragraph(
        "The repository now contains code-level remediations for each material caveat identified in the audit. "
        "Some fixes are already reflected in the new clean reruns; others remain in place as safeguards for future experiments."
    )
    builder.add_table(
        "Code and protocol fixes applied for Paper3.",
        ["Issue", "Status", "What changed"],
        data.fix_rows,
    )
    builder.paragraph(
        f"{CODE_AVAILABILITY} In practical terms, the important architectural change is that the repository now "
        "has shared path and artifact helpers, a nested LOOCV runner, a sensor-ablation runner that no longer "
        "silently keeps privileged distilled features by default, and a stats script that evaluates the actual "
        "best saved stack rather than a surrogate baseline."
    )

    builder.section("4. Claims Withdrawn Pending Rerun", "sec4")
    builder.paragraph(
        "Paper3 is intentionally conservative about downstream claims that still lack a fresh corrected rerun. "
        "Those claims are not deleted from history, but they are explicitly demoted until the relevant repaired runner completes."
    )
    builder.add_table(
        "Claims removed or downgraded in Paper3 pending corrected reruns.",
        ["Claim", "Paper3 status", "Reason"],
        data.withdrawn_rows,
    )
    hist_ref = builder.add_figure(
        "fig1_ablation_progression.png",
        "Historical feature-family progression retained only as context. Paper3 does not treat it as a clean final-model selection record.",
    )
    builder.paragraph(
        f"{hist_ref.label} is still useful as a map of feature ideas, but not as proof that the held-out test set remained untouched during development. "
        "That distinction is the central manuscript correction."
    )

    builder.section("5. Aggressive Next Steps", "sec5")
    builder.paragraph(
        "The highest-return next step is no longer to prove the evaluation protocol can be trusted; that part is repaired. "
        "The next step is to keep the new split frozen and improve the strongest booster stack where the clean rerun now shows the error truly lives."
    )
    builder.ordered_list(data.roadmap_items)

    builder.section("6. Conclusion", "sec6")
    builder.paragraph(
        "The main scientific conclusion survives in a stricter form: engineered gait features plus booster models are still the best direction in this repository, "
        "but the clean rerun on a fresh outer split is substantially harder than the legacy headline suggested. That gap is now measured honestly."
    )
    builder.paragraph(
        "Paper3 replaces the old overclaim with a cleaner contract. The repository now contains corrected runners, a fresh outer split, and an auditable manuscript generator. "
        "What remains is the real research problem: better out-of-fold distillation, cleaner subset ablations, strict LOOCV where still needed, protocol-matched DL baselines, "
        "and targeted modeling of the severe-score tail."
    )

    builder.add_references(REFERENCES)
    return builder.render()


def main():
    OUT.write_text(build_paper())
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
