from DrawingInterface import DrawingInterface

import pydiffvg
import torch
from torch.nn import functional as F
import skimage
import skimage.io
import random
import ttools.modules
import argparse
import math
import torchvision
import torchvision.transforms as transforms
import numpy as np
import PIL.Image

def rect_from_corners(p0, p1):
    x1, y1 = p0
    x2, y2 = p1
    pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    return pts

# canonical interpolation function, like https://p5js.org/reference/#/p5/map
def map_number(n, start1, stop1, start2, stop2):
  return ((n-start1)/(stop1-start1))*(stop2-start2)+start2;

def hex_from_corners(p0, p1):
    x1, y1 = p0
    x2, y2 = p1
    n  = 3.0
    # hxA = map_number(4, -n, n, x1, x2)
    # hxB = map_number(2, -n, n, x1, x2)
    # hxC = map_number(-2, -n, n, x1, x2)
    # hxD = map_number(-4, -n, n, x1, x2)
    # hyH = map_number(0, -n, n, y1, y2)
    # pts = [[hxA, hyH], [hxB, y1], [hxC, y1], [hxD, hyH], [hxC, y2], [hxB, y2]]
    hyA = map_number(4, -n, n, y1, y2)
    hyB = map_number(2, -n, n, y1, y2)
    hyC = map_number(-2, -n, n, y1, y2)
    hyD = map_number(-4, -n, n, y1, y2)
    hxH = map_number(0, -n, n, x1, x2)
    pts = [[hxH, hyA], [x1, hyB], [x1, hyC], [hxH, hyD], [x2, hyC], [x2, hyB]]
    return pts

class PixelDrawer(DrawingInterface):
    @staticmethod
    def add_settings(parser):
        parser.add_argument("--pixel_size", nargs=2, type=int, help="Pixel size (width height)", default=None, dest='pixel_size')
        parser.add_argument("--pixel_scale", type=float, help="Pixel scale", default=None, dest='pixel_scale')
        parser.add_argument("--pixel_type", type=str, help="rect, rectshift, hex, tri", default="rect", dest='pixel_type')
        parser.add_argument("--pixel_odd_check", type=bool, help="ensure offset grids are odd", default=True, dest='pixel_odd_check')
        return parser

    def __init__(self, settings):
        super(DrawingInterface, self).__init__()

        self.canvas_width = settings.size[0]
        self.canvas_height = settings.size[1]

        # current logic: assume 16x9, but check for 1x1 (all others must be provided explicitly)
        if settings.pixel_size is not None:
            self.num_cols, self.num_rows = settings.pixel_size
        elif self.canvas_width == self.canvas_height:
            self.num_cols, self.num_rows = [40, 40]
        else:
            self.num_cols, self.num_rows = [80, 45]

        # we can also "scale" pixels -- scaling "up" meaning fewer rows/cols, etc.
        if settings.pixel_scale is not None and settings.pixel_scale > 0:
            self.num_cols = int(self.num_cols / settings.pixel_scale)
            self.num_rows = int(self.num_rows / settings.pixel_scale)

        self.pixel_type = settings.pixel_type
        if settings.pixel_odd_check:
            if self.pixel_type == "hex" or self.pixel_type == "rectshift":
                if self.num_cols % 2 == 0:
                    self.num_cols = self.num_cols + 1
                if self.num_rows % 2 == 0:
                    self.num_rows = self.num_rows + 1

    def load_model(self, settings, device):
        # gamma = 1.0

        # Use GPU if available
        pydiffvg.set_use_gpu(torch.cuda.is_available())
        pydiffvg.set_device(device)
        self.device = device

    def get_opts(self):
        return self.opts

    def rand_init(self, toksX, toksY):
        self.init_from_tensor(None)

    def init_from_tensor(self, init_tensor):
        # print("----> SHAPE", self.num_rows, self.num_cols)
        canvas_width, canvas_height = self.canvas_width, self.canvas_height
        num_rows, num_cols = self.num_rows, self.num_cols
        cell_width = canvas_width / num_cols
        cell_height = canvas_height / num_rows

        tensor_cell_height = 0
        tensor_cell_width = 0
        if init_tensor is not None:
            tensor_shape = init_tensor.shape
            tensor_cell_width = tensor_shape[3] / num_cols
            tensor_cell_height = tensor_shape[2] / num_rows
            # print(tensor_shape, tensor_cell_width, tensor_cell_height)

        # Initialize Random Pixels
        shapes = []
        shape_groups = []
        colors = []
        for r in range(num_rows):
            tensor_cur_y = int(0.5 + r * tensor_cell_height)
            cur_y = r * cell_height
            num_cols_this_row = num_cols
            col_offset = 0
            if (self.pixel_type == "hex" or self.pixel_type == "rectshift") and r % 2 == 0:
                num_cols_this_row = num_cols - 1
                col_offset = 0.5
            for c in range(num_cols_this_row):
                tensor_cur_x =  (0.5 + (col_offset + c) * tensor_cell_width)
                cur_x = (col_offset + c) * cell_width
                if init_tensor is None:
                    cell_color = torch.tensor([random.random(), random.random(), random.random(), 1.0])
                else:
                    try:
                        t = (init_tensor[0] + 1.0) / 2.0
                        # t = init_tensor[0]
                        cell_color = torch.tensor([t[0][int(tensor_cur_y)][int(tensor_cur_x)], t[1][int(tensor_cur_y)][int(tensor_cur_x)], t[2][int(tensor_cur_y)][int(tensor_cur_x)], 1.0])
                    except BaseException as error:
                        print("WTF", error)
                        mono_color = random.random()
                        cell_color = torch.tensor([mono_color, mono_color, mono_color, 1.0])
                colors.append(cell_color)
                p0 = [cur_x, cur_y]
                p1 = [cur_x+cell_width, cur_y+cell_height]

                if self.pixel_type == "hex":
                    pts = hex_from_corners(p0, p1)
                else:
                    pts = rect_from_corners(p0, p1)
                pts = torch.tensor(pts, dtype=torch.float32).view(-1, 2)
                path = pydiffvg.Polygon(pts, True)

                # path = pydiffvg.Rect(p_min=torch.tensor(p0), p_max=torch.tensor(p1))
                shapes.append(path)
                path_group = pydiffvg.ShapeGroup(shape_ids = torch.tensor([len(shapes) - 1]), stroke_color = None, fill_color = cell_color)
                shape_groups.append(path_group)

        # Just some diffvg setup
        scene_args = pydiffvg.RenderFunction.serialize_scene(\
            canvas_width, canvas_height, shapes, shape_groups)
        render = pydiffvg.RenderFunction.apply
        img = render(canvas_width, canvas_height, 2, 2, 0, None, *scene_args)

        color_vars = []
        for group in shape_groups:
            group.fill_color.requires_grad = True
            color_vars.append(group.fill_color)

        self.color_vars = color_vars

        self.img = img
        self.shapes = shapes 
        self.shape_groups  = shape_groups

    def get_opts(self, decay_divisor=1):
        # Optimizers
        # points_optim = torch.optim.Adam(points_vars, lr=1.0)
        # width_optim = torch.optim.Adam(stroke_width_vars, lr=0.1)
        color_optim = torch.optim.Adam(self.color_vars, lr=0.03/decay_divisor)
        self.opts = [color_optim]
        return self.opts

    def reapply_from_tensor(self, new_tensor):
        # TODO
        pass

    def get_z_from_tensor(self, ref_tensor):
        return None

    def get_num_resolutions(self):
        # TODO
        return 5

    def synth(self, cur_iteration):
        if cur_iteration < 0:
            return self.img

        render = pydiffvg.RenderFunction.apply
        scene_args = pydiffvg.RenderFunction.serialize_scene(\
            self.canvas_width, self.canvas_height, self.shapes, self.shape_groups)
        img = render(self.canvas_width, self.canvas_height, 2, 2, cur_iteration, None, *scene_args)
        img_h, img_w = img.shape[0], img.shape[1]
        img = img[:, :, 3:4] * img[:, :, :3] + torch.ones(img.shape[0], img.shape[1], 3, device = self.device) * (1 - img[:, :, 3:4])
        img = img[:, :, :3]

        img = img.unsqueeze(0)
        img = img.permute(0, 3, 1, 2) # NHWC -> NCHW
        # if cur_iteration == 0:
        #     print("SHAPE", img.shape)

        self.img = img
        return img

    @torch.no_grad()
    def to_image(self):
        img = self.img.detach().cpu().numpy()[0]
        img = np.transpose(img, (1, 2, 0))
        img = np.clip(img, 0, 1)
        img = np.uint8(img * 255)
        pimg = PIL.Image.fromarray(img, mode="RGB")
        return pimg

    def clip_z(self):
        with torch.no_grad():
            for group in self.shape_groups:
                group.fill_color.data[:3].clamp_(0.0, 1.0)
                group.fill_color.data[3].clamp_(1.0, 1.0)

    def get_z(self):
        return None

    def get_z_copy(self):
        shape_groups_copy = []
        for group in self.shape_groups:
            group_copy = torch.clone(group.fill_color.data)
            shape_groups_copy.append(group_copy)
        return shape_groups_copy

    def set_z(self, new_z):
        l = len(new_z)
        for l in range(len(new_z)):
            active_group = self.shape_groups[l]
            new_group = new_z[l]
            active_group.fill_color.data.copy_(new_group)
        return None
