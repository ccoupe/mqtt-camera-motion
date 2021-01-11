import sys
import cv2
import os

print (cv2.__version__)
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp"

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

cap = cv2.VideoCapture(gst)
#cap = cv2.VideoCapture("rtsp://ccoupe:tssgnu@192.168.1.27/live", cv2.CAP_FFMPEG)
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


