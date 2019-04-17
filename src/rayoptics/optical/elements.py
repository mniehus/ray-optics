#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright © 2018 Michael J. Hayford
""" Module for element modeling

.. Created on Sun Jan 28 16:27:01 2018

.. codeauthor: Michael J. Hayford
"""

import logging

import numpy as np

import rayoptics.util.rgbtable as rgbt
import rayoptics.optical.thinlens as thinlens
from rayoptics.optical.profiles import Spherical, Conic
from rayoptics.optical.surface import Surface
from rayoptics.optical.gap import Gap
from rayoptics.optical.medium import Glass, glass_decode
import opticalglass.glasspolygons as gp


def create_thinlens(power=0., indx=1.5):
    tl = thinlens.ThinLens(power=power)
    tle = ThinElement(tl)
    return tl, tle


def create_mirror(c=0.0, r=None, cc=0.0, ec=None):
    if r:
        cv = 1.0/r
    else:
        cv = c

    if ec:
        k = ec - 1.0
    else:
        k = cc

    if k == 0.0:
        profile = Spherical(c=cv)
    else:
        profile = Conic(c=cv, cc=k)

    m = Surface(profile=profile, refract_mode='REFL')
    me = Mirror(m)
    return m, me


def create_lens(power=0., bending=0., th=0., sd=1., med=None):
    s1 = Surface()
    s2 = Surface()
    if med is None:
        med = Glass()
    g = Gap(t=th, med=med)
    le = Element(s1, s2, g, sd=sd)
    return (s1, s2, g), le


class Element():
    clut = rgbt.RGBTable(filename='red_blue64.csv',
                         data_range=[10.0, 100.])

    def __init__(self, s1, s2, g, tfrm=None, idx=0, idx2=1, sd=1.,
                 label='Lens'):
        self.label = label
        if tfrm is not None:
            self.tfrm = tfrm
        else:
            self.trfm = (np.identity(3), np.array([0., 0., 0.]))
        self.s1 = s1
        self.s1_indx = idx
        self.s2 = s2
        self.s2_indx = idx2
        self.g = g
        self._sd = sd
        self.flat1 = None
        self.flat2 = None
        self.render_color = self.calc_render_color()

    @property
    def sd(self):
        return self._sd

    @sd.setter
    def sd(self, semidiam):
        self._sd = semidiam
        self.edge_extent = (-semidiam, semidiam)

    def __json_encode__(self):
        attrs = dict(vars(self))
        del attrs['tfrm']
        del attrs['s1']
        del attrs['s2']
        del attrs['g']
        del attrs['handles']
        del attrs['actions']
        return attrs

    def __str__(self):
        fmt = 'Element: {!r}, {!r}, t={:.4f}, sd={:.4f}, glass: {}'
        return fmt.format(self.s1.profile, self.s2.profile, self.g.thi,
                          self.sd, self.g.medium.name())

    def sync_to_restore(self, surfs, gaps, tfrms):
        # when restoring, we want to use the stored indices to look up the
        # new object instances
        self.tfrm = tfrms[self.s1_indx]
        self.s1 = surfs[self.s1_indx]
        self.g = gaps[self.s1_indx]
        self.s2 = surfs[self.s2_indx]

    def sync_to_update(self, seq_model):
        # when updating, we want to use the stored object instances to get the
        # current indices into the interface list (e.g. to handle insertion and
        # deletion of interfaces)
        self.s1_indx = seq_model.ifcs.index(self.s1)
        self.s2_indx = seq_model.ifcs.index(self.s2)
        self.render_color = self.calc_render_color()

    def reference_interface(self):
        return self.s1

    def update_size(self):
        extents = np.union1d(self.s1.get_y_aperture_extent(),
                             self.s2.get_y_aperture_extent())
        self.edge_extent = (extents[0], extents[-1])
        self.sd = max(self.s1.surface_od(), self.s2.surface_od())
        return self.sd

    def calc_render_color(self):
        try:
            gc = float(self.g.medium.glass_code())
        except AttributeError:
            return (255, 255, 255)  # white
        else:
            # set element color based on V-number
            indx, vnbr = glass_decode(gc)
            dsg, rgb = gp.find_glass_designation(indx, vnbr)
#            rgb = Element.clut.get_color(vnbr)
            return rgb

    def compute_flat(self, s):
        ca = s.surface_od()
        if (1.0 - ca/self.sd) >= 0.05:
            flat = ca
        else:
            flat = None
        return flat

    def extent(self):
        if hasattr(self, 'edge_extent'):
            return self.edge_extent
        else:
            return (-self.sd, self.sd)

    def render_shape(self):
        if self.s1.profile_cv() < 0.0:
            self.flat1 = self.compute_flat(self.s1)
        poly = self.s1.full_profile(self.extent(), self.flat1)
        if self.s2.profile_cv() > 0.0:
            self.flat2 = self.compute_flat(self.s2)
        poly2 = self.s2.full_profile(self.extent(), self.flat2, -1)
        for p in poly2:
            p[0] += self.g.thi
        poly += poly2
        poly.append(poly[0])
        return poly

    def render_handles(self, opt_model):
        self.handles = {}
        ifcs_gbl_tfrms = opt_model.seq_model.gbl_tfrms

        shape = self.render_shape()
        self.handles['shape'] = (shape, self.tfrm, 'polygon')

        extent = self.extent()
        if self.flat1 is not None:
            extent_s1 = self.flat1,
        else:
            extent_s1 = extent
        poly_s1 = self.s1.full_profile(extent_s1, None)
        self.handles['s1_profile'] = (poly_s1, ifcs_gbl_tfrms[self.s1_indx],
                                      'polyline')

        if self.flat2 is not None:
            extent_s2 = self.flat2,
        else:
            extent_s2 = extent
        poly_s2 = self.s2.full_profile(extent_s2, None, -1)
        self.handles['s2_profile'] = (poly_s2, ifcs_gbl_tfrms[self.s2_indx],
                                      'polyline')

        poly_sd_upr = []
        poly_sd_upr.append([poly_s1[-1][0], extent[1]])
        poly_sd_upr.append([poly_s2[0][0]+self.g.thi, extent[1]])
        self.handles['sd_upr'] = (poly_sd_upr, self.tfrm, 'polyline')

        poly_sd_lwr = []
        poly_sd_lwr.append([poly_s2[-1][0]+self.g.thi, extent[0]])
        poly_sd_lwr.append([poly_s1[0][0], extent[0]])
        self.handles['sd_lwr'] = (poly_sd_lwr, self.tfrm, 'polyline')

        return self.handles

    def handle_actions(self):
        self.actions = {}

        shape_actions = {}
        shape_actions['x'] = AttrAction(self.g, 'thi')
        shape_actions['y'] = AttrAction(self, 'sd')
        self.actions['shape'] = shape_actions

        s1_prof_actions = {}
        s1_prof_actions['pt'] = SagAction(self.s1)
        self.actions['s1_profile'] = s1_prof_actions

        s2_prof_actions = {}
        s2_prof_actions['pt'] = SagAction(self.s2)
        self.actions['s2_profile'] = s2_prof_actions

        sd_upr_action = {}
        sd_upr_action['y'] = AttrAction(self, 'sd')
        self.actions['sd_upr'] = sd_upr_action

        sd_lwr_action = {}
        sd_lwr_action['y'] = AttrAction(self, 'sd')
        self.actions['sd_lwr'] = sd_lwr_action

        return self.actions


class Action():

    def __init__(self, getf, setf):
        self.getf = getf
        self.setf = setf
        self.cur_value = None
        self.new_value = None
        self.actions = {}

        def on_select(fig, event):
            self.cur_value = getf()
            return self.cur_value
        self.actions['press'] = on_select

        def on_edit(fig, event, value):
            setf(value)
            fig.refresh_gui()
        self.actions['drag'] = on_edit

        def on_release(fig, event):
            self.new_value = getf()
            fig.refresh_gui()
        self.actions['release'] = on_release


class SagAction():

    def __init__(self, surf):
        self.surf = surf
        self.cur_value = None
        self.new_value = None
        self.actions = {}

        def on_select(fig, event):
            self.cur_value = self.surf.z_sag((event.x, event.ydata))
#            print('SagAction.on_select:', self.cur_value)
            return self.cur_value
        self.actions['press'] = on_select

        def on_edit(fig, event, value):
            self.surf.set_z_sag(value)
#            cv = self.surf.calc_cv_from_zsag(value)
#            print('SagAction.on_edit (x, y, cv):', value, cv)
            fig.refresh_gui()
        self.actions['drag'] = on_edit

        def on_release(fig, event):
            self.new_value = self.surf.z_sag((event.x, event.ydata))
            fig.refresh_gui()
        self.actions['release'] = on_release


class AttrAction():

    def __init__(self, obj, attr):
        self.object = obj
        self.attr = attr
        self.cur_value = getattr(self.object, self.attr, None)
        self.new_value = None
        self.actions = {}

        def on_select(fig, event):
            self.cur_value = getattr(self.object, self.attr, None)
#            print('AttrAction.on_select:', self.attr, self.cur_value)
            return self.cur_value
        self.actions['press'] = on_select

        def on_edit(fig, event, delta_value):
            setattr(self.object, self.attr, self.cur_value+delta_value)
#            print('AttrAction.on_edit:', self.attr, self.cur_value+delta_value)
            fig.refresh_gui()
        self.actions['drag'] = on_edit

        def on_release(fig, event):
            self.new_value = getattr(self.object, self.attr, None)
            fig.refresh_gui()
        self.actions['release'] = on_release


class Mirror():
    def __init__(self, ifc, tfrm=None, idx=0, sd=1., thi=None, z_dir=1.0,
                 label='Mirror'):
        self.label = label
#        self.render_color = (192, 192, 192, 112)
        self.render_color = (158, 158, 158, 64)
#        self.render_color = (64, 64, 64, 64)
        if tfrm is not None:
            self.tfrm = tfrm
        else:
            self.trfm = (np.identity(3), np.array([0., 0., 0.]))
        self.s = ifc
        self.s_indx = idx
        self.z_dir = z_dir
        self.sd = sd
        self.flat = None
        self.thi = thi

    def get_thi(self):
        thi = self.thi
        if self.thi is None:
            thi = 0.05*self.sd
        return thi

    def __json_encode__(self):
        attrs = dict(vars(self))
        del attrs['tfrm']
        del attrs['s']
        del attrs['handles']
        del attrs['actions']
        return attrs

    def __str__(self):
        thi = self.get_thi()
        fmt = 'Mirror: {!r}, t={:.4f}, sd={:.4f}'
        return fmt.format(self.s.profile, thi, self.sd)

    def sync_to_restore(self, surfs, gaps, tfrms):
        self.tfrm = tfrms[self.s_indx]
        self.s = surfs[self.s_indx]

    def reference_interface(self):
        return self.s

    def sync_to_update(self, seq_model):
        self.s_indx = seq_model.ifcs.index(self.s)

    def update_size(self):
        self.edge_extent = self.s.get_y_aperture_extent()
        self.sd = self.s.surface_od()
        return self.sd

    def extent(self):
        if hasattr(self, 'edge_extent'):
            return self.edge_extent
        else:
            self.edge_extent = self.s.get_y_aperture_extent()
            return self.edge_extent

    def render_shape(self):
        poly = self.s.full_profile(self.extent(), self.flat)
        poly2 = self.s.full_profile(self.extent(), self.flat, -1)

        thi = self.get_thi()
        offset = thi*self.z_dir

        for p in poly2:
            p[0] += offset
        poly += poly2
        poly.append(poly[0])
        return poly

    def render_handles(self, opt_model):
        self.handles = {}
        ifcs_gbl_tfrms = opt_model.seq_model.gbl_tfrms

        self.handles['shape'] = (self.render_shape(), self.tfrm, 'polygon')

        poly = self.s.full_profile(self.extent(), None)
        self.handles['s_profile'] = (poly, ifcs_gbl_tfrms[self.s_indx],
                                     'polyline')

        thi = self.get_thi()
        offset = thi*self.z_dir

        poly_sd_upr = []
        poly_sd_upr.append(poly[-1])
        poly_sd_upr.append([poly[-1][0]+offset, poly[-1][1]])
        self.handles['sd_upr'] = (poly_sd_upr, self.tfrm, 'polyline')

        poly_sd_lwr = []
        poly_sd_lwr.append(poly[0])
        poly_sd_lwr.append([poly[0][0]+offset, poly[0][1]])
        self.handles['sd_lwr'] = (poly_sd_lwr, self.tfrm, 'polyline')

        return self.handles

    def handle_actions(self):
        self.actions = {}

        shape_actions = {}
        shape_actions['pt'] = SagAction(self.s)
        self.actions['shape'] = shape_actions

        s_prof_actions = {}
        s_prof_actions['pt'] = SagAction(self.s)
        self.actions['s_profile'] = s_prof_actions

        sd_upr_action = {}
        sd_upr_action['y'] = AttrAction(self, 'edge_extent[1]')
        self.actions['sd_upr'] = sd_upr_action

        sd_lwr_action = {}
        sd_lwr_action['y'] = AttrAction(self, 'edge_extent[0]')
        self.actions['sd_lwr'] = sd_lwr_action

        return self.actions


class ThinElement():
    def __init__(self, ifc, tfrm=None, idx=0, label='ThinLens'):
        self.label = label
        self.render_color = (192, 192, 192)
        if tfrm is not None:
            self.tfrm = tfrm
        else:
            self.trfm = (np.identity(3), np.array([0., 0., 0.]))
        self.intrfc = ifc
        self.intrfc_indx = idx
        self.sd = ifc.od

    def __json_encode__(self):
        attrs = dict(vars(self))
        del attrs['tfrm']
        del attrs['intrfc']
        del attrs['handles']
        del attrs['actions']
        return attrs

    def __str__(self):
        return str(self.intrfc)

    def sync_to_restore(self, surfs, gaps, tfrms):
        self.tfrm = tfrms[self.intrfc_indx]
        self.intrfc = surfs[self.intrfc_indx]

    def reference_interface(self):
        return self.intrfc

    def sync_to_update(self, seq_model):
        self.intrfc_indx = seq_model.ifcs.index(self.intrfc)

    def update_size(self):
        self.sd = self.intrfc.surface_od()
        return self.sd

    def render_shape(self):
        poly = self.intrfc.full_profile((-self.sd, self.sd))
        return poly

    def render_handles(self, opt_model):
        self.handles = {}
        shape = self.render_shape()
        self.handles['shape'] = (shape, self.tfrm, 'polygon')
        return self.handles

    def handle_actions(self):
        self.actions = {}
        return self.actions

class ElementModel:

    def __init__(self, opt_model):
        self.opt_model = opt_model
        self.elements = []

    def reset(self):
        self.__init__()

    def __json_encode__(self):
        attrs = dict(vars(self))
        del attrs['opt_model']
        return attrs

    def elements_from_sequence(self, seq_model):
        """ generate an element list from a sequential model """

        # if there are elements in the list already, just return
        if len(self.elements) > 0:
            return

        num_elements = 0
        tfrms = seq_model.compute_global_coords(1)
        for i, g in enumerate(seq_model.gaps):
            if isinstance(seq_model.ifcs[i], thinlens.ThinLens):
                te = ThinElement(seq_model.ifcs[i], tfrm=tfrms[i], idx=i)
                te.label = 'E' + str(++num_elements)
                self.elements.append(te)
                continue

            z_dir = seq_model.z_dir[i]
            if g.medium.name().lower() == 'air':
                # close off element
                s2 = seq_model.ifcs[i+1]
                if s2.refract_mode is 'REFL':
                    tfrm = tfrms[i+1]
                    sd = s2.surface_od()
                    m = Mirror(s2, sd=sd, tfrm=tfrm, idx=i+1, z_dir=z_dir)
                    m.label = 'E' + str(++num_elements)
                    self.elements.append(m)
            else:
                tfrm = tfrms[i]
                s1 = seq_model.ifcs[i]
                s2 = seq_model.ifcs[i+1]
                sd = max(s1.surface_od(), s2.surface_od())
                e = Element(s1, s2, g, sd=sd, tfrm=tfrm, idx=i, idx2=i+1)
                e.label = 'E' + str(++num_elements)
                self.elements.append(e)

    def sync_to_restore(self, opt_model):
        self.opt_model = opt_model
        seq_model = opt_model.seq_model
        surfs = seq_model.ifcs
        gaps = seq_model.gaps
        tfrms = seq_model.compute_global_coords(1)
        for e in self.elements:
            e.sync_to_restore(surfs, gaps, tfrms)

    def update_model(self):
        seq_model = self.opt_model.seq_model
        tfrms = seq_model.compute_global_coords(1)
        for e in self.elements:
            e.update_size()
            e.sync_to_update(seq_model)
            intrfc = e.reference_interface()
            try:
                i = seq_model.ifcs.index(intrfc)
            except ValueError:
                print("Interface {} not found".format(intrfc.lbl))
            else:
                e.tfrm = tfrms[i]

    def get_num_elements(self):
        return len(self.elements)

    def list_elements(self):
        for i, ele in enumerate(self.elements):
            print(str(ele))
