"""
Neural Extended Kalman Filter for PD state estimation.

State vector: [gait_phase, tremor_amplitude, bradykinesia_index, asymmetry]
- gait_phase: current phase in gait cycle (0-2*pi)
- tremor_amplitude: instantaneous tremor severity
- bradykinesia_index: movement slowness score
- asymmetry: left-right movement asymmetry

The process model and measurement model are both learned.
This fuses the physics-informed structure of an EKF with the
representational power of neural networks.
"""
import torch
import torch.nn as nn


STATE_DIM = 4  # gait_phase, tremor, bradykinesia, asymmetry


class LearnedProcessModel(nn.Module):
    """Learned state transition: x_{t+1} = f(x_t) + noise.

    Predicts both the next state and the process noise covariance.
    """

    def __init__(self, state_dim: int = STATE_DIM, hidden_dim: int = 64):
        super().__init__()
        self.state_transition = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )
        # Predict log-diagonal of process noise covariance
        self.noise_net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )

    def forward(
        self, state: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            state: (B, state_dim)

        Returns:
            next_state: (B, state_dim) predicted next state
            Q: (B, state_dim, state_dim) process noise covariance (diagonal)
        """
        # Residual connection: next_state = state + delta
        delta = self.state_transition(state)
        next_state = state + delta

        # Process noise covariance (diagonal, positive definite via exp)
        log_q = self.noise_net(state)
        q_diag = torch.exp(log_q)  # (B, state_dim)
        Q = torch.diag_embed(q_diag)  # (B, state_dim, state_dim)

        return next_state, Q


class LearnedMeasurementModel(nn.Module):
    """Maps IMU encoder features to measurement of the state.

    z_t = h(imu_features) where z_t is an observation of the state.
    Also predicts measurement noise covariance R.
    """

    def __init__(
        self,
        feature_dim: int = 128,
        state_dim: int = STATE_DIM,
        hidden_dim: int = 64,
    ):
        super().__init__()
        self.measurement = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )
        # Measurement noise covariance
        self.noise_net = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )

    def forward(
        self, features: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            features: (B, feature_dim) from IMU encoder

        Returns:
            z: (B, state_dim) measurement
            R: (B, state_dim, state_dim) measurement noise cov (diagonal)
        """
        z = self.measurement(features)
        log_r = self.noise_net(features)
        r_diag = torch.exp(log_r)
        R = torch.diag_embed(r_diag)
        return z, R


class NeuralEKF(nn.Module):
    """Differentiable Extended Kalman Filter with learned dynamics.

    Runs EKF update equations with neural process/measurement models.
    Fully differentiable for end-to-end training.
    """

    def __init__(
        self,
        state_dim: int = STATE_DIM,
        feature_dim: int = 128,
        hidden_dim: int = 64,
    ):
        super().__init__()
        self.state_dim = state_dim
        self.process_model = LearnedProcessModel(state_dim, hidden_dim)
        self.measurement_model = LearnedMeasurementModel(
            feature_dim, state_dim, hidden_dim
        )

        # Initial state and covariance (learned)
        self.init_state = nn.Parameter(torch.zeros(state_dim))
        self.init_log_cov = nn.Parameter(torch.zeros(state_dim))

    def _predict(
        self,
        state: torch.Tensor,
        P: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """EKF predict step.

        Args:
            state: (B, state_dim)
            P: (B, state_dim, state_dim) covariance

        Returns:
            predicted state and covariance
        """
        # Compute Jacobian of process model via autograd
        state_for_jac = state.detach().requires_grad_(True)
        pred_state, Q = self.process_model(state_for_jac)

        # Compute Jacobian F = df/dx
        F = torch.zeros(
            state.size(0), self.state_dim, self.state_dim,
            device=state.device,
        )
        for i in range(self.state_dim):
            grad_outputs = torch.zeros_like(pred_state)
            grad_outputs[:, i] = 1.0
            grad = torch.autograd.grad(
                pred_state, state_for_jac,
                grad_outputs=grad_outputs,
                retain_graph=True,
                create_graph=self.training,
            )[0]
            F[:, i, :] = grad

        # Re-run without detach for gradient flow
        pred_state, Q = self.process_model(state)

        # P_pred = F @ P @ F^T + Q
        P_pred = torch.bmm(torch.bmm(F, P), F.transpose(1, 2)) + Q

        return pred_state, P_pred

    def _update(
        self,
        state: torch.Tensor,
        P: torch.Tensor,
        z: torch.Tensor,
        R: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """EKF update step (linear measurement model: H = I).

        Args:
            state: (B, state_dim) predicted state
            P: (B, state_dim, state_dim) predicted covariance
            z: (B, state_dim) measurement
            R: (B, state_dim, state_dim) measurement noise

        Returns:
            updated state and covariance
        """
        # Innovation
        y = z - state  # (B, state_dim)

        # Innovation covariance: S = P + R (H = I)
        S = P + R

        # Kalman gain: K = P @ S^{-1}
        K = torch.linalg.solve(S.transpose(1, 2), P.transpose(1, 2))
        K = K.transpose(1, 2)  # (B, state_dim, state_dim)

        # State update
        new_state = state + torch.bmm(K, y.unsqueeze(-1)).squeeze(-1)

        # Covariance update (Joseph form for numerical stability)
        I = torch.eye(self.state_dim, device=state.device).unsqueeze(0)
        IKH = I - K  # H = I
        new_P = torch.bmm(torch.bmm(IKH, P), IKH.transpose(1, 2)) + \
                torch.bmm(torch.bmm(K, R), K.transpose(1, 2))

        return new_state, new_P

    def forward(
        self,
        imu_features_seq: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Run EKF over a sequence of IMU feature vectors.

        Args:
            imu_features_seq: (B, T, feature_dim) sequence of encoded IMU windows

        Returns:
            states: (B, T, state_dim) filtered state trajectory
            covs: (B, T, state_dim, state_dim) covariance trajectory
        """
        B, T, _ = imu_features_seq.shape
        device = imu_features_seq.device

        # Initialize
        state = self.init_state.unsqueeze(0).expand(B, -1)
        P = torch.diag_embed(
            torch.exp(self.init_log_cov).unsqueeze(0).expand(B, -1)
        )

        states = []
        covs = []

        for t in range(T):
            # Predict
            state, P = self._predict(state, P)

            # Get measurement from IMU features
            z, R = self.measurement_model(imu_features_seq[:, t])

            # Update
            state, P = self._update(state, P, z, R)

            states.append(state)
            covs.append(P)

        states = torch.stack(states, dim=1)  # (B, T, state_dim)
        covs = torch.stack(covs, dim=1)  # (B, T, state_dim, state_dim)

        return states, covs


class PDNeuralEKFModel(nn.Module):
    """Complete model: IMU Encoder -> Neural EKF -> Prediction Heads.

    This is the main model that combines:
    1. IMU Transformer Encoder (per-window features)
    2. Neural EKF (temporal filtering across windows)
    3. Prediction heads (UPDRS, H&Y, etc.)
    """

    def __init__(
        self,
        in_channels: int = 6,
        token_dim: int = 128,
        n_heads: int = 8,
        n_layers: int = 4,
        patch_size: int = 50,
        state_dim: int = STATE_DIM,
    ):
        super().__init__()
        # Import here to avoid circular imports
        from src.models.imu_encoder import IMUTransformerEncoder, PDPredictionHeads

        self.encoder = IMUTransformerEncoder(
            in_channels=in_channels,
            token_dim=token_dim,
            n_heads=n_heads,
            n_layers=n_layers,
            patch_size=patch_size,
        )
        self.ekf = NeuralEKF(
            state_dim=state_dim,
            feature_dim=token_dim,
        )

        # Prediction from EKF state (not raw features)
        self.hy_head = nn.Sequential(
            nn.Linear(state_dim, 32),
            nn.GELU(),
            nn.Linear(32, 5),
        )
        self.updrs_head = nn.Sequential(
            nn.Linear(state_dim, 32),
            nn.GELU(),
            nn.Linear(32, 1),
        )

    def forward(
        self, imu_windows: torch.Tensor
    ) -> dict[str, torch.Tensor]:
        """
        Args:
            imu_windows: (B, N_windows, C, T) batch of IMU window sequences

        Returns:
            dict with predictions from final EKF state
        """
        B, N, C, T = imu_windows.shape

        # Encode each window independently
        imu_flat = imu_windows.reshape(B * N, C, T)
        features_flat = self.encoder(imu_flat)  # (B*N, token_dim)
        features = features_flat.reshape(B, N, -1)  # (B, N, token_dim)

        # Run EKF over window sequence
        states, covs = self.ekf(features)  # (B, N, state_dim)

        # Predict from final state
        final_state = states[:, -1]  # (B, state_dim)

        return {
            "hy_stage": self.hy_head(final_state),
            "updrs": self.updrs_head(final_state).squeeze(-1),
            "states": states,
            "covariances": covs,
        }
