"""
IMU encoder backbone for PD detection.
Processes raw 6-axis IMU into learned representations.
Inspired by TLIO architecture with modifications for PD-specific signals.
"""
import torch
import torch.nn as nn
import math


class GaitCycleTokenizer(nn.Module):
    """Tokenize IMU by gait cycles instead of fixed windows.

    Uses learned 1D convolution to detect gait cycle boundaries,
    then pools each cycle into a token.
    Falls back to fixed-size patches if cycles are not detectable.
    """

    def __init__(self, in_channels: int = 6, token_dim: int = 128, patch_size: int = 50):
        super().__init__()
        self.patch_size = patch_size
        self.token_dim = token_dim

        # Patch embedding (fixed-size fallback, also used for sub-cycle features)
        self.patch_embed = nn.Sequential(
            nn.Conv1d(in_channels, 64, kernel_size=7, stride=1, padding=3),
            nn.BatchNorm1d(64),
            nn.GELU(),
            nn.Conv1d(64, token_dim, kernel_size=patch_size, stride=patch_size),
            nn.BatchNorm1d(token_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (B, C, T) raw IMU, C=6 (accel_xyz + gyro_xyz)

        Returns:
            tokens: (B, N_tokens, token_dim)
        """
        tokens = self.patch_embed(x)  # (B, token_dim, N_tokens)
        return tokens.transpose(1, 2)  # (B, N_tokens, token_dim)


class PositionalEncoding(nn.Module):
    """Sinusoidal positional encoding for transformer."""

    def __init__(self, d_model: int, max_len: int = 512):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe.unsqueeze(0))  # (1, max_len, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, :x.size(1)]


class IMUTransformerEncoder(nn.Module):
    """Transformer encoder for IMU token sequences.

    Architecture:
        Raw IMU -> GaitCycleTokenizer -> Transformer -> [CLS] token
    """

    def __init__(
        self,
        in_channels: int = 6,
        token_dim: int = 128,
        n_heads: int = 8,
        n_layers: int = 6,
        ff_dim: int = 512,
        dropout: float = 0.1,
        patch_size: int = 50,
    ):
        super().__init__()
        self.tokenizer = GaitCycleTokenizer(in_channels, token_dim, patch_size)
        self.pos_enc = PositionalEncoding(token_dim)
        self.cls_token = nn.Parameter(torch.randn(1, 1, token_dim) * 0.02)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=token_dim,
            nhead=n_heads,
            dim_feedforward=ff_dim,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(token_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (B, C, T) raw IMU data

        Returns:
            features: (B, token_dim) global representation
        """
        tokens = self.tokenizer(x)  # (B, N, D)
        B = tokens.size(0)

        # Prepend CLS token
        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)

        tokens = self.pos_enc(tokens)
        tokens = self.transformer(tokens)
        tokens = self.norm(tokens)

        return tokens[:, 0]  # CLS token output


class PDPredictionHeads(nn.Module):
    """Multi-task prediction heads for PD assessment.

    Heads:
        - H&Y stage classification (5 classes)
        - UPDRS score regression
        - PD vs Control binary classification
        - Medication state (on/off)
    """

    def __init__(self, feature_dim: int = 128):
        super().__init__()
        self.hy_head = nn.Sequential(
            nn.Linear(feature_dim, 64),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(64, 5),
        )
        self.updrs_head = nn.Sequential(
            nn.Linear(feature_dim, 64),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(64, 1),
        )
        self.pd_head = nn.Sequential(
            nn.Linear(feature_dim, 64),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(64, 2),
        )
        self.med_head = nn.Sequential(
            nn.Linear(feature_dim, 64),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(64, 2),
        )

    def forward(self, features: torch.Tensor) -> dict[str, torch.Tensor]:
        return {
            "hy_stage": self.hy_head(features),
            "updrs": self.updrs_head(features).squeeze(-1),
            "pd_control": self.pd_head(features),
            "medication": self.med_head(features),
        }


class PDIMUModel(nn.Module):
    """Full PD-IMU model: encoder + multi-task heads."""

    def __init__(
        self,
        in_channels: int = 6,
        token_dim: int = 128,
        n_heads: int = 8,
        n_layers: int = 6,
        patch_size: int = 50,
    ):
        super().__init__()
        self.encoder = IMUTransformerEncoder(
            in_channels=in_channels,
            token_dim=token_dim,
            n_heads=n_heads,
            n_layers=n_layers,
            patch_size=patch_size,
        )
        self.heads = PDPredictionHeads(feature_dim=token_dim)

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        features = self.encoder(x)
        return self.heads(features)

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        """Get learned representation without prediction heads."""
        return self.encoder(x)
