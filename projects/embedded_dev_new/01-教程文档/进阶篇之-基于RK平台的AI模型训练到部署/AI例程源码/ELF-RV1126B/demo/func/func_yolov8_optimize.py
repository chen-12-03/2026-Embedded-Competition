# 以下代码改自https://github.com/rockchip-linux/rknn-toolkit2/tree/master/examples/onnx/yolov5
import cv2
import numpy as np
from copy import copy
OBJ_THRESH, NMS_THRESH, IMG_SIZE = 0.25, 0.45, 640
out_win = "output_style_full_screen"
CLASSES = ("person", "bicycle", "car","motorbike","aeroplane","bus","train","truck","boat","traffic light",
           "fire hydrant","stop sign","parking meter","bench","bird","cat","dog ","horse","sheep","cow","elephant",
           "bear","zebra ","giraffe","backpack","umbrella","handbag","tie","suitcase","frisbee","skis","snowboard","sports ball","kite",
           "baseball bat","baseball glove","skateboard","surfboard","tennis racket","bottle","wine glass","cup","fork","knife",
           "spoon","bowl","banana","apple","sandwich","orange","broccoli","carrot","hot dog","pizza","donut","cake","chair","sofa",
           "pottedplant","bed","diningtable","toilet","tvmonitor","laptop","mouse","remote","keyboard","cell phone","microwave",
           "oven","toaster","sink","refrigerator","book","clock","vase","scissors","teddy bear","hair drier", "toothbrush")

INTERESTED_CLASSES = ["backpack","umbrella","handbag","tie","sports ball","bottle","wine glass","cup","fork",
                      "knife","spoon","bowl","banana","apple","sandwich","orange","broccoli","carrot","hot dog",
                      "pizza","donut","cake","book","scissors","teddy bear","hair drier", "toothbrush"]



CLASS_INDICES = {cls: idx for idx, cls in enumerate(CLASSES)}
INTERESTED_CLASS_INDICES = [CLASS_INDICES[cls] for cls in INTERESTED_CLASSES]
def filter_boxes(boxes, box_confidences, box_class_probs):
    """Filter boxes with object threshold.
    """
    box_confidences = box_confidences.reshape(-1)
    candidate, class_num = box_class_probs.shape

    class_max_score = np.max(box_class_probs, axis=-1)
    classes = np.argmax(box_class_probs, axis=-1)

    _class_pos = np.where(class_max_score * box_confidences >= OBJ_THRESH)
    scores = (class_max_score * box_confidences)[_class_pos]

    boxes = boxes[_class_pos]
    classes = classes[_class_pos]

    return boxes, classes, scores


def nms_boxes(boxes, scores):
    """Suppress non-maximal boxes.
    # Returns
        keep: ndarray, index of effective boxes.
    """
    x = boxes[:, 0]
    y = boxes[:, 1]
    w = boxes[:, 2] - boxes[:, 0]
    h = boxes[:, 3] - boxes[:, 1]

    areas = w * h
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)

        xx1 = np.maximum(x[i], x[order[1:]])
        yy1 = np.maximum(y[i], y[order[1:]])
        xx2 = np.minimum(x[i] + w[i], x[order[1:]] + w[order[1:]])
        yy2 = np.minimum(y[i] + h[i], y[order[1:]] + h[order[1:]])

        w1 = np.maximum(0.0, xx2 - xx1 + 0.00001)
        h1 = np.maximum(0.0, yy2 - yy1 + 0.00001)
        inter = w1 * h1

        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        inds = np.where(ovr <= NMS_THRESH)[0]
        order = order[inds + 1]
    keep = np.array(keep)
    return keep


# def dfl(position):
#     # Distribution Focal Loss (DFL)
#     import torch
#     x = torch.tensor(position)
#     n,c,h,w = x.shape
#     p_num = 4
#     mc = c//p_num
#     y = x.reshape(n,p_num,mc,h,w)
#     y = y.softmax(2)
#     acc_metrix = torch.tensor(range(mc)).float().reshape(1,1,mc,1,1)
#     y = (y*acc_metrix).sum(2)
#     return y.numpy()

# def dfl(position):
#     # Distribution Focal Loss (DFL)
#     n, c, h, w = position.shape
#     p_num = 4
#     mc = c // p_num
#     y = position.reshape(n, p_num, mc, h, w)
#     exp_y = np.exp(y)
#     y = exp_y / np.sum(exp_y, axis=2, keepdims=True)
#     acc_metrix = np.arange(mc).reshape(1, 1, mc, 1, 1).astype(float)
#     y = (y * acc_metrix).sum(2)
#     return y

def dfl(position):
    # Distribution Focal Loss (DFL)
    # x = np.array(position)
    n, c, h, w = position.shape
    p_num = 4
    mc = c // p_num
    y = position.reshape(n, p_num, mc, h, w)

    # Vectorized softmax
    e_y = np.exp(y - np.max(y, axis=2, keepdims=True))  # subtract max for numerical stability
    y = e_y / np.sum(e_y, axis=2, keepdims=True)

    acc_metrix = np.arange(mc).reshape(1, 1, mc, 1, 1)
    y = (y * acc_metrix).sum(2)
    return y


def box_process(position):
    grid_h, grid_w = position.shape[2:4]
    col, row = np.meshgrid(np.arange(0, grid_w), np.arange(0, grid_h))
    col = col.reshape(1, 1, grid_h, grid_w)
    row = row.reshape(1, 1, grid_h, grid_w)
    grid = np.concatenate((col, row), axis=1)
    stride = np.array([IMG_SIZE // grid_h, IMG_SIZE // grid_w]).reshape(1, 2, 1, 1)

    position = dfl(position)
    box_xy = grid + 0.5 - position[:, 0:2, :, :]
    box_xy2 = grid + 0.5 + position[:, 2:4, :, :]
    xyxy = np.concatenate((box_xy * stride, box_xy2 * stride), axis=1)

    return xyxy


def yolov8_post_process(input_data):
    boxes, scores, classes_conf = [], [], []
    defualt_branch = 3
    pair_per_branch = len(input_data) // defualt_branch
    # Python 忽略 score_sum 输出
    for i in range(defualt_branch):
        boxes.append(box_process(input_data[pair_per_branch * i]))
        classes_conf.append(input_data[pair_per_branch * i + 1])
        scores.append(np.ones_like(input_data[pair_per_branch * i + 1][:, :1, :, :], dtype=np.float32))

    def sp_flatten(_in):
        ch = _in.shape[1]
        _in = _in.transpose(0, 2, 3, 1)
        return _in.reshape(-1, ch)

    boxes = [sp_flatten(_v) for _v in boxes]
    classes_conf = [sp_flatten(_v) for _v in classes_conf]
    scores = [sp_flatten(_v) for _v in scores]

    boxes = np.concatenate(boxes)
    classes_conf = np.concatenate(classes_conf)
    scores = np.concatenate(scores)

    # filter according to threshold
    boxes, classes, scores = filter_boxes(boxes, scores, classes_conf)

    # nms
    nboxes, nclasses, nscores = [], [], []
    for c in set(classes):
        inds = np.where(classes == c)
        b = boxes[inds]
        c = classes[inds]
        s = scores[inds]
        keep = nms_boxes(b, s)

        if len(keep) != 0:
            nboxes.append(b[keep])
            nclasses.append(c[keep])
            nscores.append(s[keep])

    if not nclasses and not nscores:
        return None, None, None

    boxes = np.concatenate(nboxes)
    classes = np.concatenate(nclasses)
    scores = np.concatenate(nscores)

    return boxes, classes, scores

def draw_box_corner(draw_img, top, left, right, bottom, length, corner_color):
    # Top Left
    cv2.line(draw_img, (top, left), (top + length, left), corner_color, thickness=3)
    cv2.line(draw_img, (top, left), (top, left + length), corner_color, thickness=3)
    # Top Right
    cv2.line(draw_img, (right, left), (right - length, left), corner_color, thickness=3)
    cv2.line(draw_img, (right, left), (right, left + length), corner_color, thickness=3)
    # Bottom Left
    cv2.line(draw_img, (top, bottom), (top + length, bottom), corner_color, thickness=3)
    cv2.line(draw_img, (top, bottom), (top, bottom - length), corner_color, thickness=3)
    # Bottom Right
    cv2.line(draw_img, (right, bottom), (right - length, bottom), corner_color, thickness=3)
    cv2.line(draw_img, (right, bottom), (right, bottom - length), corner_color, thickness=3)
def draw_label_type(draw_img, top, left, CLASSES, label_color):
    label = str(CLASSES)
    labelSize = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1, 6)[0]

    # 计算文本边界框的位置
    if left - labelSize[1] - 3 < 0:  # 如果标签在图像左侧放不下
        # 在标签右侧绘制背景框和文本
        box_coords = (top, left + 5, top + labelSize[0], left + labelSize[1] + 3)
        text_pos = (top, left + labelSize[0] + 3)  # 文本放置在背景框右侧
    else:
        # 在标签左侧绘制背景框和文本
        box_coords = (top, left - labelSize[1] - 3, top + labelSize[0], left - 3)
        text_pos = (top, left - 3)  # 文本放置在背景框左侧

    # 绘制背景框
    cv2.rectangle(draw_img, box_coords[0:2], box_coords[2:4], color=label_color, thickness=-1)

    # 在背景框上绘制文本
    cv2.putText(draw_img, label, text_pos, cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), thickness=2)


# def draw(image, boxes, scores, classes, ratio, padding):
#     for box, score, cl in zip(boxes, scores, classes):
#         top, left, right, bottom = box
#
#         top = (top - padding[0]) / ratio[0]
#         left = (left - padding[1]) / ratio[1]
#         right = (right - padding[0]) / ratio[0]
#         bottom = (bottom - padding[1]) / ratio[1]
#         # print('class: {}, score: {}'.format(CLASSES[cl], score))
#         # print('box coordinate left,top,right,down: [{}, {}, {}, {}]'.format(top, left, right, bottom))
#         top = int(top)
#         left = int(left)
#
#         cv2.rectangle(image, (top, left), (int(right), int(bottom)), (255, 0, 0), 2)
#         cv2.putText(image, '{0} {1:.2f}'.format(CLASSES[cl], score),
#                     (top, left - 6),
#                     cv2.FONT_HERSHEY_SIMPLEX,
#                     0.6, (0, 0, 255), 2)

def draw(image, boxes, scores, classes, ratio, padding):
    for box, score, cl in zip(boxes, scores, classes):
            top, left, right, bottom = box

            top = int((top - padding[0]) / ratio[0])
            left = int((left - padding[1]) / ratio[1])
            right = int((right - padding[0]) / ratio[0])
            bottom = int((bottom - padding[1]) / ratio[1])

            cv2.rectangle(image, (top,left), (right, bottom), (255,0,255), 2)
            draw_box_corner(image, top, left, right, bottom, 15, (0, 255, 0))
            draw_label_type(image, top, left,CLASSES[cl], (255,0,255))



def letterbox(im, new_shape=(640, 640), color=(0, 0, 0)):
    shape = im.shape[:2]  # current shape [height, width]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])

    ratio = r, r  # width, height ratios
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - \
             new_unpad[1]  # wh padding

    dw /= 2  # divide padding into 2 sides
    dh /= 2

    if shape[::-1] != new_unpad:  # resize——
        im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im, top, bottom, left, right,
                            cv2.BORDER_CONSTANT, value=color)  # add border
    # return im
    return im, ratio, (left, top)


def myFunc(rknn_lite, IMG):
    IMG2 = cv2.cvtColor(IMG, cv2.COLOR_BGR2RGB)
    # 等比例缩放
    IMG2, ratio, padding = letterbox(IMG2)
    # 强制放缩
    # IMG2 = cv2.resize(IMG, (IMG_SIZE, IMG_SIZE))
    IMG2 = np.expand_dims(IMG2, 0)

    outputs = rknn_lite.inference(inputs=[IMG2], data_format=['nhwc'])

    # print("oups1",len(outputs))
    # print("oups2",outputs[0].shape)

    boxes, classes, scores = yolov8_post_process(outputs)

    if boxes is not None:
        draw(IMG, boxes, scores, classes, ratio, padding)

    return IMG

