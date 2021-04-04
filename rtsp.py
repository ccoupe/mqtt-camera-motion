import sys
import cv2
import os

print (cv2.__version__)

#gst = "rtspsrc location=rtsp://ccoupe:tssgnu@192.168.1.27/live latency=0 ! rtph265depay ! h265parse ! omxh265dec ! videoconvert ! appsink"
#
# Works on nano:
gst = "rtspsrc location=rtsp://ccoupe:tssgnu@192.168.1.27/live latency=200 ! queue ! rtph264depay ! queue ! h264parse ! omxh264dec ! nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! video/x-raw,format=BGR ! appsink"
#
# Another nano suggestion - module udpsrc3 reported: Internal data stream error
# that may be accurate. 
gst = "rtspsrc location=rtsp://ccoupe:tssgnu@192.168.1.27/live latency=0 ! rtph264depay ! h264parse ! nvv4l2decoder ! nvvidconv ! video/x-raw , format=(string)BGRx ! videoconvert ! appsink"
#
#
#gst = "rtspsrc location='rtsp://ccoupe:tssgnu@192.168.1.27/live' latency=0 buffer-mode=auto ! decodebin ! videoconvert ! autovideosink sync=false"
#
#
#gst = "rtspsrc location='rtsp://ccoupe:tssgnu@192.168.1.27/live' latency=0 buffer-mode=auto ! decodebin ! videoconvert ! appsink"

def nvidia_cam_rtsp(uri, width, height, latency):
    gst_str = ("rtspsrc location={} latency={} ! rtph264depay ! h264parse ! omxh264dec ! "
               "nvvidconv ! video/x-raw, width=(int){}, height=(int){}, format=(string)BGRx ! "
               "videoconvert ! appsink").format(uri, latency, width, height)
    return cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)
    
def open_cam_rtsp(uri, width, height, latency):
  os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp"
  return cv2.VideoCapture(uri, cv2.CAP_FFMPEG)
  
def open_cam_gst(uri, width, height, latency):
  pass

def open_cam_bare(uri, width, height, latency):
    return cv2.VideoCapture(uri)

uri = 'rtsp://ccoupe:tssgnu@192.168.1.40/live'  # Wyze V2 aka patio
#uri = 'rtsp://ccoupe:tssgnu@192.168.1.28/live'  # Wyze Pan aka mantle

#cap = nvidia_cam_rtsp(uri, 640, 360, 0)
#cap = open_cam_rtsp(uri, 640, 360, 0)
cap = open_cam_bare(uri, 640, 360, 0)


if not cap.isOpened() :
        print("capture failed")
        exit()

ret,frame = cap.read()
while ret :
        cv2.imshow('frame',frame)
        ret,frame = cap.read()
        if(cv2.waitKey(1) & 0xFF == ord('q')):
                break;

cap.release()
cv2.destroyAllWindows()


