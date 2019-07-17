import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models
import numpy as np
import os

from geometric_matching.gm_model.geometric_matching import GeometricMatching
from geometric_matching.gm_model.feature_correlation import FeatureCorrelation
from geometric_matching.gm_model.theta_regression import ThetaRegression
from geometric_matching.gm_model.feature_extraction import FeatureExtraction
# from geometric_matching.model.feature_extraction_2 import FeatureExtraction_2
from geometric_matching.gm_model.object_select import ObjectSelect
from geometric_matching.gm_model.feature_crop import FeatureCrop
from geometric_matching.geotnf.affine_theta import AffineTheta
from geometric_matching.geotnf.transformation import GeometricTnf

from lib.model.faster_rcnn.vgg16 import vgg16
from lib.model.faster_rcnn.resnet import resnet

# The entire architecture of the model
class GeometricMatchingAff(GeometricMatching):
    """
    Predict geometric transformation parameters (TPS) between two images

    (1) Directly train with warped image pair; or
    (2) Fine-tune on pre-trained GeometricMatching model (TPS) with warped image pair

    image pair: source image: source image is warped by affine parameters computed by coordinates of object bounding box
    predicted by faster-rcnn
    target image: target image
    """
    def __init__(self, output_dim=6, dataset_classes=None, class_agnostic=False, feature_extraction_cnn='resnet101',
                 feature_extraction_last_layer='', return_correlation=False, fr_feature_size=15, fr_kernel_sizes=[7, 5],
                 fr_channels=[128, 64], normalize_features=True, normalize_matches=True, batch_normalization=True,
                 train_fe=False, use_cuda=True, pretrained=True, thresh=0.05, max_per_image=50, crop_layer=None,
                 return_box=False):
        super().__init__(output_dim=output_dim, feature_extraction_cnn=feature_extraction_cnn,
                         feature_extraction_last_layer=feature_extraction_last_layer,
                         return_correlation=return_correlation, fr_feature_size=fr_feature_size,
                         fr_kernel_sizes=fr_kernel_sizes, fr_channels=fr_channels,
                         normalize_features=normalize_features, normalize_matches=normalize_matches,
                         batch_normalization=batch_normalization, train_fe=train_fe, use_cuda=use_cuda,
                         pretrained=pretrained)
        self.AffTheta = AffineTheta(use_cuda=self.use_cuda)
        self.AffTnf = GeometricTnf(geometric_model='affine', use_cuda=self.use_cuda)
        self.crop_layer = crop_layer
        self.return_box = return_box

        # Object detection networks
        if feature_extraction_cnn == 'vgg16':
            self.FasterRCNN = vgg16(dataset_classes, use_pytorch=False, use_caffe=False, class_agnostic=class_agnostic)
        elif feature_extraction_cnn == 'resnet101':
            self.FasterRCNN = resnet(dataset_classes, 101, use_pytorch=False, use_caffe=False, class_agnostic=class_agnostic)
        # self.FasterRCNN = vgg16(classes=dataset_classes, pretrained=False, class_agnostic=class_agnostic)
        self.FasterRCNN.create_architecture()

        # Select salient object in image
        self.ObjectSelect = ObjectSelect(thresh=thresh, max_per_image=max_per_image)

    def forward(self, batch):
        # Object detection
        box_info_A = self.FasterRCNN(im_data=batch['source_im'], im_info=batch['source_im_info'], gt_boxes=batch['source_gt_boxes'], num_boxes=batch['source_num_boxes'])[0:3]
        box_info_B = self.FasterRCNN(im_data=batch['target_im'], im_info=batch['target_im_info'], gt_boxes=batch['target_gt_boxes'], num_boxes=batch['target_num_boxes'])[0:3]
        box_A, box_B = self.ObjectSelect(box_info_A=box_info_A, im_info_A=batch['source_im_info'], box_info_B=box_info_B, im_info_B=batch['target_im_info'])

        # Warp source image with affine parameters
        theta_aff_det = self.AffTheta(boxes_s=box_A, boxes_t=box_B)
        source_image_warp = self.AffTnf(image_batch=batch['source_image'], theta_batch=theta_aff_det)

        feature_A_warp = self.FeatureExtraction(source_image_warp)
        feature_B = self.FeatureExtraction(batch['target_image'])

        correlation = self.FeatureCorrelation(feature_A_warp, feature_B)

        theta_aff = self.ThetaRegression(correlation)

        if not self.return_correlation:
            if not self.return_box:
                return theta_aff, theta_aff_det
            else:
                return theta_aff, theta_aff_det, box_A, box_B
        else:
            return theta_aff, theta_aff_det, correlation