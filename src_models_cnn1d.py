"""
1D CNN baseline for PD classification from raw IMU.
Simple but effective architecture for comparison against Neural EKF.
"""
import torch
import torch.nn as nn


class ResBlock1D(nn.Module):
    """Residual block for 1D convolution."""

    def __init__(self, channels: int, kernel_size: int = 7):
        super().__init__()
        padding = kernel_size // 2
        self.block = nn.Sequential(
            nn.Conv1d(channels, channels, kernel_size, padding=padding),
            nn.BatchNorm1d(channels),
            nn.GELU(),
            nn.Conv1d(channels, channels, kernel_size, padding=padding),
            nn.BatchNorm1d(channels),
        )
        self.act = nn.GELU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.act(x + self.block(x))


class CNN1DBaseline(nn.Module):
    """1D-CNN for IMU classification.

    Architecture:
        Conv1D stem -> 4 ResBlocks -> Global Avg Pool -> FC heads

    Input: (B, 6, T) raw 6-axis IMU at 100Hz
    """

    def __init__(
        self,
        in_channels: int = 6,
        base_channels: int = 64,
        n_blocks: int = 4,
        n_classes: int = 3,
        dropout: float = 0.3,
    ):
        super().__init__()

        # Stem
        self.stem = nn.Sequential(
            nn.Conv1d(in_channels, base_channels, kernel_size=15, stride=2, padding=7),
            nn.BatchNorm1d(base_channels),
            nn.GELU(),
        )

        # Residual blocks with progressive channel doubling
        blocks = []
        ch = base_channels
        for i in range(n_blocks):
            blocks.append(ResBlock1D(ch))
            if i < n_blocks - 1:
                next_ch = ch * 2
                blocks.append(nn.Conv1d(ch, next_ch, 3, stride=2, padding=1))
                blocks.append(nn.BatchNorm1d(next_ch))
                blocks.append(nn.GELU())
                ch = next_ch

        self.backbone = nn.Sequential(*blocks)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.feature_dim = ch

        # Classification head
        self.classifier = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(ch, ch // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(ch // 2, n_classes),
        )

        # UPDRS regression head
        self.regressor = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(ch, ch // 2),
            nn.GELU(),
            nn.Linear(ch // 2, 1),
        )

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        """Extract features without heads."""
        x = self.stem(x)
        x = self.backbone(x)
        x = self.pool(x).squeeze(-1)
        return x

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        features = self.encode(x)
        return {
            "classification": self.classifier(features),
            "updrs": self.regressor(features).squeeze(-1),
            "features": features,
        }


class InceptionBlock1D(nn.Module):
    """Inception-style multi-scale convolution block.

    Processes input with multiple kernel sizes in parallel,
    capturing patterns at different temporal scales.
    """

    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        branch_ch = out_channels // 4

        self.branch1 = nn.Sequential(
            nn.Conv1d(in_channels, branch_ch, 1),
            nn.BatchNorm1d(branch_ch),
            nn.GELU(),
        )
        self.branch3 = nn.Sequential(
            nn.Conv1d(in_channels, branch_ch, 3, padding=1),
            nn.BatchNorm1d(branch_ch),
            nn.GELU(),
        )
        self.branch5 = nn.Sequential(
            nn.Conv1d(in_channels, branch_ch, 5, padding=2),
            nn.BatchNorm1d(branch_ch),
            nn.GELU(),
        )
        self.branch_pool = nn.Sequential(
            nn.MaxPool1d(3, stride=1, padding=1),
            nn.Conv1d(in_channels, branch_ch, 1),
            nn.BatchNorm1d(branch_ch),
            nn.GELU(),
        )

        # Residual if dimensions match
        self.residual = (
            nn.Identity() if in_channels == out_channels
            else nn.Conv1d(in_channels, out_channels, 1)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        branches = torch.cat([
            self.branch1(x),
            self.branch3(x),
            self.branch5(x),
            self.branch_pool(x),
        ], dim=1)
        return branches + self.residual(x)


class InceptionTime1D(nn.Module):
    """InceptionTime baseline (Fawaz et al., 2020 adapted for IMU).

    Multi-scale temporal feature extraction shown effective
    for PD symptom classification from wrist accelerometer.
    """

    def __init__(
        self,
        in_channels: int = 6,
        base_channels: int = 64,
        n_inception_blocks: int = 3,
        n_classes: int = 3,
    ):
        super().__init__()

        blocks = [InceptionBlock1D(in_channels, base_channels)]
        for _ in range(n_inception_blocks - 1):
            blocks.append(InceptionBlock1D(base_channels, base_channels))

        self.backbone = nn.Sequential(*blocks)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.classifier = nn.Linear(base_channels, n_classes)

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        features = self.backbone(x)
        pooled = self.pool(features).squeeze(-1)
        return {
            "classification": self.classifier(pooled),
            "features": pooled,
        }
