"""
Python code for extracting frames and events from .hdf5 file in DDD20 dataset.

@author: Tobi Delbruck, Zhe He
@contact: zhehe@student.ethz.ch
@latest update: 2019-June-28 22:27
"""
from pathlib import Path, PurePath
import cv2
import numpy as np
import argparse
import os
from engineering_notation import EngNumber
from tqdm import tqdm
import atexit
from src.ddd20_utils import ddd_h5_reader
from src.output.aedat2_output import AEDat2Output
from src.v2e_utils import inputFileDialog, checkAddSuffix, read_image
from src.ddd20_utils.ddd_h5_reader import DDD20SimpleReader
import src.desktop as desktop


import logging
logging.basicConfig()
root = logging.getLogger()
root.setLevel(logging.DEBUG)
# https://stackoverflow.com/questions/384076/how-can-i-color-python-logging-output/7995762#7995762
logging.addLevelName( logging.WARNING, "\033[1;31m%s\033[1;0m" % logging.getLevelName(logging.WARNING))
logging.addLevelName( logging.ERROR, "\033[1;41m%s\033[1;0m" % logging.getLevelName(logging.ERROR))
logger=logging.getLogger(__name__)

from src.slomo import video_writer

parser = argparse.ArgumentParser()

parser.add_argument("-i","--input", type=str, help="input video file; leave empty for file chooser dialog")
parser.add_argument("-o", "--output_folder", type=str, required=True, help="folder to store outputs")
parser.add_argument("--start_time", type=float, default=None, help="start at this time in seconds in video")
parser.add_argument("--stop_time", type=float, default=None, help="stop point of video stream")
parser.add_argument("--rotate180", action="store_true", help='rotate output 180 deg')
parser.add_argument("--overwrite", action="store_true", help="overwrites files in existing folder (checks existance of non-empty output_folder)")
args = parser.parse_args()


def cleanup():
    if videoWriter:
        videoWriter.release()
    if realDvsAeDatOutput:
        realDvsAeDatOutput.close()

def filter_frame(d):
    '''
    receives 16 bit frame,
    needs to return unsigned 8 bit img
    '''
    # add custom filters here...
    # d['data'] = my_filter(d['data'])
    frame8 = (d['data'] / 256).astype(np.uint8)
    return frame8

if __name__ == "__main__":
    overwrite=args.overwrite
    output_folder=args.output_folder
    f=not overwrite and os.path.exists(output_folder) and os.listdir(output_folder)
    if f:
        logger.error('output folder {} already exists\n it holds files {}\n - use --overwrite'.format(os.path.abspath(output_folder),f))
        quit()

    if not os.path.exists(output_folder):
        logger.info('making output folder {}'.format(output_folder))
        os.mkdir(output_folder)

    input_file = args.input
    if not input_file:
        input_file =inputFileDialog()
        if not input_file:
            logger.info('no file selected, quitting')
            quit()

    arguments_list = 'arguments:\n'
    for arg, value in args._get_kwargs():
        arguments_list += "{}:\t{}\n".format(arg, value)
    logger.info(arguments_list)

    with open(os.path.join(args.output_folder, "info.txt"), "w") as f:
        f.write(arguments_list)


    start_time=args.start_time
    stop_time=args.stop_time
    rotate180 = args.rotate180

    import time
    time_run_started = time.time()

    # input file checking
    if not input_file or not Path(input_file).exists():
        logger.error('input file {} does not exist'.format(input_file))
        quit()

    atexit.register(cleanup)

    davisData=DDD20SimpleReader(input_file)

    realDvsAeDatOutput=None
    videoWriter=None

    startPacket=davisData.search(timeS=start_time) if start_time else davisData.firstPacketNumber
    if startPacket is None: raise ValueError('cannot find relative start time ' + str(start_time) + 's within recording')
    stopPacket=davisData.search(timeS=stop_time) if stop_time else davisData.numPackets-1
    if stopPacket is None: raise ValueError('cannot find relative stop time ' + str(start_time) + 's within recording')
    if not start_time: start_time=0
    if not stop_time: stop_time=davisData.durationS
    numDvsEvents=0
    num_frames=0
    srcDurationToBeProcessed=stop_time-start_time

    for i in tqdm(range(startPacket, stopPacket),desc='v2e-ddd20',unit='packet'):
        packet=davisData.readPacket(i)
        if not packet: continue # empty or could not parse this one
        if stop_time >0 and packet['timestamp']>davisData.firstTimeS+ stop_time:
            logger.info('\n reached stop time {}'.format(stop_time))
            break
        if packet['etype']== ddd_h5_reader.DDD20SimpleReader.ETYPE_DVS:
            numDvsEvents+=packet['enumber']
            events=np.array(packet['data'],dtype=float) # get just events [:,[ts,x,y,pol]]
            events[:, 0] = events[:, 0] * 1e-6 # us timestamps
            if not realDvsAeDatOutput:
                filename=PurePath(input_file).name.replace('.hdf5','.aedat')
                filepath=os.path.join(output_folder, filename)
                realDvsAeDatOutput = AEDat2Output(filepath,rotate180=rotate180)
            realDvsAeDatOutput.appendEvents(events)

        elif packet['etype']== ddd_h5_reader.DDD20SimpleReader.ETYPE_APS:
            num_frames+=1
            if packet is not None:
                img = (packet['data'] / 256).astype(np.uint8)
                h,w=img.shape[0],img.shape[1]
                if not videoWriter:
                    filename = PurePath(input_file).name.replace('.hdf5', '.avi')
                    filepath = os.path.join(output_folder, filename)
                    videoWriter = video_writer(filepath,height=h, width=w)
                if rotate180: img=np.rot90(img,k=2)
                videoWriter.write(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))

    totalTime=(time.time() - time_run_started)
    framePerS=num_frames/totalTime
    sPerFrame=1/framePerS
    throughputStr=(str(EngNumber(framePerS))+'fr/s') if framePerS>1 else (str(EngNumber(sPerFrame))+'s/fr')
    logger.info('done processing {} frames in {}s ({})\n see output folder {}'.format(
                 num_frames,
                 EngNumber(totalTime),
                 throughputStr,
                 output_folder))
    logger.info("done; see output folder " + str(args.output_folder))
    try:
        desktop.open(os.path.abspath(output_folder))
    except Exception as e:
        logger.warning('{}: could not open {} in desktop'.format(e,output_folder))
    quit()


