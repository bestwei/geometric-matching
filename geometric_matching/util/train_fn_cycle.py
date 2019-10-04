# ========================================================================================
# Train and evaluate geometric matching model
# Author: Jingwei Qu
# Date: 01 June 2019
# ========================================================================================

from __future__ import print_function, division
import torch
import torchvision
import time
import cv2

from geometric_matching.geotnf.transformation import GeometricTnf
from geometric_matching.util.net_util import *
from geometric_matching.image.normalization import normalize_image

import matplotlib
# matplotlib.use('Qt5Agg')
import matplotlib.pyplot as plt

def show_images(batch_st, batch_tr, warped_image=None, warped_image_2=None, warped_image_3=None, box_s=None, box_t=None, box_r=None):
    # Show images
    if box_s is not None:
        rows = 2
    else:
        rows = 3
    cols = 3
    for i in range(batch_st['source_image'].shape[0]):
        show_id = i

        if box_s is not None:
            ax_1 = im_show_1(batch_st['source_image'][show_id], 'source_image', rows, cols, 1)
            show_boxes(ax_1, box_s[show_id, :].reshape(1, -1))

            ax_2 = im_show_1(batch_st['target_image'][show_id], 'target_image', rows, cols, 2)
            show_boxes(ax_2, box_t[show_id, :].reshape(1, -1))

            ax_3 = im_show_1(batch_tr['target_image'][show_id], 'refer_image', rows, cols, 3)
            show_boxes(ax_3, box_r[show_id, :].reshape(1, -1))

            ax_4 = im_show_2(batch_st['source_im'][show_id], 'source_im', rows, cols, 4)
            show_boxes(ax_4, box_s[show_id, :].reshape(1, -1))

            ax_5 = im_show_2(batch_st['target_im'][show_id], 'target_im', rows, cols, 5)
            show_boxes(ax_5, box_t[show_id, :].reshape(1, -1))

            ax_6 = im_show_2(batch_tr['target_im'][show_id], 'refer_im', rows, cols, 6)
            show_boxes(ax_6, box_r[show_id, :].reshape(1, -1))

        else:
            im_show_1(batch_st['source_image'][show_id], 'source_image', rows, cols, 1)

            im_show_1(warped_image[show_id], 'warped_image', rows, cols, 2)

            im_show_1(batch_st['target_image'][show_id], 'target_image', rows, cols, 3)


            im_show_1(batch_tr['source_image'][show_id], 'target_image', rows, cols, 4)

            im_show_1(warped_image_2[show_id], 'warped_image_2', rows, cols, 5)

            im_show_1(batch_tr['target_image'][show_id], 'refer_image', rows, cols, 6)


            im_show_1(batch_st['source_image'][show_id], 'source_image', rows, cols, 7)

            im_show_1(warped_image_3[show_id], 'warped_image_3', rows, cols, 8)

            im_show_1(batch_tr['target_image'][show_id], 'refer_image', rows, cols, 9)

        # mng = plt.get_current_fig_manager()
        # mng.window.showMaximized()
        plt.show()

def add_watch(watch_images, image_names, batch_st, batch_tr, geoTnf, theta_st, theta_tr, k):
    warped_image_st = geoTnf(batch_st['source_image'][0].unsqueeze(0), theta_st[0].unsqueeze(0))
    warped_image_tr = geoTnf(batch_tr['source_image'][0].unsqueeze(0), theta_tr[0].unsqueeze(0))
    warped_image_sr = geoTnf(warped_image_st, theta_tr[0].unsqueeze(0))

    watch_images[k, :, 0:240, :] = batch_st['source_image'][0]
    watch_images[k + 1, :, 0:240, :] = warped_image_st.detach()
    watch_images[k + 2, :, 0:240, :] = batch_st['target_image'][0]
    watch_images[k + 3, :, 0:240, :] = warped_image_tr.detach()
    watch_images[k + 4, :, 0:240, :] = batch_tr['target_image'][0]
    watch_images[k + 5, :, 0:240, :] = warped_image_sr.detach()

    image_names.append('Source')
    image_names.append('Warped_st')
    image_names.append('Target')
    image_names.append('Warped_tr')
    image_names.append('Refer')
    image_names.append('Warped_sr')

    return watch_images, image_names

def train_fn(epoch, model, loss_fn, loss_cycle_fn, lambda_c, optimizer, dataloader, triple_generation, geometric_model='tps', use_cuda=True,
             log_interval=100, vis=None, show=False):
    """
        Train the model with synthetically training triple:
        {source image, target image, refer image (warped source image), theta_GT} from PF-PASCAL.
        1. Train the transformation parameters theta_st from source image to target image;
        2. Train the transformation parameters theta_tr from target image to refer image;
        3. Combine theta_st and theta_st to obtain theta from source image to refer image, and compute loss between
        theta and theta_GT.
    """

    geoTnf = GeometricTnf(geometric_model=geometric_model, use_cuda=use_cuda)
    epoch_loss = 0
    if (epoch % 5 == 0 or epoch == 1) and vis is not None:
        stride_images = len(dataloader) / 3
        group_size = 6
        watch_images = torch.ones(group_size * 4, 3, 260, 240).cuda()
        image_names = list()
        fnt = cv2.FONT_HERSHEY_COMPLEX
        # means for normalize of caffe resnet and vgg
        # pixel_means = torch.Tensor(np.array([[[[102.9801, 115.9465, 122.7717]]]]).astype(np.float32)).cuda()
        stride_loss = len(dataloader) / 105
        iter_loss = np.zeros(106)
    begin = time.time()
    for batch_idx, batch in enumerate(dataloader):
        ''' Move input batch to gpu '''
        # batch['source_image'].shape & batch['target_image'].shape: (batch_size, 3, 240, 240)
        # batch['theta'].shape-tps: (batch_size, 18)-random or (batch_size, 18, 1, 1)-(pre-set from csv)
        if use_cuda:
            batch = batch_cuda(batch)

        ''' Get the training triple {source image, target image, refer image (warped source image), theta_GT}'''
        batch_triple = triple_generation(batch)

        ''' Train the model '''
        optimizer.zero_grad()
        loss = 0
        # Predict tps parameters between images
        # theta.shape: (batch_size, 18) for tps, theta.shape: (batch_size, 6) for affine
        batch_st = {'source_image': batch_triple['source_image'], 'target_image': batch_triple['target_image']}
        batch_tr = {'source_image': batch_triple['target_image'], 'target_image': batch_triple['refer_image']}
        theta_st, theta_ts = model(batch_st)  # from source image to target image
        theta_tr, theta_rt = model(batch_tr)  # from target image to refer image
        loss_match = loss_fn(theta_st=theta_st, theta_tr=theta_tr, theta_GT=batch_triple['theta_GT'])
        loss_cycle_st = loss_cycle_fn(theta_AB=theta_st, theta_BA=theta_ts)
        loss_cycle_ts = loss_cycle_fn(theta_AB=theta_ts, theta_BA=theta_st)
        loss_cycle_tr = loss_cycle_fn(theta_AB=theta_tr, theta_BA=theta_rt)
        loss_cycle_rt = loss_cycle_fn(theta_AB=theta_rt, theta_BA=theta_tr)
        loss = loss_match + lambda_c * (loss_cycle_st + loss_cycle_ts + loss_cycle_tr + loss_cycle_rt) / 4
        loss.backward()
        optimizer.step()
        epoch_loss += loss.item()
        if (batch_idx+1) % log_interval == 0:
            end = time.time()
            print('Train epoch: {} [{}/{} ({:.0%})]\t\tCurrent batch loss: {:.6f}\t\tTime cost ({} batches): {:.4f} s'
                  .format(epoch, batch_idx+1, len(dataloader), (batch_idx+1) / len(dataloader), loss.item(), batch_idx + 1, end - begin))

        if (epoch % 5 == 0 or epoch == 1) and vis is not None:
            if (batch_idx + 1) % stride_images == 0 or batch_idx == 0:
                watch_images, image_names = add_watch(watch_images, image_names, batch_st, batch_tr, geoTnf, theta_st, theta_tr, int((batch_idx + 1) / stride_images) * group_size)
            if (batch_idx + 1) % stride_loss == 0 or batch_idx == 0:
                iter_loss[int((batch_idx + 1) / stride_loss)] = epoch_loss / (batch_idx + 1)

        # watch_images = normalize_image(batch_tr['target_image'], forward=False) * 255.0
        # vis.images(watch_images, nrow=8, padding=3)

        # if show:
        #     if dual:
        #         warped_image_aff = affTnf(batch_st['source_image'], theta_aff_st_1)
        #         warped_image_aff_2 = affTnf(batch_tr['source_image'], theta_aff_tr_1)
        #         warped_image_aff_3 = affTnf(warped_image_aff, theta_aff_tr_1)
        #         show_images(batch_st, batch_tr, warped_image_aff.detach(), warped_image_aff_2.detach(), warped_image_aff_3.detach())
        #
        #         warped_image_aff = affTnf(batch_st['source_image'], theta_aff_st)
        #         warped_image_aff_2 = affTnf(batch_tr['source_image'], theta_aff_tr)
        #         warped_image_aff_3 = affTnf(warped_image_aff, theta_aff_tr)
        #         show_images(batch_st, batch_tr, warped_image_aff.detach(), warped_image_aff_2.detach(), warped_image_aff_3.detach())
        #
        #         warped_image_aff_tps = tpsTnf(batch_st['source_image'], theta_aff_tps_st)
        #         warped_image_aff_tps_2 = tpsTnf(batch_tr['source_image'], theta_aff_tps_tr)
        #         warped_image_aff_tps_3 = tpsTnf(warped_image_aff_tps, theta_aff_tps_tr)
        #         show_images(batch_st, batch_tr, warped_image_aff_tps.detach(), warped_image_aff_tps_2.detach(), warped_image_aff_tps_3.detach())
        #
        #         warped_image = affTnf(batch_st['source_image'], theta_aff_st_1)
        #         warped_image = affTnf(warped_image, theta_aff_st)
        #         warped_image = tpsTnf(warped_image, theta_aff_tps_st)
        #         warped_image_2 = affTnf(batch_tr['source_image'], theta_aff_tr_1)
        #         warped_image_2 = affTnf(warped_image_2, theta_aff_tr)
        #         warped_image_2 = tpsTnf(warped_image_2, theta_aff_tps_tr)
        #         warped_image_3 = affTnf(warped_image, theta_aff_tr_1)
        #         warped_image_3 = affTnf(warped_image_3, theta_aff_tr)
        #         warped_image_3 = tpsTnf(warped_image_3, theta_aff_tps_tr)
        #         show_images(batch_st, batch_tr, warped_image.detach(), warped_image_2.detach(), warped_image_3.detach())
        #     else:
        #         warped_image_aff = affTnf(batch_st['source_image'], theta_st)
        #         warped_image_aff_2 = affTnf(batch_tr['source_image'], theta_tr)
        #         warped_image_aff_3 = affTnf(warped_image_aff, theta_tr)
        #         show_images(batch_st, batch_tr, warped_image_aff.detach(), warped_image_aff_2.detach(), warped_image_aff_3.detach())

                # warped_image_tps = tpsTnf(batch_st['source_image'], theta_st)
                # warped_image_tps_2 = tpsTnf(batch_tr['source_image'], theta_tr)
                # warped_image_tps_3 = tpsTnf(warped_image_tps, theta_tr)
                # show_images(batch_st, batch_tr, warped_image_tps.detach(), warped_image_tps_2.detach(), warped_image_tps_3.detach())

    end = time.time()

    # Visualize watch images & train loss
    if (epoch % 5 == 0 or epoch == 1) and vis is not None:
        opts = dict(jpgquality=100, title='Epoch ' + str(epoch) + ' source warped_sr target warped_tr refer warped_sr')
        watch_images[:, :, 0:240, :] = normalize_image(watch_images[:, :, 0:240, :], forward=False)
        watch_images *= 255.0
        watch_images = watch_images.permute(0, 2, 3, 1).cpu().numpy().astype(np.uint8)
        for i in range(watch_images.shape[0]):
            cv2.putText(watch_images[i], image_names[i], (80, 255), fnt, 0.5, (0, 0, 0), 1)
        watch_images = torch.Tensor(watch_images.astype(np.float32))
        watch_images = watch_images.permute(0, 3, 1, 2)
        vis.image(torchvision.utils.make_grid(watch_images, nrow=group_size, padding=3), opts=opts)
        # Un-normalize for caffe resnet and vgg
        # watch_images = watch_images.permute(0, 2, 3, 1) + pixel_means
        # watch_images = watch_images[:, :, :, [2, 1, 0]].permute(0, 3, 1, 2)

        opts_loss = dict(xlabel='Iterations (' + str(stride_loss) + ')',
                         ylabel='Loss',
                         title='GM ResNet101 ' + geometric_model + ' Training Loss in Epoch ' + str(epoch),
                         legend=['Loss'],
                         width=2000)
        vis.line(iter_loss, np.arange(106), opts=opts_loss)

    epoch_loss /= len(dataloader)
    print('Train set -- Average loss: {:.6f}\t\tTime cost: {:.4f}'.format(epoch_loss, end - begin))
    return epoch_loss, end - begin