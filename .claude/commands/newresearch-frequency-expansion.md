---
description: Extract advanced frequency-domain features (wavelets, spectral entropy, dominant frequencies, cross-frequency coupling) beyond basic FFT.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
argument-hint: [method]
---

# Advanced Frequency Domain Features

## Research Question
Can wavelet-based, spectral complexity, and cross-frequency features capture PD gait signatures that time-domain statistics and basic FFT miss?

## Arguments
$ARGUMENTS — one of: "wavelet", "spectral", "coupling", "all" (default: "all")

## Hypothesis
Current spectral features are basic (dominant frequency, spectral energy in bands). Advanced frequency analysis can capture:

1. **Wavelet decomposition**: time-frequency patterns — HOW gait frequency changes within a trial (freezing episodes = sudden frequency shift)
2. **Spectral entropy/flatness**: complexity of the frequency spectrum — PD gait has more concentrated spectral energy (less complex)
3. **Cross-frequency coupling**: phase-amplitude coupling between limb segments — disrupted in PD (arm-leg coordination)
4. **Harmonic structure**: ratio of stride frequency harmonics — PD has altered harmonic ratios (less smooth gait)

Expected: +0.1-0.4 MAE (complementary to time-domain features)

## Literature Support
- Pham 2018: Wavelet-based features outperform time-domain for PD gait classification
- Alam 2017: Spectral entropy of gait accelerometry distinguishes PD severity
- Plotnik 2007: Phase coordination index (arm-leg coupling) correlates with falls risk in PD
- Gait harmonic ratio (Menz 2003): smoothness measure, sensitive to PD

## Instructions

Write and deploy `run_freq_expansion.py` via `./gpu.sh`.

### 1. Wavelet Decomposition Features

```python
import pywt

def wavelet_features(signal, fs=100, wavelet='db4', max_level=5):
    """Extract multi-resolution wavelet features."""
    coeffs = pywt.wavedec(signal, wavelet, level=max_level)
    features = {}

    # Frequency bands (at 100Hz, level decomposition):
    # Level 1: 25-50 Hz (noise, impact spikes)
    # Level 2: 12.5-25 Hz (fast oscillations)
    # Level 3: 6.25-12.5 Hz (gait harmonics)
    # Level 4: 3.125-6.25 Hz (stride frequency + harmonics)
    # Level 5: 1.5625-3.125 Hz (fundamental stride frequency)
    # Approx:  0-1.5625 Hz (postural sway, drift)

    for i, c in enumerate(coeffs):
        band = f"level_{i}" if i > 0 else "approx"
        features[f"{band}_energy"] = np.sum(c**2)
        features[f"{band}_entropy"] = -np.sum(c**2 * np.log(c**2 + 1e-10))
        features[f"{band}_mean_abs"] = np.mean(np.abs(c))
        features[f"{band}_std"] = np.std(c)
        features[f"{band}_max"] = np.max(np.abs(c))

    # Energy ratios between bands
    total_energy = sum(np.sum(c**2) for c in coeffs)
    for i, c in enumerate(coeffs):
        features[f"level_{i}_energy_ratio"] = np.sum(c**2) / (total_energy + 1e-10)

    return features
```

### 2. Spectral Complexity Features

```python
from scipy.signal import welch

def spectral_complexity(signal, fs=100):
    freqs, psd = welch(signal, fs=fs, nperseg=256)
    features = {}

    # Spectral entropy (flatness of spectrum)
    psd_norm = psd / (np.sum(psd) + 1e-10)
    features["spectral_entropy"] = -np.sum(psd_norm * np.log(psd_norm + 1e-10))

    # Spectral flatness (geometric/arithmetic mean of PSD)
    features["spectral_flatness"] = gmean(psd + 1e-10) / (np.mean(psd) + 1e-10)

    # Spectral centroid (center of mass of spectrum)
    features["spectral_centroid"] = np.sum(freqs * psd) / (np.sum(psd) + 1e-10)

    # Spectral bandwidth
    features["spectral_bandwidth"] = np.sqrt(
        np.sum((freqs - features["spectral_centroid"])**2 * psd) / (np.sum(psd) + 1e-10)
    )

    # Spectral edge (95% energy below this frequency)
    cumsum = np.cumsum(psd) / np.sum(psd)
    features["spectral_edge_95"] = freqs[np.searchsorted(cumsum, 0.95)]

    # Harmonic ratio (even/odd harmonics — gait smoothness)
    stride_freq_range = (0.5, 3.0)  # Hz
    stride_idx = (freqs >= stride_freq_range[0]) & (freqs <= stride_freq_range[1])
    if np.any(stride_idx):
        fund_freq = freqs[stride_idx][np.argmax(psd[stride_idx])]
        harmonics_even = sum(psd[np.abs(freqs - k*fund_freq) < 0.1] for k in [2, 4, 6])
        harmonics_odd = sum(psd[np.abs(freqs - k*fund_freq) < 0.1] for k in [1, 3, 5])
        features["harmonic_ratio"] = harmonics_even / (harmonics_odd + 1e-10)

    return features
```

### 3. Cross-Frequency / Cross-Sensor Coupling

```python
def phase_coordination(signal_A, signal_B, fs=100):
    """Phase coordination index between two limb segments."""
    from scipy.signal import hilbert

    # Bandpass to stride frequency (0.5-3 Hz)
    analytic_A = hilbert(bandpass(signal_A, 0.5, 3.0, fs))
    analytic_B = hilbert(bandpass(signal_B, 0.5, 3.0, fs))

    phase_A = np.angle(analytic_A)
    phase_B = np.angle(analytic_B)

    # Phase coordination index (Plotnik 2007)
    phase_diff = phase_A - phase_B
    mean_phase_diff = np.mean(np.exp(1j * phase_diff))
    PCI = np.abs(mean_phase_diff)  # 1 = perfect sync, 0 = no sync

    return {
        "phase_coherence": PCI,
        "mean_phase_diff": np.angle(mean_phase_diff),
        "phase_diff_std": np.std(np.mod(phase_diff, 2*np.pi)),
    }

# Apply to bilateral pairs AND arm-leg pairs:
COUPLING_PAIRS = [
    ("R_LatShank_Gyr_Y", "L_LatShank_Gyr_Y"),   # Bilateral leg coordination
    ("R_Wrist_Gyr_Y", "R_LatShank_Gyr_Y"),       # Arm-leg ipsilateral
    ("R_Wrist_Gyr_Y", "L_LatShank_Gyr_Y"),       # Arm-leg contralateral
    ("LowerBack_Acc_Z", "R_DorsalFoot_Acc_Z"),    # Trunk-foot vertical
]
```

### 4. Experiment Design

| Config | Features | Expected MAE |
|--------|----------|-------------|
| A | Baseline 150 | 7.97 |
| B | Baseline + wavelet energy/entropy | 7.6-7.9 |
| C | Baseline + spectral complexity | 7.7-8.0 |
| D | Baseline + cross-frequency coupling | 7.7-8.0 |
| E | Baseline + harmonic ratio | 7.7-8.0 |
| F | Baseline + all frequency features | 7.4-7.8 |

### Critical Rules
- Wavelet choice matters: db4 is standard for gait, but test db6 and sym5 too
- Welch PSD: use nperseg=256 (2.56s at 100Hz) — enough for stride frequency resolution
- Bandpass filter before coupling analysis (remove DC and high-frequency noise)
- Harmonic ratio requires accurate stride frequency detection — validate first
- Cross-sensor coupling features must match left-right or arm-leg anatomically
- Feature selection re-run on expanded set
- 3 seeds per config
