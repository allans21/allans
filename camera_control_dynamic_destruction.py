import gi
from threading import Thread
from time import sleep
from datetime import datetime
gi.require_version("Gst", "1.0")

from gi.repository import Gst, GLib, GObject

FILE_PATH = "../../../mnt/STORAGE/"#MAKE SURE THIS PATH EXISTS OR THE VIDEOS WONT SAVE, IT WILL NOT CREATE THE FILE

high_res_pipeline = None


Gst.init()

high_res_mode1_caps = Gst.Caps.from_string("video/x-raw(memory:NVMM), width=(int)1920, height=(int)1080, format=(string)NV12, framerate=(fraction)30/1 ")
high_res_mode2_caps = Gst.Caps.from_string("video/x-raw(memory:NVMM), width=(int)3264, height=(int)1848, format=(string)NV12, framerate=(fraction)28/1 ")
high_res_mode3_caps = Gst.Caps.from_string("video/x-raw(memory:NVMM), width=(int)1280, height=(int)720, format=(string)NV12, framerate=(fraction)60/1 ")
high_res_udp_caps = Gst.Caps.from_string("width=(int)1280, height=(int)720, framerate=(fraction)5/1")
low_res_caps = Gst.Caps.from_string("video/x-raw(memory:NVMM), width=(int)1280, height=(int)720, format=(string)NV12, framerate=(fraction)1/1 ")

def set_file_resolution(mode, filt):
    print("mode = ")
    print(mode)
    if mode == 0x01:
        filt.set_property("caps", high_res_mode1_caps)
    elif mode == 0x02:
        filt.set_property("caps", high_res_mode2_caps)
    elif mode == 0x03:
        filt.set_property("caps", high_res_mode3_caps)
    else:
        filt.set_property("caps", high_res_mode1_caps)
    return filt

def create_high_res_pipeline(mode):
    pipeline = Gst.Pipeline()

    if mode&0x3 == 0:#mode is not recoring or sending, don't need pipeline
        return None

    src = Gst.ElementFactory.make("nvarguscamerasrc", "high_res_camera")
    pipeline.add(src)

    if mode&0x1 == 0x1: #create elements needed for a save structure, avoids context specific linkage
        filt_file = Gst.ElementFactory.make("capsfilter", "filter_file_hr")
        enc_file = Gst.ElementFactory.make("nvv4l2h264enc", "encoder_file_hr")
        prs_file = Gst.ElementFactory.make("h264parse", "parser_file_hr")
        mux_file = Gst.ElementFactory.make("mp4mux", "qt_muxer_file_hr")
        fs_file = Gst.ElementFactory.make("filesink", "filesink_file_hr")

        res_mode = mode & 0xc
        res_mode = res_mode >> 2
        filt_file = set_file_resolution(res_mode, filt_file)

        pipeline.add(filt_file)
        pipeline.add(enc_file)
        pipeline.add(prs_file)
        pipeline.add(mux_file)
        pipeline.add(fs_file)

        #src.link(filt_file)

        #link elements needed for all pipelines that save files
        filt_file.link(enc_file)
        enc_file.link(prs_file)
        prs_file.link(mux_file)
        mux_file.link(fs_file)

        dt = datetime.now()
        filename = "HighRes-"+str(dt.year) + '-' + str(dt.month) + '-' + str(dt.day) + '-' + str(dt.hour) + '' + str(dt.minute) + '' + str(dt.second) + ".mp4"
        fs_file.set_property("location", FILE_PATH + filename)


    if mode&0x2 == 0x2: #create elements for the udp port avoids context specific src linkage
        filt_udp = Gst.ElementFactory.make("capsfilter", "filter_udp_hr")
        filt_udp.set_property("caps", high_res_udp_caps)
        enc_udp = Gst.ElementFactory.make("nvv4l2h264enc", "encoder_udp_hr")
        prs_udp = Gst.ElementFactory.make("h264parse", "parser_udp_hr")
        rtp = Gst.ElementFactory.make("rtph264pay", "rtp_hr")
        udp_sink = Gst.ElementFactory.make("udpsink", "udp_hr")#TODO set host and port properties
        #fake = Gst.ElementFactory.make("fakesink")

        pipeline.add(filt_udp)
        pipeline.add(enc_udp)
        pipeline.add(prs_udp)
        pipeline.add(rtp)
        pipeline.add(udp_sink)
        #pipeline.add(fake)

        #link elements needed for saving to udp
        filt_udp.link(enc_udp)
        enc_udp.link(prs_udp)
        prs_udp.link(rtp)
        rtp.link(udp_sink)

    if mode&0x3 == 0x3: #create elements needed to save to file and send to udp avoids context specific src linkage
        tee= Gst.ElementFactory.make("tee", "tee_hr")
        videoscale_file = Gst.ElementFactory.make("videoscale", "videoscale_file_hr")
        videoscale_udp = Gst.ElementFactory.make("videoscale", "videoscale_udp_hr")
        queue_file = Gst.ElementFactory.make("queue", "queue_file_hr")
        queue_udp = Gst.ElementFactory.make("queue", "queue_udp_hr")

        pipeline.add(tee)
        pipeline.add(videoscale_file)
        pipeline.add(videoscale_udp)
        pipeline.add(queue_file)
        pipeline.add(queue_udp)

        #link elements for splitting without yet connecting the 2 modes to src

        tee.link(queue_file)
        tee.link(queue_udp)
        queue_file.link(videoscale_file)
        queue_udp.link(videoscale_udp)

    #Make the mode specific src links
    if mode&0x3 == 0x1:
        filt_file = pipeline.get_by_name("filter_file_hr")
        src.link(filt_file)

    elif mode&0x3 == 0x2:
        filt_udp = pipeline.get_by_name("filter_udp_hr")
        src.link(filt_udp)

    elif mode&0x03 == 0x3:
        tee = pipeline.get_by_name("tee_hr")
        videoscale_udp = pipeline.get_by_name("videoscale_udp_hr")
        videoscale_file = pipeline.get_by_name("videoscale_file_hr")
        filt_file = pipeline.get_by_name("filter_file_hr")
        filt_udp = pipeline.get_by_name("filter_udp_hr")
        src.link(tee)
        videoscale_file.link(filt_file)
        videoscale_udp.link(filt_udp)

    return pipeline

def command(byte):
    global high_res_pipeline
    #Stop pipeline if it exists
    if high_res_pipeline != None:
        print("pipeline exists, stopping recording, freeing pipeline ")
        high_res_pipeline.send_event(Gst.Event.new_eos())
        sleep(1)#need delay to let pipeline handle end of stream TODO add event probe to make sure EOS finished
        high_res_pipeline.set_state(Gst.State.NULL)
        #delete the pipeline as we need to create a new one
        high_res_pipeline.unref()
        sleep(1)#maybe need something to make sure it deletes?

    high_res_pipeline = create_high_res_pipeline(byte)

    if high_res_pipeline != None:
        high_res_pipeline.set_state(Gst.State.PLAYING) #start the pipeline



