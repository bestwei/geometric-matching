# ====================================================================================================
# Test geometric matching model on benchmarks based on the object detection by faster rcnn
# Make an affine transformation before the predicted tps:
# (1) Use the coordinates of bounding boxes (i.e. object detection of the two images) as translation
# parameters of the affine
# (2) Resize the two objects to solve the scale transformation in the affine
# Author: Jingwei Qu
# Date: 27 April 2019
# ====================================================================================================

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import numpy as np
import argparse
import pprint
import time

import torch
from torch.autograd import Variable
import torch.nn as nn
import torch.optim as optim
import pdb
from PIL import Image
from collections import OrderedDict
from visdom import Visdom

from geometric_matching.arguments.arguments_setting import Arguments
from geometric_matching.gm_model.dual_geometric_matching import DualGeometricMatching
from geometric_matching.image.normalization import *
from geometric_matching.gm_data.pf_willow_dataset import PFWILLOWDataset
from geometric_matching.gm_data.pf_pascal_dataset import PFPASCALDataset
from geometric_matching.gm_data.caltech_dataset import CaltechDataset
from geometric_matching.gm_data.tss_dataset import TSSDataset
from geometric_matching.gm_data.watch_dataset import WatchDataset
from geometric_matching.util.net_util import *
from geometric_matching.util.test_watch import *
from geometric_matching.util.vis_watch_dual import *
from geometric_matching.util.dataloader import default_collate

from lib.model.faster_rcnn.vgg16 import vgg16
from lib.model.faster_rcnn.resnet import resnet
from model.utils.config import cfg, cfg_from_file, cfg_from_list

# import matplotlib
# matplotlib.use('Qt5Agg')
# import matplotlib.pyplot as plt

if __name__ == '__main__':

    print('Test GeometricMatching model')

    ''' Load arguments '''
    args, arg_groups = Arguments(mode='test').parse()
    print('Arguments setting:')
    print(args)

    if torch.cuda.is_available() and not args.cuda:
        print('WARNING: You have a CUDA device, so you should probably run with --cuda')

    torch.manual_seed(args.seed)
    if args.cuda:
        torch.cuda.manual_seed(args.seed)
    np.random.seed(args.seed)

    ''' Initialize dual geometric matching model '''
    print('Initialize dual geometric matching model')
    # args.geometric_model = 'tps'
    # print(args.geometric_model)
    # Create geometric_matching model
    # Crop object from image ('img'), feature map of vgg pool4 ('pool4'), feature map of vgg conv1 ('conv1'), or no cropping (None)
    # Feature extraction network: 1. pre-trained on ImageNet; 2. fine-tuned on PascalVOC2011, arg_groups['model']['pretrained'] = pretrained
    model = DualGeometricMatching(aff_output_dim=6, tps_output_dim=18, use_cuda=args.cuda, **arg_groups['model'],
                                       pytorch=False, caffe=False)

    model_weak = DualGeometricMatching(aff_output_dim=6, tps_output_dim=18, use_cuda=args.cuda, **arg_groups['model'],
                                       pytorch=False, caffe=False)

    ''' Set detect geometric matching model '''
    # Load pre-trained model
    if args.model != '':
        GM_cp_name = os.path.join(args.trained_models_dir, args.feature_extraction_cnn, args.model)
        if not os.path.exists(GM_cp_name):
            raise Exception('There is no pre-trained geometric matching model, i.e. ' + GM_cp_name)
        print('Load geometric matching model {}'.format(GM_cp_name))
        GM_checkpoint = torch.load(GM_cp_name, map_location=lambda storage, loc: storage)
        model.load_state_dict(GM_checkpoint['state_dict'])
        print('Load geometric matching model successfully!')

    if args.model_weak != '':
        weak_cp_name = os.path.join(args.trained_models_dir, args.feature_extraction_cnn, args.model_weak)
        if not os.path.exists(weak_cp_name):
            raise Exception('There is no pre-trained geometric matching model, i.e. ' + weak_cp_name)
        print('Load geometric matching model {}'.format(weak_cp_name))
        weak_checkpoint = torch.load(weak_cp_name, map_location=lambda storage, loc: storage)
        model_weak.load_state_dict(weak_checkpoint['state_dict'])

        # weak_checkpoint['state_dict'] = OrderedDict(
        #     [(k.replace('model', 'GM_base'), v) for k, v in weak_checkpoint['state_dict'].items()])
        # weak_checkpoint['state_dict'] = OrderedDict(
        #     [(k.replace('FeatureRegression', 'ThetaRegression'), v) for k, v in weak_checkpoint['state_dict'].items()])
        # weak_checkpoint['state_dict'] = OrderedDict(
        #     [(k.replace('FeatureRegression2', 'ThetaRegression2'), v) for k, v in weak_checkpoint['state_dict'].items()])
        # model_weak.load_state_dict(weak_checkpoint['state_dict'], strict=False)
        print('Load Rocco weak model successfully!')

    if args.cuda:
        model.cuda()
        model_weak.cuda()

    ''' Set watch dataset & evaluation metric '''
    if args.test_dataset == 'PF-WILLOW':
        TestDataSet = PFWILLOWDataset
        metric = 'pck'
    elif args.test_dataset == 'PF-PASCAL':
        TestDataSet = PFPASCALDataset
        metric = 'pck'
    elif args.test_dataset == 'Caltech-101':
        TestDataSet = CaltechDataset
        metric = 'area'
    elif args.test_dataset == 'TSS':
        TestDataSet = TSSDataset
        metric = 'flow'
    collate_fn = default_collate

    # Set path of csv file including image names (source and target) and annotation
    csv_file_watch, watch_dataset_path = get_dataset_csv(dataset_path=args.test_dataset_path, dataset=args.test_dataset, subset='watch')
    print(csv_file_watch)
    output_size = (args.image_size, args.image_size)
    normalize = NormalizeImageDict(['source_image', 'target_image'])
    # normalize = None
    dataset = TestDataSet(csv_file=csv_file_watch, dataset_path=watch_dataset_path, output_size=output_size, normalize=normalize)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=args.batch_size, shuffle=False, num_workers=4, collate_fn=collate_fn)

    ''' Test trained geometric matching model '''
    print('Test on {}'.format(args.test_dataset))
    # Set visualization
    vis = Visdom(env='vsWeakDual')
    # vis = Visdom()
    model.eval()
    model_weak.eval()
    with torch.no_grad():
        results, theta, theta_inver, _ = test_watch(model=model, metric=metric, dataset=dataset, dataloader=dataloader, dual=True, args=args)
        results_weak, theta_weak, theta_weak_inver, _ = test_watch(model=model_weak, metric=metric, dataset=dataset, dataloader=dataloader, dual=True, args=args)
        if args.test_dataset == 'PF-PASCAL' or args.test_dataset == 'PF-WILLOW':
            vis_pf(vis, dataloader, theta, theta_weak, theta_inver, theta_weak_inver, results, results_weak, args.test_dataset, use_cuda=args.cuda)
            # vis_pf_2(vis, dataloader, theta, theta_weak, theta_inver, theta_weak_inver, results, results_weak, args.test_dataset, use_cuda=args.cuda)
        elif args.test_dataset == 'Caltech-101':
            vis_caltech(vis, dataloader, theta, theta_weak, results, results_weak, args.test_dataset, use_cuda=args.cuda)
        elif args.test_dataset == 'TSS':
            vis_tss(vis, dataloader, theta, theta_weak, csv_file_watch, args.test_dataset, use_cuda=args.cuda)

    print('Done!')