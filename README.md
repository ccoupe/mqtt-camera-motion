# Video motion detection for Linux and MQTT. 
  Uses python, USB webcams or Raspberry pi cameras.

## Purpose
This program reads from a USB wecam or Raspberry's camera and when it detects
movement it will send 'active' or 'inactive' to a MQTT topic.  There
is a matching Hubitat driver you'll want to use. It's extremely sensitve
to small movements which a PIR or Microwave sensor wouldn't trigger.

It also reports a 'lux' level to MQTT. Do not confuse this with other 'lux's. Generally
speaking a low number means less light. This program attempt to detect step changes
in lux so that turning the lights off in the room with the camera does NOT cause and
'active' message to be sent. Attempts to do that. You may have to do that in the Hubitat rule.

There are a large number of setting you can tweak. Some are from the configuation
file and some via the Hubitat driver and MQTT. Most of these are for performance improvment

## License
There isn't one for my code. 

## Support
The best way to contact me about problems, suggestions, wishes and fixes
is to file an [https://github.com/ccoupe/mqtt-camera-motion/issues](issue at the github repo.)
Membership is free. If it crashed, a backtrace dump is
really, really useful as are error messages from the Hubitat log if that
is where the problem shows up.

To contribute fixes, a git hub pull request is the best method for anything longer 
that three lines of code.

## Installation

```
git clone https://github.com/ccoupe/mqtt-camera-motion.git
cd mqtt-camera-motion
```

Note: You can not share the camera with this program. When it's running you
can't use MotionEye (moditiond) or Cheese or Skype, for example. You might be
might be able to use the microphone on a USb Webcam. Maybe.

### Find your Video device
```
ls -ld /dev/video*
```
For more detail
```
v4l2-ctl --all
```
#### python3 installation
With any luck at all, you'll have python3 installed - check by
`python --version` or `python3 --version`

You need some python packages.
```
sudo pip install numpy
sudo pip install paho-mqtt
```
#### opencv installation
Opencv provides the libraries for image manipulation. I use version 4.1.2 which
is a real pain to install from source, especially on a Raspberry (takes a few hours)
On a Pi Zero it takes a day and a half or more to build from source and it's a bit iffy.
You really want to use the following link instead

For Raspberry Pi's (https://solarianprogrammer.com/2019/09/17/install-opencv-raspberry-pi-raspbian-cpp-python-development/)[(follow these instructions]

Ubuntu linux has opencv version 3.x in its repo but we want 4.x (4.1.2+) so we have to build from source.
It's not difficult once you have a working configuration. It does take some time

INSERT configuration here

### Manual Configuration.
Try it manually to see how well it works for you and to get your configuation
workable before doing a system install. Create a json file. For example here is
a bronco.json. 'bronco is the computer name but it should probably be office-webcam.json
to better reflect where and what it is.
```
{
  "server_ip": "192.168.1.7",
  "port": 1883,
  "client_name": "office_video_webcam",
  "topic_publish": "cameras/office/webcam",
  "topic_control": "cameras/office/webcam",
  "camera_number": 0,
  "camera_height": 640,
  "camera_width": 480,
  "camera_warmup_time": 2.5,
  "camera_fps": 16,
  "lux_level": 0.6,
  "contour_limit": 900,
  "active_hold": 10,
  "tick_size": 5
}
```
We'll get to the parameters later but the important one at this point is the
camera_number. Enter 0 to use /dev/video0, 1 for /dev/video1, etc. 
Sometimes, -1 works better than 0. Sometimes.

Run the script from the terminal and see what you get. 
```
python3 mqtt-vision.py -d -c pi.json
```
the -d mean debug. -d only works from a terminal launch because it puts
up a window for the camera frames and draws detection rectangles on it. you need
the visual to tune things for the best performance. 

### System Install

We use the systemd facility. 

Create a directory for the configuration file. I'll use /usr/local/etc/mqtt-camera
Copy your working json file.
```
sudo mkdir -p /usr/local/etc/mqtt-camera
sudo cp pi.json /usr/local/etc/mqtt-camera
```

Create a directory for the python code. I'll use /usr/local/bin

```
sudo cp mqtt-vision.py /usr/local/lib/mqtt-camera.py
```
You need to modify mqttcamera.service so systemd can manage the camera for booting and
other system events. For example:

```
[Unit]
Description=MQTT Camera

[Service]
ExecStart=python3 /usr/local/lib/mqtt-vision.py -c /usr/local/etc/mqtt-camera/pi.conf
Restart=on-abort

[Install]
WantedBy=multi-user.target
```
Then you copy the service file to systemd's location and start the server.
```
sudo cp mqttcamera.service /etc/system/systemd
sudo systemctl enable mqttcamera
sudo systemctl start mqttcamera
```
That should get it running now and for every reboot. If you want to disable it
to fix it or use the camera for another application `sudo systemctl disable mqttcamera`
mqttcamera will log to /var/log/mqttcamera. The word `backtrace` in the log would indicate
a failure that needs fixing, ASAP. 

### Install an MQTT server.
If you don't have one, `mosquitto` is easy to install.  It's almost mandatory to assign
a fixed IP address for the system running your MQTT server using your router configuration
software.

You really want a fixed IP address and you want a machine that will reboot on powerfail. A pi3 is
enough to run MQTT and the camera if you want.

TODO: Instuctions here.

### Hubitat driver install

TODO:

### Performance Tuning

The code uses a fairly simple algo to find motion but it does take time and
computer cycles. With bad tuning it can run %200+ utilization of a Intel I7 (i.e.
two cores/threads . That's too much (IMO) and impossible for a 
Pi Zero. Pi 3 ? - maybe, maybe not. 

The first thing to do is reduce the frame size. Just large enough to capture the 
detail you want to detect. Since I only want to detect me, sitting at a desk and barely
moving that's were I aim the camera. I can get by with 400 x 400. Use the smallest frame
that works for you.

Fortunately we don't need 30fps full speed video. In my webcam config I have
`"frame_skip": 10,` which means read a frame, sleep for 10 frames, read a frame and compare.
That works out to have latency of detection of 1/3 second. Of course, if your machine
can't keep up with 30fps then you're already dropping frames. On a Raspberry PI it might be
a much lower value because it can't keep up as it is.

The current algo uses a 'contour size' to find the points of interest for determining
movement. The comparsion is `contourArea < contour_limit` triggers a possible `active`. My
webcam, 3 feet from me uses a `"contour_limit": 900,` 
Your mileage may vary. 700 wasn't good enough for me. 

`"active_hold": 10,` means we'll wait at least 10 `ticks` after sending an `active` to the
MQTT topic (Hubitat driver) before we think about issue an `inactive`. In combination with 
`"tick_size": 5,` will give a 50 second hold time.  `tick_size` is in seconds. It also
controls how often the code checks to see if there was motion during the `tick` and we can
delay the `inactive` by another 

`"lux_level": 0.60,` is the percentage, in decimal for the lux level to drop in order to
NOT trigger an active when the lights go out. This is kind of big deal. If we have a Hubitat
rule the turns the light off when motion goes inactive then detector would see that two frames
are not alike, by a lot of pixels and send an 'active' which would turn the lights back on.
This is not theorical- simpler detectors would do this and its really annoying. The current code for lux step changes may not work. I don't actually 
need it because the algo doesn't seem to be sensitive to that problem AND since we don't check frames
that often there plenty of time. If the lights were dimmed over 20 seconds? I don't know, I don't have
a smart dimmer switch. NOTE: This lux step change code doesn't work, yet.  FWIW at 60% it also gets triggered
 when the monitor screen saver goes black in an otherwise dark room.
 
The hubitat driver also has some of these settings you can fine tune the settings
from a web browser. You still have to update the configuration json with any changes or you'll
lose them at the next boot. 


## Backstory
I was playing around with motion sensors like the Samsung SmartThings and the
Phillips Hue sensor. They work fine if you want to turn on the light when you
move into a room and then the lights turn off after some delay from the sensor and 
from Hubitat settings. If you move around in the room then the lights stay on.

What happens if you plant yourself in front of a computer or comfy chair and barely move? 
Correct, the lights go out after a while because you aren't moving enough.

This a problem for me. Granted, it's not a solve world hunger problem but maybe 
I could fix this one, for me. First, I bought some components and build my own PIR 
sensor (AM312) and an ESP32. That wasn't any better. I tried a microwave sensor
(RCWL-0516) which is a funny device. Pretty sensitive to small movements, most times.
It also sees movement through walls which defeats the point of having a sensor
in a room for that room. Then I built a combo device, when the PIR sees movement
it sends an 'active' to MQTT and any RCWL triggersignals  extend the time until my device
sends an 'inactive'.  This works pretty well and I learned about ESP32 and Arduino and 
PlatformIO and refreshed my opinion of C++ (I'm not a fan). I also learned enough groovy
to modify some Hubitat drivers to talk to MQTT.

I looked at a few other things until I ran across some YouTube videos showing ESP32 cameras
doing facial recognition. Of course I found videos of systems doing object detection and
tracking (althogh not with a puny ESP32). So I ordered a couple of ESP32 camera's. I
broke one right of the bat (fat findered the connector) and the other one gets a software error
in the driver, for
no reason that make sense to me.  Then I thought, MotionEye claims to do motion detection
so I got a camera for my raspberry pi3 (it's also my MQTT server) and after some fun I did 
get a video motion detector working for Hubitat. But, it too has limitations. Accuracy depends
on the camera distance, lens and frame size and it gets chatty - it's not been a load on Hubitat with
all that traffic from the mqtt server but it is inefficient and it consumes half the raspberry cpu and 
that bugs me. I know my economics are backwards, but it's a hobby!

Still, I bought a Pi Zero Wireless and a camera chip for it, installed motioneye (NOT MotionEyeOS) and
that works pretty well in my office. A pi zero doesn't have the processing power to do decent frame rates
if you wanted a fancy motioneye security camera. For this application, higher frame rates are not needed and 
small frame sizes like 640 x 480 are what I needed.
I could call it quits and be happy.

Of course, quitting is not an real option until I try to do even better. I also have
a USB Webcam (Logitech 615) on my 'big' ubuntu box. Lot's of processing power for development.
All the cool kids use Python (I'm Rubyist). More importantly all the opencv samples are in python and very
close to what I need. 

However examples do not make 'App's and in particular they do not make fancy weird device drivers. 
That's what this project does.
