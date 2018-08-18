from __future__ import absolute_import, division, print_function, unicode_literals

import os
import random
import unittest
from math import pi

import gpytorch
import torch
from gpytorch.kernels import MultitaskKernel, RBFKernel
from gpytorch.likelihoods import MultitaskGaussianLikelihood
from gpytorch.means import ConstantMean, MultitaskMean
from gpytorch.random_variables import MultitaskGaussianRandomVariable


# Simple training data: let's try to learn a sine function
train_x = torch.linspace(0, 1, 100)
latent_error = torch.randn(train_x.size()) * 0.5

# y1 function is sin(2*pi*x) with noise N(0, 0.04)
train_y1 = (
    torch.sin(train_x.data * (2 * pi))
    + latent_error
    + torch.randn(train_x.size()) * 0.1
)
# y2 function is cos(2*pi*x) with noise N(0, 0.04)
train_y2 = (
    torch.cos(train_x.data * (2 * pi))
    + latent_error
    + torch.randn(train_x.size()) * 0.1
)

# Create a train_y which interleaves the two
train_y = torch.stack([train_y1, train_y2], -1)


class MultitaskGPModel(gpytorch.models.ExactGP):
    def __init__(self, train_x, train_y, likelihood):
        super(MultitaskGPModel, self).__init__(train_x, train_y, likelihood)
        self.mean_module = MultitaskMean(ConstantMean(), n_tasks=2)
        self.data_covar_module = RBFKernel()
        self.covar_module = MultitaskKernel(self.data_covar_module, n_tasks=2, rank=1)

    def forward(self, x):
        mean_x = self.mean_module(x)
        covar_x = self.covar_module(x)
        return MultitaskGaussianRandomVariable(mean_x, covar_x)


class TestMultiTaskGPRegression(unittest.TestCase):
    def setUp(self):
        if (
            os.getenv("UNLOCK_SEED") is None
            or os.getenv("UNLOCK_SEED").lower() == "false"
        ):
            self.rng_state = torch.get_rng_state()
            torch.manual_seed(0)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(0)
            random.seed(0)

    def tearDown(self):
        if hasattr(self, "rng_state"):
            torch.set_rng_state(self.rng_state)

    def test_multitask_gp_mean_abs_error(self):
        likelihood = MultitaskGaussianLikelihood(n_tasks=2, rank=1)
        model = MultitaskGPModel(train_x, train_y, likelihood)
        # Find optimal model hyperparameters
        model.train()
        likelihood.train()

        # Use the adam optimizer
        optimizer = torch.optim.Adam(
            [{"params": model.parameters()}],  # Includes GaussianLikelihood parameters
            lr=0.1,
        )

        # "Loss" for GPs - the marginal log likelihood
        mll = gpytorch.mlls.ExactMarginalLogLikelihood(likelihood, model)

        n_iter = 50
        for _ in range(n_iter):
            # Zero prev backpropped gradients
            optimizer.zero_grad()
            # Make predictions from training data
            # Again, note feeding duplicated x_data and indices indicating which task
            output = model(train_x)
            # TODO: Fix this view call!!
            loss = -mll(output, train_y)
            loss.backward()
            optimizer.step()

        # Test the model
        model.eval()
        likelihood.eval()

        n_tasks = 2
        task_noise_covar_factor = likelihood.task_noise_covar_factor
        log_noise = likelihood.log_noise
        task_noise_covar = task_noise_covar_factor.matmul(
            task_noise_covar_factor.transpose(-1, -2)
        ) + log_noise.exp() * torch.eye(n_tasks)

        self.assertGreater(task_noise_covar[0, 1].data.squeeze().item(), 0.05)


if __name__ == "__main__":
    unittest.main()