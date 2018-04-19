#!/usr/bin/env python3
############################################################
# Program is part of PySAR                                 #
# Copyright(c) 2017, Zhang Yunjun                          #
# Author:  Zhang Yunjun, 2017                              #
############################################################


import os
import sys
import time
import argparse
import warnings
import numpy as np
from pysar.utils import readfile, writefile, utils as ut
from pysar.objects.resample import resample

######################################################################################
TEMPLATE = """template:
pysar.geocode              = auto  #[yes / no], auto for yes
pysar.geocode.SNWE         = auto  #[-1.2,0.5,-92,-91 / no ], auto for no, output coverage in S N W E in degree 
pysar.geocode.latStep      = auto  #[0.0-90.0 / None], auto for None, output resolution in degree
pysar.geocode.lonStep      = auto  #[0.0-180.0 / None], auto for None - calculate from lookup file
pysar.geocode.interpMethod = auto  #[nearest], auto for nearest, interpolation method
pysar.geocode.fillValue    = auto  #[np.nan, 0, ...], auto for np.nan, fill value for outliers.
"""

EXAMPLE = """example:
  radar2geo.py velocity.h5
  radar2geo.py velocity.h5 -b -0.5 -0.25 -91.3 -91.1

  radar2geo.py  velocity.h5 temporalCoherence.h5 timeseries_ECMWF_demErr_refDate.h5
  radar2geo.py  velocity.h5 temporalCoherence.h5 timeseries_ECMWF_demErr_refDate.h5 -t pysarApp_template.txt

  radar2geo.py  101120-110220.unw   -l geomap_4rlks.trans
  radar2geo.py  velocity.h5         -l sim_150911-150922.UTM_TO_RDC
  radar2geo.py  coherence.h5        -l geometryRadar.h5   --lalo-step 0.0003333
  radar2geo.py  unwrapIfgram.h5     -l geometryRadar.h5   --lalo-step demGeo_tight.h5
"""


def create_parser():
    parser = argparse.ArgumentParser(description='Resample radar coded files into geo coordinates',
                                     formatter_class=argparse.RawTextHelpFormatter,
                                     epilog=TEMPLATE + '\n' + EXAMPLE)

    parser.add_argument('file', nargs='+', help='File(s) to be geocoded')
    parser.add_argument('-l', '--lookup', dest='lookupFile',
                        help='Lookup table file generated by InSAR processors.')
    parser.add_argument('-t', '--template', dest='templateFile',
                        help="Template file with geocoding options.")

    parser.add_argument('-b', '--bbox', dest='SNWE', type=float, nargs=4, metavar=('S', 'N', 'W', 'E'),
                        help='Bounding box of area to be geocoded.')
    parser.add_argument('-y', '--lat-step', dest='latStep', type=float,
                        help='output pixel size in degree in latitude.')
    parser.add_argument('-x', '--lon-step', dest='lonStep', type=float,
                        help='output pixel size in degree in longitude.')

    parser.add_argument('-i', '--interpolate', dest='interpMethod', choices={'nearest', 'bilinear'},
                        help='interpolation/resampling method. Default: nearest', default='nearest')
    parser.add_argument('--fill', dest='fillValue', type=float, default=np.nan,
                        help='Value used for points outside of the interpolation domain.\n' +
                             'Default: np.nan')

    parser.add_argument('-o', '--output', dest='outfile', nargs='*',
                        help="output file name. Default: add prefix 'geo_'")

    return parser


def cmd_line_parse(iargs=None):
    parser = create_parser()
    inps = parser.parse_args(args=iargs)

    inps.file = ut.get_file_list(inps.file)
    if not inps.file:
        sys.exit('ERROR: no input file found!')

    inps.lookupFile = ut.get_lookup_file(inps.lookupFile)
    if not inps.lookupFile:
        sys.exit('ERROR: No lookup table found! Can not geocode without it.')

    if inps.SNWE:
        inps.SNWE = tuple(inps.SNWE)

    inps.laloStep = [inps.latStep, inps.lonStep]
    if None in inps.laloStep:
        inps.laloStep = None

    return inps


def read_template2inps(template_file, inps):
    """Read input template options into Namespace inps"""
    print('read input option from template file: ' + template_file)
    if not inps:
        inps = cmd_line_parse()
    inps_dict = vars(inps)
    template = readfile.read_template(template_file)
    template = ut.check_template_auto_value(template)

    prefix = 'pysar.geocode.'
    key_list = [i for i in list(inps_dict.keys()) if prefix + i in template.keys()]
    for key in key_list:
        value = template[prefix + key]
        if value:
            if key == 'SNWE':
                inps_dict[key] = tuple([float(i) for i in value.split(',')])
            elif key in ['latStep', 'lonStep']:
                inps_dict[key] = float(value)
            elif key in ['interpMethod']:
                inps_dict[key] = value
            elif key == 'fillValue':
                if 'nan' in value.lower():
                    inps_dict[key] = np.nan
                else:
                    inps_dict[key] = float(value)

    inps.laloStep = [inps.latStep, inps.lonStep]
    if None in inps.laloStep:
        inps.laloStep = None
    return inps


############################################################################################
def update_attribute(atr_in, inps, print_msg=True):
    atr = dict(atr_in)
    length, width = inps.outShape[-2:]
    atr['LENGTH'] = length
    atr['WIDTH'] = width
    atr['Y_FIRST'] = inps.SNWE[1]
    atr['X_FIRST'] = inps.SNWE[2]
    atr['Y_STEP'] = (inps.SNWE[0] - inps.SNWE[1]) / length
    atr['X_STEP'] = (inps.SNWE[3] - inps.SNWE[2]) / width
    atr['Y_UNIT'] = 'degrees'
    atr['X_UNIT'] = 'degrees'

    # Reference point from y/x to lat/lon
    if 'REF_Y' in atr.keys():
        ref_lat, ref_lon = ut.radar2glob(np.array(int(atr['REF_Y'])), np.array(int(atr['REF_X'])),
                                         inps.lookupFile, atr_in, print_msg=False)[0:2]
        if ~np.isnan(ref_lat) and ~np.isnan(ref_lon):
            ref_y = int(np.rint((ref_lat - float(atr['Y_FIRST'])) / float(atr['Y_STEP'])))
            ref_x = int(np.rint((ref_lon - float(atr['X_FIRST'])) / float(atr['X_STEP'])))
            atr['REF_LAT'] = str(ref_lat)
            atr['REF_LON'] = str(ref_lon)
            atr['REF_Y'] = str(ref_y)
            atr['REF_X'] = str(ref_x)
            if print_msg:
                print('update REF_LAT/LON/Y/X')
        else:
            warnings.warn("original reference pixel is out of .trans file's coverage. Continue.")
            try:
                atr.pop('REF_Y')
                atr.pop('REF_X')
            except:
                pass
            try:
                atr.pop('REF_LAT')
                atr.pop('REF_LON')
            except:
                pass
    return atr


def geocode_file(infile, inps, res_obj, outfile=None):
    print('-' * 50)
    print('geocode file: {}'.format(infile))

    # read source data
    data, atr = readfile.read(infile)
    if len(data.shape) == 3:
        data = np.moveaxis(data, 0, -1)

    # resample source data into target data
    geo_data = res_obj.resample(data, inps.src_def, inps.dest_def,
                                inps.interpMethod, inps.fillValue)
    if len(geo_data.shape) == 3:
        geo_data = np.moveaxis(geo_data, -1, 0)

    # update metadata
    inps.outShape = geo_data.shape
    atr = update_attribute(atr, inps)

    # write to file
    if not outfile:
        outfile = os.path.join(os.path.dirname(infile), 'geo_' + os.path.basename(infile))
    writefile.write(geo_data, atr, outfile, infile)

    return outfile


######################################################################################
def main(iargs=None):
    inps = cmd_line_parse(iargs)
    if inps.templateFile:
        inps = read_template2inps(inps.templateFile, inps)

    start_time = time.time()

    res_obj = resample(lookupFile=inps.lookupFile, dataFile=inps.file[0], SNWE=inps.SNWE,
                       laloStep=inps.latStep)
    inps.src_def, inps.dest_def, inps.SNWE = res_obj.get_geometry_definition()

    for infile in inps.file:
        geocode_file(infile, inps, res_obj)

    print('Done.\ntime used: {:.2f} secs'.format(time.time() - start_time))
    return


######################################################################################
if __name__ == '__main__':
    main()
