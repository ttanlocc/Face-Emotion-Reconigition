import warnings

import matplotlib.pyplot as plt
import mmcv
import numpy as np
import torch
from mmcv.parallel import collate, scatter
from mmcv.runner import load_checkpoint

from mmcls.datasets.pipelines import Compose
from mmcls.models import build_classifier

def convert2coarse_label(i:int):
    """The first four are negative"""
    if i <= 3:
        return i
    return i - 3


def init_model(config, checkpoint=None, device='cuda:0', options=None):
    """Initialize a classifier from config file.

    Args:
        config (str or :obj:`mmcv.Config`): Config file path or the config
            object.
        checkpoint (str, optional): Checkpoint path. If left as None, the model
            will not load any weights.
        options (dict): Options to override some settings in the used config.

    Returns:
        nn.Module: The constructed classifier.
    """
    if isinstance(config, str):
        config = mmcv.Config.fromfile(config)
    elif not isinstance(config, mmcv.Config):
        raise TypeError('config must be a filename or Config object, '
                        f'but got {type(config)}')
    if options is not None:
        config.merge_from_dict(options)
    config.model.pretrained = None
    config.model.extractor.pretrained = None
    config.model.vit.pretrained = None
    model = build_classifier(config.model)
    if checkpoint is not None:
        map_loc = 'cpu' if device == 'cpu' else None
        checkpoint = load_checkpoint(model, checkpoint, map_location=map_loc)
        class_loaded = False
        if 'meta' in checkpoint:
            if 'CLASSES' in checkpoint['meta']:
                model.CLASSES = checkpoint['meta']['CLASSES']
                class_loaded = True
        if not class_loaded:
            from mmcls.datasets.raf import FER_CLASSES
            model.CLASSES = FER_CLASSES
    model.cfg = config  # save the config in the model for convenience
    model.to(device)
    model.eval()
    return model


def inference_model(model, img):
    """Inference image(s) with the classifier.

    Args:
        model (nn.Module): The loaded classifier.
        img (str/ndarray): The image filename or loaded image.

    Returns:
        result (dict): The classification results that contains
            `class_name`, `pred_label` and `pred_score`.
    """
    cfg = model.cfg
    device = next(model.parameters()).device  # model device
    # build the data pipeline
    if isinstance(img, str):
        if cfg.data.test.pipeline[0]['type'] != 'LoadImageFromFile':
            cfg.data.test.pipeline.insert(0, dict(type='LoadImageFromFile'))
        data = dict(img_info=dict(filename=img), img_prefix=None)
    else:
        if cfg.data.test.pipeline[0]['type'] == 'LoadImageFromFile':
            cfg.data.test.pipeline.pop(0)
        data = dict(img=img)
    test_pipeline = Compose(cfg.data.test.pipeline)
    data = test_pipeline(data)
    data = collate([data], samples_per_gpu=1)
    if next(model.parameters()).is_cuda:
        # scatter to specified GPU
        data = scatter(data, [device])[0]

    # # forward the model
    # with torch.no_grad():
    #     scores = model(return_loss=False, **data)
    #     print(scores)
    #     pred_score = np.max(scores, axis=1)[0]
    #     pred_label = np.argmax(scores, axis=1)[0]
    #     print(f"predict label {np.argmax(scores, axis=1)} add convert {pred_label}" )
    #     result = {'pred_label': pred_label, 'pred_score': float(pred_score)}
    #     result['pred_class'] = model.CLASSES[result['pred_label']]
    # print(result)
    # return result

    # forward the model
    with torch.no_grad():
        scores = model(return_loss=False, **data)
        results = []
        pred_score = np.max(scores, axis=1)[0]
        pred_label = np.argmax(scores, axis=1)[0]
        for index, score in enumerate(scores[0]):
            result = {'class': model.CLASSES[index], 'score': float(score/pred_score)}
            results.append(result)
        # print(results)
        results.append({'pred_class': model.CLASSES[pred_label], 'pred_score': float(pred_score)})
    return results
