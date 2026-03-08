"""
Training loops for PD-IMU models.
Supports pretraining (MIM/Contrastive) and fine-tuning (multi-task).
"""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset
from torch.utils.tensorboard import SummaryWriter
from pathlib import Path
import numpy as np
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TrainConfig:
    """Immutable training configuration."""
    # Data
    batch_size: int = 32
    num_workers: int = 4
    window_sec: float = 10.0
    fs: float = 100.0  # sampling frequency

    # Optimization
    lr: float = 1e-4
    weight_decay: float = 1e-4
    warmup_epochs: int = 5
    max_epochs: int = 100
    patience: int = 15

    # Model
    in_channels: int = 6
    token_dim: int = 128
    n_heads: int = 8
    n_layers: int = 6
    patch_size: int = 50

    # Logging
    log_dir: str = "runs"
    save_dir: str = "checkpoints"
    experiment_name: str = "pd_imu"


class IMUDataset(Dataset):
    """PyTorch dataset for windowed IMU segments."""

    def __init__(
        self,
        accel_windows: np.ndarray,   # (N, T, 3)
        gyro_windows: Optional[np.ndarray],  # (N, T, 3) or None
        labels: dict[str, np.ndarray],  # {task_name: (N,) array}
        augment: bool = False,
    ):
        self.n_samples = len(accel_windows)
        self.augment = augment

        # Combine accel + gyro into (N, C, T)
        if gyro_windows is not None:
            imu = np.concatenate([accel_windows, gyro_windows], axis=2)  # (N, T, 6)
        else:
            # Pad with zeros if no gyro
            imu = np.concatenate([
                accel_windows,
                np.zeros_like(accel_windows),
            ], axis=2)

        self.imu = torch.from_numpy(imu).float().permute(0, 2, 1)  # (N, C, T)
        self.labels = {k: torch.from_numpy(v) for k, v in labels.items()}

    def __len__(self) -> int:
        return self.n_samples

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        x = self.imu[idx]

        if self.augment:
            # Simple augmentation: additive noise
            x = x + torch.randn_like(x) * 0.02

        label_dict = {k: v[idx] for k, v in self.labels.items()}
        return x, label_dict


def get_cosine_schedule_with_warmup(
    optimizer: optim.Optimizer,
    warmup_epochs: int,
    max_epochs: int,
) -> optim.lr_scheduler.LambdaLR:
    """Cosine LR schedule with linear warmup."""

    def lr_lambda(epoch: int) -> float:
        if epoch < warmup_epochs:
            return epoch / max(1, warmup_epochs)
        progress = (epoch - warmup_epochs) / max(1, max_epochs - warmup_epochs)
        return 0.5 * (1.0 + np.cos(np.pi * progress))

    return optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)


def train_pretrain_mim(
    model: nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader,
    config: TrainConfig,
    device: torch.device,
) -> dict:
    """Pretrain with Masked IMU Modeling."""
    model = model.to(device)
    optimizer = optim.AdamW(
        model.parameters(),
        lr=config.lr,
        weight_decay=config.weight_decay,
    )
    scheduler = get_cosine_schedule_with_warmup(
        optimizer, config.warmup_epochs, config.max_epochs
    )

    log_path = Path(config.log_dir) / f"{config.experiment_name}_pretrain"
    writer = SummaryWriter(str(log_path))
    save_path = Path(config.save_dir)
    save_path.mkdir(parents=True, exist_ok=True)

    best_val_loss = float("inf")
    patience_counter = 0

    for epoch in range(config.max_epochs):
        model.train()
        train_losses = []

        for batch_idx, (x, _) in enumerate(train_loader):
            x = x.to(device)
            loss, mask = model(x)

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            train_losses.append(loss.item())

        scheduler.step()

        # Validation
        model.eval()
        val_losses = []
        with torch.no_grad():
            for x, _ in val_loader:
                x = x.to(device)
                loss, mask = model(x)
                val_losses.append(loss.item())

        train_loss = np.mean(train_losses)
        val_loss = np.mean(val_losses)

        writer.add_scalar("pretrain/train_loss", train_loss, epoch)
        writer.add_scalar("pretrain/val_loss", val_loss, epoch)
        writer.add_scalar("pretrain/lr", optimizer.param_groups[0]["lr"], epoch)

        print(
            f"Epoch {epoch+1}/{config.max_epochs} | "
            f"Train: {train_loss:.4f} | Val: {val_loss:.4f} | "
            f"LR: {optimizer.param_groups[0]['lr']:.6f}"
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            torch.save(
                model.state_dict(),
                save_path / f"{config.experiment_name}_pretrain_best.pt",
            )
        else:
            patience_counter += 1
            if patience_counter >= config.patience:
                print(f"Early stopping at epoch {epoch+1}")
                break

    writer.close()
    return {"best_val_loss": best_val_loss, "epochs_trained": epoch + 1}


def train_finetune(
    model: nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader,
    config: TrainConfig,
    device: torch.device,
    task_weights: Optional[dict[str, float]] = None,
) -> dict:
    """Fine-tune multi-task model on labeled data."""
    if task_weights is None:
        task_weights = {
            "pd_control": 1.0,
            "hy_stage": 1.0,
            "updrs": 1.0,
        }

    model = model.to(device)
    optimizer = optim.AdamW(
        model.parameters(),
        lr=config.lr * 0.1,  # lower LR for fine-tuning
        weight_decay=config.weight_decay,
    )
    scheduler = get_cosine_schedule_with_warmup(
        optimizer, config.warmup_epochs, config.max_epochs
    )

    ce_loss = nn.CrossEntropyLoss()
    mse_loss = nn.MSELoss()

    log_path = Path(config.log_dir) / f"{config.experiment_name}_finetune"
    writer = SummaryWriter(str(log_path))
    save_path = Path(config.save_dir)
    save_path.mkdir(parents=True, exist_ok=True)

    best_val_metric = float("inf")
    patience_counter = 0

    for epoch in range(config.max_epochs):
        model.train()
        epoch_losses = {k: [] for k in task_weights}

        for batch_idx, (x, labels) in enumerate(train_loader):
            x = x.to(device)
            preds = model(x)

            total_loss = torch.tensor(0.0, device=device)

            if "pd_control" in labels and "pd_control" in preds:
                y = labels["pd_control"].to(device).long()
                l = ce_loss(preds["pd_control"], y)
                total_loss = total_loss + task_weights["pd_control"] * l
                epoch_losses["pd_control"].append(l.item())

            if "hy_stage" in labels and "hy_stage" in preds:
                y = labels["hy_stage"].to(device).long()
                valid = y >= 0
                if valid.any():
                    l = ce_loss(preds["hy_stage"][valid], y[valid])
                    total_loss = total_loss + task_weights["hy_stage"] * l
                    epoch_losses["hy_stage"].append(l.item())

            if "updrs" in labels and "updrs" in preds:
                y = labels["updrs"].to(device).float()
                valid = y >= 0
                if valid.any():
                    l = mse_loss(preds["updrs"][valid], y[valid])
                    total_loss = total_loss + task_weights["updrs"] * l
                    epoch_losses["updrs"].append(l.item())

            optimizer.zero_grad()
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        scheduler.step()

        # Validation
        model.eval()
        val_losses = []
        val_preds_all = {k: [] for k in task_weights}
        val_labels_all = {k: [] for k in task_weights}

        with torch.no_grad():
            for x, labels in val_loader:
                x = x.to(device)
                preds = model(x)

                for k in task_weights:
                    if k in labels and k in preds:
                        val_preds_all[k].append(preds[k].cpu())
                        val_labels_all[k].append(labels[k])

        # Compute validation metrics
        val_metrics = {}
        for k in task_weights:
            if val_preds_all[k]:
                p = torch.cat(val_preds_all[k])
                y = torch.cat(val_labels_all[k])
                if k == "updrs":
                    val_metrics[f"val_{k}_mae"] = torch.abs(p - y).mean().item()
                else:
                    pred_cls = p.argmax(dim=-1)
                    val_metrics[f"val_{k}_acc"] = (pred_cls == y).float().mean().item()

        for k, v in val_metrics.items():
            writer.add_scalar(f"finetune/{k}", v, epoch)

        # Print epoch summary
        train_summary = " | ".join(
            f"{k}: {np.mean(v):.4f}" for k, v in epoch_losses.items() if v
        )
        val_summary = " | ".join(f"{k}: {v:.4f}" for k, v in val_metrics.items())
        print(f"Epoch {epoch+1} | Train: {train_summary} | Val: {val_summary}")

        # Early stopping on primary metric
        primary_metric = val_metrics.get("val_updrs_mae", val_metrics.get("val_pd_control_acc", 0))
        if isinstance(primary_metric, float) and primary_metric < best_val_metric:
            best_val_metric = primary_metric
            patience_counter = 0
            torch.save(
                model.state_dict(),
                save_path / f"{config.experiment_name}_finetune_best.pt",
            )
        else:
            patience_counter += 1
            if patience_counter >= config.patience:
                print(f"Early stopping at epoch {epoch+1}")
                break

    writer.close()
    return {"best_val_metric": best_val_metric, "epochs_trained": epoch + 1}
