"""
Self-supervised pretraining for IMU encoder.

Two strategies:
1. Masked IMU Modeling (MIM) - MAE-style, predict masked patches
2. Contrastive Learning - gait cycle positive pairs

Pretrain on large unlabeled datasets (mPower, PADS walking segments)
then fine-tune on labeled clinical data.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
import math
import random


class MaskedIMUModeling(nn.Module):
    """MAE-style pretraining for IMU data.

    Randomly masks patches of IMU tokens and trains the encoder
    to reconstruct the masked patches.
    """

    def __init__(
        self,
        in_channels: int = 6,
        token_dim: int = 128,
        n_heads: int = 8,
        n_layers: int = 6,
        patch_size: int = 50,
        mask_ratio: float = 0.75,
        decoder_dim: int = 64,
        decoder_layers: int = 2,
    ):
        super().__init__()
        self.mask_ratio = mask_ratio
        self.patch_size = patch_size
        self.in_channels = in_channels
        self.token_dim = token_dim

        # Encoder (same as IMUTransformerEncoder but without CLS)
        self.patch_embed = nn.Sequential(
            nn.Conv1d(in_channels, 64, kernel_size=7, stride=1, padding=3),
            nn.BatchNorm1d(64),
            nn.GELU(),
            nn.Conv1d(64, token_dim, kernel_size=patch_size, stride=patch_size),
            nn.BatchNorm1d(token_dim),
        )

        self.pos_enc = nn.Parameter(torch.randn(1, 512, token_dim) * 0.02)
        self.mask_token = nn.Parameter(torch.randn(1, 1, decoder_dim) * 0.02)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=token_dim,
            nhead=n_heads,
            dim_feedforward=token_dim * 4,
            dropout=0.1,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.encoder_norm = nn.LayerNorm(token_dim)

        # Lightweight decoder
        decoder_layer = nn.TransformerEncoderLayer(
            d_model=decoder_dim,
            nhead=4,
            dim_feedforward=decoder_dim * 4,
            dropout=0.1,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.decoder_embed = nn.Linear(token_dim, decoder_dim)
        self.decoder = nn.TransformerEncoder(decoder_layer, num_layers=decoder_layers)
        self.decoder_norm = nn.LayerNorm(decoder_dim)
        self.decoder_pred = nn.Linear(decoder_dim, patch_size * in_channels)

    def _random_masking(
        self, tokens: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Random masking of tokens.

        Args:
            tokens: (B, N, D)

        Returns:
            visible_tokens: (B, N_vis, D)
            mask: (B, N) binary mask (1 = masked)
            ids_restore: (B, N) indices to restore original order
        """
        B, N, D = tokens.shape
        n_mask = int(N * self.mask_ratio)
        n_vis = N - n_mask

        # Random permutation per sample
        noise = torch.rand(B, N, device=tokens.device)
        ids_shuffle = torch.argsort(noise, dim=1)
        ids_restore = torch.argsort(ids_shuffle, dim=1)

        # Keep visible tokens
        ids_keep = ids_shuffle[:, :n_vis]
        visible_tokens = torch.gather(
            tokens, 1, ids_keep.unsqueeze(-1).expand(-1, -1, D)
        )

        # Create mask
        mask = torch.ones(B, N, device=tokens.device)
        mask[:, :n_vis] = 0
        mask = torch.gather(mask, 1, ids_restore)

        return visible_tokens, mask, ids_restore

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            x: (B, C, T) raw IMU data

        Returns:
            loss: reconstruction loss (MSE on masked patches)
            mask: (B, N) which patches were masked
        """
        # Patchify
        tokens = self.patch_embed(x).transpose(1, 2)  # (B, N, D)
        B, N, D = tokens.shape

        # Add positional encoding
        tokens = tokens + self.pos_enc[:, :N]

        # Store original tokens for reconstruction target
        # Target is the raw patch (before embedding)
        # Reshape x into patches: (B, N, patch_size * C)
        x_patches = x.unfold(2, self.patch_size, self.patch_size)  # (B, C, N, patch_size)
        x_patches = x_patches.permute(0, 2, 1, 3).reshape(B, N, -1)  # (B, N, C*patch_size)

        # Mask
        visible, mask, ids_restore = self._random_masking(tokens)

        # Encode visible tokens only (efficient)
        visible = self.encoder(visible)
        visible = self.encoder_norm(visible)

        # Decode: add mask tokens back
        visible_dec = self.decoder_embed(visible)
        n_vis = visible_dec.size(1)

        mask_tokens = self.mask_token.expand(B, N - n_vis, -1)
        decoder_dim = visible_dec.size(-1)

        # Unshuffle: put visible and mask tokens back in original order
        full_tokens = torch.cat([visible_dec, mask_tokens], dim=1)
        full_tokens = torch.gather(
            full_tokens, 1,
            ids_restore.unsqueeze(-1).expand(-1, -1, decoder_dim),
        )

        # Decode
        decoded = self.decoder(full_tokens)
        decoded = self.decoder_norm(decoded)
        pred = self.decoder_pred(decoded)  # (B, N, patch_size * C)

        # Loss on masked patches only
        loss = (pred - x_patches) ** 2
        loss = loss.mean(dim=-1)  # (B, N) per-patch MSE
        loss = (loss * mask).sum() / mask.sum()

        return loss, mask


class ContrastiveIMU(nn.Module):
    """Contrastive learning for IMU using gait cycle augmentations.

    Positive pairs: different gait cycles from the same walking bout
    Negative pairs: gait cycles from different subjects

    Uses InfoNCE loss (SimCLR-style).
    """

    def __init__(
        self,
        in_channels: int = 6,
        token_dim: int = 128,
        n_heads: int = 8,
        n_layers: int = 6,
        patch_size: int = 50,
        proj_dim: int = 64,
        temperature: float = 0.1,
    ):
        super().__init__()
        self.temperature = temperature

        # Shared encoder
        self.patch_embed = nn.Sequential(
            nn.Conv1d(in_channels, 64, kernel_size=7, stride=1, padding=3),
            nn.BatchNorm1d(64),
            nn.GELU(),
            nn.Conv1d(64, token_dim, kernel_size=patch_size, stride=patch_size),
            nn.BatchNorm1d(token_dim),
        )

        self.cls_token = nn.Parameter(torch.randn(1, 1, token_dim) * 0.02)
        self.pos_enc = nn.Parameter(torch.randn(1, 512, token_dim) * 0.02)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=token_dim,
            nhead=n_heads,
            dim_feedforward=token_dim * 4,
            dropout=0.1,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(token_dim)

        # Projection head
        self.projector = nn.Sequential(
            nn.Linear(token_dim, token_dim),
            nn.GELU(),
            nn.Linear(token_dim, proj_dim),
        )

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        """Encode IMU to normalized projection."""
        tokens = self.patch_embed(x).transpose(1, 2)
        B, N, D = tokens.shape

        cls = self.cls_token.expand(B, -1, -1)
        tokens = torch.cat([cls, tokens], dim=1)
        tokens = tokens + self.pos_enc[:, :N + 1]

        tokens = self.encoder(tokens)
        tokens = self.norm(tokens)

        features = tokens[:, 0]  # CLS
        proj = self.projector(features)
        return F.normalize(proj, dim=-1)

    def forward(
        self, x1: torch.Tensor, x2: torch.Tensor
    ) -> torch.Tensor:
        """
        Args:
            x1, x2: (B, C, T) two augmented views of the same IMU segment

        Returns:
            InfoNCE loss
        """
        z1 = self.encode(x1)  # (B, proj_dim)
        z2 = self.encode(x2)  # (B, proj_dim)

        B = z1.size(0)

        # Similarity matrix
        z = torch.cat([z1, z2], dim=0)  # (2B, proj_dim)
        sim = torch.mm(z, z.t()) / self.temperature  # (2B, 2B)

        # Mask self-similarity
        mask = torch.eye(2 * B, device=sim.device).bool()
        sim.masked_fill_(mask, -1e9)

        # Positive pairs: (i, i+B) and (i+B, i)
        labels = torch.cat([
            torch.arange(B, 2 * B, device=sim.device),
            torch.arange(0, B, device=sim.device),
        ])

        loss = F.cross_entropy(sim, labels)
        return loss


def imu_augment(x: torch.Tensor) -> torch.Tensor:
    """Apply random augmentations to IMU data for contrastive learning.

    Augmentations (applied randomly):
    - Time warping (speed perturbation)
    - Additive Gaussian noise
    - Channel dropout
    - Random rotation (simulates sensor re-orientation)
    - Magnitude scaling

    Args:
        x: (B, C, T) IMU data

    Returns:
        Augmented x (same shape)
    """
    B, C, T = x.shape
    augmented = x.clone()

    # Additive noise (always apply, small)
    noise = torch.randn_like(augmented) * 0.05
    augmented = augmented + noise

    # Magnitude scaling (per-sample random scale 0.8-1.2)
    if random.random() > 0.5:
        scale = 0.8 + 0.4 * torch.rand(B, 1, 1, device=x.device)
        augmented = augmented * scale

    # Channel dropout (zero out one axis with p=0.3)
    if random.random() > 0.7:
        channel = random.randint(0, C - 1)
        augmented[:, channel, :] = 0.0

    # Time shift (circular shift by random amount)
    if random.random() > 0.5:
        shift = random.randint(-T // 10, T // 10)
        augmented = torch.roll(augmented, shifts=shift, dims=2)

    return augmented
