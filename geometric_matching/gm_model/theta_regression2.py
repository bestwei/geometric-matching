from __future__ import print_function, division
import torch
import torch.nn as nn

class ThetaRegression(nn.Module):
    """
    Do regression to tnf parameters theta
    theta.shape: (batch_size, 18) for tps, (batch_size, 6) for affine
    """
    def __init__(self, output_dim=6, batch_normalization=True, kernel_sizes=[1, 7, 5, 3], channels=[256, 128, 64, 32], feature_size=15):
        super(ThetaRegression, self).__init__()
        num_layers = len(kernel_sizes)
        nn_modules = list()
        # Feature map.shape: (batch_size, 225, 15, 15) to (batch_size, 128, 9, 9) to (batch_size, 64, 5, 5)
        for i in range(num_layers):
            # Number of input feature map channels
            if i == 0:
                ch_in = feature_size * feature_size
            else:
                ch_in = channels[i - 1]
            ch_out = channels[i]    # Number of output feature map channels
            k_size = kernel_sizes[i]    # Kernel size of current layer
            # self.conv consists of two conv, batchnorm, relu blocks
            nn_modules.append(nn.Conv2d(ch_in, ch_out, kernel_size=k_size, padding=0))
            if batch_normalization:
                nn_modules.append(nn.BatchNorm2d(ch_out))
            nn_modules.append(nn.ReLU(inplace=True))
        self.conv = nn.Sequential(*nn_modules)
        self.linear = nn.Linear(ch_out * k_size * k_size, output_dim)
        nn.init.constant_(self.linear.weight, 0)
        # self.linear.weight.data.normal_(0, 1e-6)
        if output_dim == 36:
            # Initialize the network with an identity tps, i.e. identity mapping between source and target image
            self.linear.bias.data.copy_(torch.Tensor([-1, -1, -1, 0, 0, 0, 1, 1, 1, -1, 0, 1, -1, 0, 1, -1, 0, 1, \
                                                      -1, -1, -1, 0, 0, 0, 1, 1, 1, -1, 0, 1, -1, 0, 1, -1, 0, 1]))
        elif output_dim == 24:
            self.linear.bias.data.copy_(torch.Tensor([0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]))
        elif output_dim == 18:
            # Initialize the network with an identity tps, i.e. identity mapping between source and target image
            self.linear.bias.data.copy_(torch.Tensor([-1, -1, -1, 0, 0, 0, 1, 1, 1, -1, 0, 1, -1, 0, 1, -1, 0, 1]))
        elif output_dim == 6:
            self.linear.bias.data.copy_(torch.Tensor([1, 0, 0, 0, 1, 0]))

    def forward(self, x):
        # x.shape: (batch_size, 225, 15, 15)
        x = self.conv(x)
        # x.shape: (batch_size, 64, 5, 5)
        x = x.view(x.size(0), -1)
        # x.shape: (batch_size, output_dim)
        x = self.linear(x)
        return x