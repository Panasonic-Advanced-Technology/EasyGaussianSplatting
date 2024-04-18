import torch
import torchvision
import numpy as np
from math import exp
from torch.autograd import Variable
import torch.nn.functional as F
import matplotlib.pyplot as plt
import torch.nn as nn
import torch.optim as optim


import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'viewer'))

from viewer import *
from custom_items import *


# More information about real spherical harmonics can be obtained from:
# https://en.wikipedia.org/wiki/Table_of_spherical_harmonics
# https://github.com/NVlabs/tiny-cuda-nn/blob/master/scripts/gen_sh.py

SH_C0_0 = 0.28209479177387814  # Y0,0:  1/2*sqrt(1/pi)       plus

SH_C1_0 = -0.4886025119029199  # Y1,-1: sqrt(3/(4*pi))       minus
SH_C1_1 = 0.4886025119029199   # Y1,0:  sqrt(3/(4*pi))       plus
SH_C1_2 = -0.4886025119029199  # Y1,1:  sqrt(3/(4*pi))       minus

SH_C2_0 = 1.0925484305920792   # Y2,-2: 1/2 * sqrt(15/pi)    plus
SH_C2_1 = -1.0925484305920792  # Y2,-1: 1/2 * sqrt(15/pi)    minus
SH_C2_2 = 0.31539156525252005  # Y2,0:  1/4*sqrt(5/pi)       plus
SH_C2_3 = -1.0925484305920792  # Y2,1:  1/2*sqrt(15/pi)      minus
SH_C2_4 = 0.5462742152960396   # Y2,2:  1/4*sqrt(15/pi)      plus

SH_C3_0 = -0.5900435899266435  # Y3,-3: 1/4*sqrt(35/(2*pi))  minus
SH_C3_1 = 2.890611442640554    # Y3,-2: 1/2*sqrt(105/pi)     plus
SH_C3_2 = -0.4570457994644658  # Y3,-1: 1/4*sqrt(21/(2*pi))  minus
SH_C3_3 = 0.3731763325901154   # Y3,0:  1/4*sqrt(7/pi)       plus
SH_C3_4 = -0.4570457994644658  # Y3,1:  1/4*sqrt(21/(2*pi))  minus
SH_C3_5 = 1.445305721320277    # Y3,2:  1/4*sqrt(105/pi)     plus
SH_C3_6 = -0.5900435899266435  # Y3,3:  1/4*sqrt(35/(2*pi))  minus

SH_C4_0 = 2.5033429417967046  # Y4,-4:  3/4*sqrt(35/pi)       plus
SH_C4_1 = -1.7701307697799304  # Y4,-3:  3/4*sqrt(35/(2*pi))  minus
SH_C4_2 = 0.9461746957575601  # Y4,-2:  3/4*sqrt(5/pi)        plus
SH_C4_3 = -0.6690465435572892  # Y4,-1:  3/4*sqrt(5/(2*pi))   minus
SH_C4_4 = 0.10578554691520431  # Y4,0:  3/16*sqrt(1/pi)       plus
SH_C4_5 = -0.6690465435572892  # Y4,1:  3/4*sqrt(5/(2*pi))    minus
SH_C4_6 = 0.47308734787878004  # Y4,2:  3/8*sqrt(5/pi)        plus
SH_C4_7 = -1.7701307697799304  # Y4,3:  3/4*sqrt(35/(2*pi))   minus
SH_C4_8 = 0.6258357354491761  # Y4,4:  3/16*sqrt(35/pi)       plus

SH_C5_0 = -0.65638205684017015
SH_C5_1 = 8.3026492595241645
SH_C5_2 = -0.48923829943525038
SH_C5_3 = 4.7935367849733241
SH_C5_4 = -0.45294665119569694
SH_C5_5 = 0.1169503224534236
SH_C5_6 = -0.45294665119569694
SH_C5_7 = 2.3967683924866621
SH_C5_8 = -0.48923829943525038
SH_C5_9 = 2.0756623148810411
SH_C5_10 = -0.65638205684017015


def rotation_matrix_from_axis_angle(axis, angle):
        c = np.cos(angle)
        s = np.sin(angle)
        t = 1 - c
        x, y, z = axis / np.linalg.norm(axis)
        rotation_matrix = np.array([
            [t*x*x + c, t*x*y - s*z, t*x*z + s*y, 0],
            [t*x*y + s*z, t*y*y + c, t*y*z - s*x, 0],
            [t*x*z - s*y, t*y*z + s*x, t*z*z + c, 0],
            [0, 0, 0, 1]
        ])
        return rotation_matrix


def create_rotation_matrix(angle):
        axis = np.array([0, 0, 1])
        rotation_matrix = rotation_matrix_from_axis_angle(axis, angle)
        return rotation_matrix


def rotate(sphere, angle_increment=0.01):
    rotation_angle = 0

    def updateTransform():
        nonlocal rotation_angle
        while True:
            T = create_rotation_matrix(rotation_angle)
            for i, s in enumerate(sphere.values()):
                T[0, 3] = 2.5 * i
                s.setTransform(T)
            rotation_angle += angle_increment
            time.sleep(0.02)  # Adjust the sleep duration as needed

    rotation_thread = threading.Thread(target=updateTransform)
    rotation_thread.daemon = True
    rotation_thread.start()


device='cuda'


def sh2color(sh, ray_dir, dim=36):
    # lib = np if mode == 'torch' else torch
    dCdSH = None
    if isinstance(sh, np.ndarray):
        dCdSH = np.zeros([sh.shape[0], ray_dir.shape[0]], dtype=np.float32)
    elif isinstance(sh, torch.Tensor):
        dCdSH = torch.zeros([sh.shape[0], ray_dir.shape[0]], dtype=torch.float32, device=device)
    else:
        raise TypeError("unspport type.")

    sh_dim = np.min([sh.shape[0], dim])
    dCdSH[0] = SH_C0_0
    color = (dCdSH[0] * sh[0][:, np.newaxis]) + 0.5

    if (sh_dim <= 1):
        return color, dCdSH.T

    x = ray_dir[:, 0]
    y = ray_dir[:, 1]
    z = ray_dir[:, 2]
    dCdSH[1] = SH_C1_0 * y
    dCdSH[2] = SH_C1_1 * z
    dCdSH[3] = SH_C1_2 * x
    color = color + \
        dCdSH[1] * sh[1][:, np.newaxis] + \
        dCdSH[2] * sh[2][:, np.newaxis] + \
        dCdSH[3] * sh[3][:, np.newaxis]

    if (sh_dim <= 4):
        return color, dCdSH.T
    x2 = x * x
    y2 = y * y
    z2 = z * z
    xy = x * y
    yz = y * z
    xz = x * z
    dCdSH[4] = SH_C2_0 * xy
    dCdSH[5] = SH_C2_1 * yz
    dCdSH[6] = SH_C2_2 * (2.0 * z2 - x2 - y2)
    dCdSH[7] = SH_C2_3 * xz
    dCdSH[8] = SH_C2_4 * (x2 - y2)
    color = color + \
        dCdSH[4] * sh[4][:, np.newaxis] + \
        dCdSH[5] * sh[5][:, np.newaxis] + \
        dCdSH[6] * sh[6][:, np.newaxis] + \
        dCdSH[7] * sh[7][:, np.newaxis] + \
        dCdSH[8] * sh[8][:, np.newaxis]

    if (sh_dim <= 9):
        return color, dCdSH.T
    dCdSH[9] = SH_C3_0 * y * (3.0 * x2 - y2)
    dCdSH[10] = SH_C3_1 * xy * z
    dCdSH[11] = SH_C3_2 * y * (4.0 * z2 - x2 - y2)
    dCdSH[12] = SH_C3_3 * z * (2.0 * z2 - 3.0 * x2 - 3.0 * y2)
    dCdSH[13] = SH_C3_4 * x * (4.0 * z2 - x2 - y2)
    dCdSH[14] = SH_C3_5 * z * (x2 - y2)
    dCdSH[15] = SH_C3_6 * x * (x2 - 3.0 * y2)

    color = color +  \
        dCdSH[9] * sh[9][:, np.newaxis] + \
        dCdSH[10] * sh[10][:, np.newaxis] + \
        dCdSH[11] * sh[11][:, np.newaxis] + \
        dCdSH[12] * sh[12][:, np.newaxis] + \
        dCdSH[13] * sh[13][:, np.newaxis] + \
        dCdSH[14] * sh[14][:, np.newaxis] + \
        dCdSH[15] * sh[15][:, np.newaxis]

    if (sh_dim <= 16):
        return color, dCdSH.T

    x4 = x2 * x2
    y4 = y2 * y2
    z4 = z2 * z2
    dCdSH[16] = SH_C4_0 * xy * (x2 - y2)
    dCdSH[17] = SH_C4_1 * yz * (3*x2 - y2)
    dCdSH[18] = SH_C4_2 * xy * (7*z2 - 1)
    dCdSH[19] = SH_C4_3 * yz * (7*z2 - 3)  # 4*z2*z - 3*x2*z - 3*z*y2
    dCdSH[20] = SH_C4_4 * (35 * z4 - 30 * z2 + 3)
    dCdSH[21] = SH_C4_5 * xz * (7 * z2 - 3)
    dCdSH[22] = SH_C4_6 * (x2 - y2) * (7*z2-1)
    dCdSH[23] = SH_C4_7 * xz * (x2 - 3*y2)
    dCdSH[24] = SH_C4_8 * (x4 - 6 * x2*y2 + y4)

    color = color +  \
        dCdSH[16] * sh[16][:, np.newaxis] + \
        dCdSH[17] * sh[17][:, np.newaxis] + \
        dCdSH[18] * sh[18][:, np.newaxis] + \
        dCdSH[19] * sh[19][:, np.newaxis] + \
        dCdSH[20] * sh[20][:, np.newaxis] + \
        dCdSH[21] * sh[21][:, np.newaxis] + \
        dCdSH[22] * sh[22][:, np.newaxis] + \
        dCdSH[23] * sh[23][:, np.newaxis] + \
        dCdSH[24] * sh[24][:, np.newaxis]

    if (sh_dim <= 25):
        return color, dCdSH.T
    dCdSH[25] = SH_C5_0*y*(-10.0*x2*y2 + 5.0*x4 + y4)  #
    dCdSH[26] = SH_C5_1*xy*z*(x2 - y2)
    dCdSH[27] = SH_C5_2*y*(3.0*x2 - y2)*(9.0*z2 - 1.0)
    dCdSH[28] = SH_C5_3*xy*z*(3.0*z2 - 1.0)  #
    dCdSH[29] = SH_C5_4*y*(14.0*z2 - 21.0*z4 - 1.0)
    dCdSH[30] = SH_C5_5*z*(70.0*z2 - 63.0*z4 - 15.0)  #
    dCdSH[31] = SH_C5_6*x*(14.0*z2 - 21.0*z4 - 1.0)
    dCdSH[32] = SH_C5_7*z*(x2 - y2)*(3.0*z2 - 1.0)
    dCdSH[33] = SH_C5_8*x*(x2 - 3.0*y2)*(9.0*z2 - 1.0)
    dCdSH[34] = SH_C5_9*z*(-6.0*x2*y2 + x4 + y4)
    dCdSH[35] = SH_C5_10*x*(-10.0*x2*y2 + x4 + 5.0*y4)  #

    color = color +  \
        dCdSH[25] * sh[25][:, np.newaxis] + \
        dCdSH[26] * sh[26][:, np.newaxis] + \
        dCdSH[27] * sh[27][:, np.newaxis] + \
        dCdSH[28] * sh[28][:, np.newaxis] + \
        dCdSH[29] * sh[29][:, np.newaxis] + \
        dCdSH[30] * sh[30][:, np.newaxis] + \
        dCdSH[31] * sh[31][:, np.newaxis] + \
        dCdSH[32] * sh[32][:, np.newaxis] + \
        dCdSH[33] * sh[33][:, np.newaxis] + \
        dCdSH[34] * sh[34][:, np.newaxis] + \
        dCdSH[35] * sh[35][:, np.newaxis]

    return color, dCdSH.T


# spherical harmonics
class SHNet(torch.autograd.Function):

    @staticmethod
    def forward(ctx, sh):
        color, dCdSH = sh2color(sh, xyz)
        ctx.save_for_backward(dCdSH)
        return color.reshape(3, H, W)

    @staticmethod
    def backward(ctx, dL_dC):
        dCdSH,  = ctx.saved_tensors
        dLdSH = dL_dC.reshape(3, -1) @ dCdSH
        return dLdSH.T


if __name__ == "__main__":
    sh = np.zeros([36, 3], dtype=np.float32)  # 1. 4, 9, 16, 25, 36
    sh = torch.from_numpy(sh).to(device).requires_grad_()

    W = int(979)  # 1957  # 979
    H = int(546)  # 1091  # 546

    theta = torch.linspace(0, torch.pi, H, dtype=torch.float32, device=device)
    phi = torch.linspace(0, 2 * torch.pi, W, dtype=torch.float32, device=device)
    angle = torch.stack((torch.meshgrid(theta, phi)), axis=2)
    x = torch.sin(angle[:, :, 0]) * torch.cos(angle[:, :, 1])
    y = torch.sin(angle[:, :, 0]) * torch.sin(angle[:, :, 1])
    z = torch.cos(angle[:, :, 0])
    xyz = torch.dstack((x, y, z)).reshape(-1, 3)

    shnet = SHNet

    image_gt = torchvision.io.read_image("imgs/Solarsystemscope_texture_8k_earth_daymap.jpg").to(device)
    image_gt = torchvision.transforms.functional.resize(image_gt, [H, W]) / 255.

    criterion = nn.MSELoss()
    optimizer = optim.SGD([sh], lr=1.)

    for i in range(100):
        image = shnet.apply(sh)
        loss = criterion(image, image_gt)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        print(loss.item())

    sh = sh.to('cpu').detach().numpy()

    # Display the ground truth image
    image_gt = image_gt.to('cpu').detach().permute(1, 2, 0).numpy()

    # create QT application and sphere items
    app = QApplication([])
    gt = SphereItem()
    sh1 = SphereItem()
    c1, _ = sh2color(sh, sh1.vertices, dim=1)  # level1
    sh2 = SphereItem()
    c2, _ = sh2color(sh, sh2.vertices, dim=9)  # level3
    sh3 = SphereItem()
    c3, _ = sh2color(sh, sh3.vertices, dim=16)  # level4
    sh4 = SphereItem()
    c4, _ = sh2color(sh, sh4.vertices, dim=36)  # level5

    gt.set_colors_from_image(image_gt)
    sh1.set_colors(c1.T)
    sh2.set_colors(c2.T)
    sh3.set_colors(c3.T)
    sh4.set_colors(c4.T)

    s = 3.
    a1 = np.eye(4)
    a1[0, 3] = 1 * s
    sh1.setTransform(a1)

    a2 = np.eye(4)
    a2[0, 3] = 2 * s
    sh2.setTransform(a2)

    a3 = np.eye(4)
    a3[0, 3] = 3 * s
    sh3.setTransform(a3)

    a4 = np.eye(4)
    a4[0, 3] = 4 * s
    sh4.setTransform(a4)

    items = {"sh1": sh1, "sh2": sh2, "sh3": sh3, "sh4": sh4, "gt": gt}

    rotate(items)
    viewer = Viewer(items)
    viewer.show()
    app.exec_()

    # Display the sh image
    """
    fig, ax = plt.subplots(2, 3)
    ax[0, 0].imshow(image_gt.to('cpu').detach().permute(1, 2, 0).numpy())
    xyz = xyz.to('cpu').detach().numpy()

    image, _ = sh2color(sh, xyz, 1)
    image = image.reshape(3, H, W)
    ax[0, 1].imshow(image.transpose(1, 2, 0))

    image, _ = sh2color(sh, xyz, 4)
    image = image.reshape(3, H, W)
    ax[0, 2].imshow(image.transpose(1, 2, 0))

    image, _ = sh2color(sh, xyz, 8)
    image = image.reshape(3, H, W)
    ax[1, 0].imshow(image.transpose(1, 2, 0))

    image, _ = sh2color(sh, xyz, 16)
    image = image.reshape(3, H, W)
    ax[1, 1].imshow(image.transpose(1, 2, 0))

    image, _ = sh2color(sh, xyz)
    image = image.reshape(3, H, W)
    ax[1, 2].imshow(image.transpose(1, 2, 0))

    plt.show()
    """
