# Neurologist Review: Ordinal Ranking for Wearable PD Motor Assessment

As a neurologist, I have reviewed the manuscript focusing on the clinical utility and methodological transparency of the proposed IMU-based MDS-UPDRS III assessment. Overall, this is a highly pragmatic and methodologically rigorous paper that correctly identifies the "observability ceiling" as a clinical modality constraint rather than a purely mathematical one.

### 1. Clinical Actionability of the Observable Subscore
The shift in focus from the total UPDRS-III score to a "directly observable" subscore (items 3.9–3.14) is the most clinically astute decision in the paper. As neurologists, we know that axial motor symptoms (gait, freezing, postural stability) are primary drivers of falls, morbidity, and loss of independence. Predicting unobservable signs (e.g., rigidity, which requires passive manipulation, or facial expression) from gait IMUs is inherently flawed. Achieving an MAE of <1 point on this 24-point axial subscore is exceptional. This subscore provides a highly actionable metric for titrating dopaminergic therapies or adjusting DBS settings specifically targeting axial dysfunction.

### 2. Sensor Reduction Deployment Guidance
The sensor reduction analysis bridges the gap between research environments and real-world clinical deployment. A 13-sensor setup is entirely impractical for routine monitoring. The finding that a 5-sensor minimal set is non-inferior across targets, and that a single lower-back sensor can effectively capture the observable subscore (CCC = 0.867), is transformative. This provides a clear, evidence-based roadmap for continuous, passive, single-sensor monitoring, which maximizes patient compliance while preserving diagnostic fidelity.

### 3. Clinical Significance of the Calibration Fix
The identification and correction of "prediction compression" via temperature scaling (improving the calibration slope to 0.967) is critically important. A model that compresses predictions toward the mean is clinically dangerous: it would under-triage severe, advanced patients (delaying escalation of therapy) and over-score mild patients (risking over-medication). By stretching the predictions to reflect the true clinical spectrum, the temperature scaling fix ensures the tool is reliable for differentiating edge-case patients across all disease stages. 

### 4. Honesty in Limitations
The authors are exceptionally transparent about the study's limitations. Acknowledging the lack of free-living data and uncontrolled medication states highlights a clear understanding of the clinical realities of PD (where motor fluctuations between ON/OFF states are paramount). Furthermore, calling out the confounding presence of DBS patients (24% of the cohort) and the lack of an established MCID for the novel subscore shows scientific integrity. 

### 5. Recommended Specific Improvements
To further strengthen the clinical impact of the paper, I recommend the following three improvements:
1. **Medication State Analysis:** Since medication state was uncontrolled, please analyze whether time-since-last-medication-dose (if available) correlates with prediction errors. If unavailable, explicitly recommend a controlled ON/OFF study design in the future directions to validate the model's ability to track motor fluctuations.
2. **DBS vs. Non-DBS Residual Check:** Although the DBS subgroup is small (N=23), DBS drastically alters gait kinematics. Provide a brief supplementary scatter plot or residual analysis comparing the error distributions of DBS vs. non-DBS patients to ensure the model isn't systematically failing on DBS-induced motor phenotypes.
3. **Clinical Anchoring for Subscore MCID:** While a formal MCID for the 24-point subscore does not yet exist, you could provide a clinical proxy. For example, map the subscore distributions against the established Hoehn & Yahr (H&Y) stages of your cohort to give clinicians a heuristic for what a 1-point or 2-point change means in terms of broad disease progression.
