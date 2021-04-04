# Video motion detection for Linux and MQTT. 
  Uses python,opencv, USB webcams or Raspberry pi cameras.

## Purpose
This program reads from a USB wecam or Raspberry's camera and when it detects
movement it will send 'active' or 'inactive' to a MQTT topic.  There
is a matching Hubitat driver you'll want to use. It's sensitve
to movements with its field of view which a PIR or Microwave sensor may not
trigger on.

It also reports a 'lux' level to MQTT. Do not confuse this with other 'lux's. Generally
speaking a low number means less light. This program attempts to detect step changes
in lux so that turning the lights off in the room with the camera does NOT cause and
'active' message to be sent. It fails to do that. You have to do that in the 
Hubitat motion lighting rule.

There are a large number of setting you can tweak. Some are from the configuation
file and some via the Hubitat driver and MQTT. Most of these are for performance improvement

## License
There isn't one for my code. 

## Support
The best way to contact me about problems, suggestions, wishes and fixes
is to file an [https://github.com/ccoupe/mqtt-camera-motion/issues](issue at the github repo.)
Membership is free. If it crashed, a backtrace dump is
really, really useful as are error messages from the Hubitat log if that
is where the problem shows up.

To contribute fixes, a git hub pull request is the best method for anything longer 
than three lines of code.

## Installation

### Install an MQTT server.
If you don't have one, `mosquitto` is easy to install.  It is mandatory to assign
a fixed IP address for the system running your MQTT server. Use your router configuration
software. Mine is 192.168.1.7 - yours will probably be different.

You really want a fixed IP address for the mqtt server and you want a machine that will reboot on powerfail.
A pi3 is enough to run MQTT (and a camera). You shouldn't reboot the mqtt server 
just because you think something is wrong with something else. Too many things
will depend on the server being up. 
```sh
sudo apt install mosquitto
sudo apt install mosquitto-clients
```
### Get the source code 
```sh
git clone https://github.com/ccoupe/mqtt-camera-motion.git
cd mqtt-camera-motion
```

Note: You can not share the camera with this program. When it's running you
can't use MotionEye (moditiond) or Cheese or Skype, for example. You might be
might be able to use the microphone on a USb Webcam. Maybe.

There are several ways to connect a camera to a linux system. If it is
a usb webcam or csi cam like a raspberry cam then it will have a /dev/video 
entry. If you want to read a network camera please use an rtsp camera and
pay attention.

### Find your Video device (not for rtsp)
```
ls -ld /dev/video*
```
For more detail
```
v4l2-ctl --all
```
`/dev/video0` is probably what you want to use.

#### python3 installation
With any luck at all, you'll have python3 installed - check by
`python --version` or `python3 --version`

You need some python packages.
```
sudo pip3 install numpy
sudo pip3 install paho-mqtt
```
#### opencv installation
Opencv provides the libraries for image manipulation. I use version 4.1.2 which
is a pain to install from source, especially on a Raspberry (it takes a few hours)
On a Pi Zero it takes a day and a half or more to build from source and it's a bit iffy.
You really want to use the following link instead

For Raspberry Pi's (https://solarianprogrammer.com/2019/09/17/install-opencv-raspberry-pi-raspbian-cpp-python-development/)[(follow these instructions]

If you happen to have a Raspberry 4 with 4MB, it compiles much faster and if
you are clever that can be used, how to do that is off topic.

Ubuntu linux has opencv version 3.x in its repo but we want 4.x (4.1.2+) so we have to build from source.
It's not too difficult once you have a the cmake settings. 

TODO: INSERT ubuntu cmake command line here

### Motion-Video Manual Configuration.
There are a large number of configuration settings.
l For now, we only want the first five. mqtt_server_ip, mqtt_port are
the location of your MQTT broker. Every device connecting should have a unique
id (a string), so make up short-ish something for mqtt_client_name

`trumpy.json`:m
```sh
{
  "mqtt_server_ip": "192.168.1.7",
  "mqtt_port": 1883,
  "mqtt_client_name": "trumpy_cam",
  "homie_device": "trumpy_cam",
  "homie_name": "Pi3 Camera",
  "camera_type": "capture",
  "camera_number": 0,
  "camera_prep": nil,
  "camera_height": 480,
  "camera_width": 640,
  "camera_warmup": 2.5,
  "frame_skip": 5,
  "lux_level": 0.60,
  "contour_limit": 900,
  "tick_len": 5,
  "active_hold": 10,
  "lux_secs": 300,
  "settings_rw": false,
  "snapshot": true,
  "mv_algo": "adrian_1",
  "mv_threshold": 10,
  "ml_server_ip": "192.168.1.4",
  "ml_port": 4433,
  "ml_algo": "Cnn_Shapes",
  "confidence": 0.4,
  "use_ml": "remote"
}
```
The first five deal with MQTT. 'mqtt_server_ip', 'mqtt_port' are
the location of your MQTT broker. Every device connecting should have a unique
id (a string), so make up short-ish something for mqtt_client_name. 
We attempt to use the Homie 3 compatible method of describing a device. 
All devices have a toplevel name, in the example it is 'p3_touch'. 'homie_name'
is a long form description. It's required but not used.  When mqtt-vision.py
starts up it creates corresponding topics at the MQTT broker (and many more under
that homie_device) 

The next group of settings in the json file deal with our camera.
Cameras come in two types - an internal bus wired
(CSI) camera on a Pi or a Jetson Nano. I call this a 'capture' cam because
opencv.VideoCapture() works on it and that has a lower system load that using a
stream. Load matters on a Pi. The other camera type is 'stream'. This
could be a webcam on a usb port or an rtsp camera or gstreamer pipeline.
Sometimes, you can get away with calling a webcam a 'capture' (Linux Mint 19.1)
and sometimes you can't (Ubuntu 18.04 Jetson Nano). Capture is better if it
works but often it doesn't.

'camera_number'. Enter 0 to use /dev/video0, 1 for /dev/video1, etc. 
For an rtsp camera, "camera_number": "rtsp://username:password@192.168.1.40/live" is
an example, for a wyze cam with their rtsp image.
If you need a more complex camera setup for rtsp or gstreamer pipeline
then you'll put that in the 'camera_prep' setting.

Camera height and width resize the frame. Full size can slows things down 
and truth be told you don't want 'more pixels are better'. You should 
pick something that keeps the aspect ratio correct, the settings above don't, but
they work OK. 

Frame_skip is the number of frames to skip between samples. You can consume
enormous amounts of cpu running the camera as fast as it run. How much is camera
and processor dependent. 5 frames over 30 is 1/6 second and a resonable rate
for a Pi3. Contrary to common belief you don't want a supersensitve motion detector.
I set in to 10 when using a Webcam because they take more processing power.

Camera_warmup is the number of seconds to wait after application startup.
You'd have to really care about these things to vary it below 1. It's only used
for the very first frame. 

Lux_level is not used anymore. 

Lux_secs is how often the 'average' lux level is reported. Nothing really
uses our definition of Lux and it's not reported to Hubitat so consider
mostly useless info. 

tick_len is used in conjuntion with active_hold. tick_len is in seconds.
active_hold is the number of 'ticks'to keep an'active' motion sensor as active
before going 'inactive'. Active hold can be set by hubitat and when run as
a simple motion sensor is your way of controlling how chatty the device is.
10 is a good number.  If motion happens in the 50 second (5 x 10) period
then the 50 second countdown begins anew. 

settings_rw is discouraged. If set true then any setting changes made by
hubitat is store in /var/lib/... and re-read at startup. If you make changes
you like to active_hold, just modify the json file and restart. It's nasty
code and should disapper and hubitat will change it back to Hubitat's
preference setting. 

snapshot: True means take a picture every minute and store in /var/www/camera/{snapshot.jpg}
If you are running a normal web server on the same computer then that is not an ideal place and you
may want to disable that, change the code or play some symlink games. The picture can be retrieved
and placed in a hubitat dashboard. If the motion sensor was signalling 'inactive' then
the picture will be grayscale. If active status, then it will be in color. it's Eye candy and I
like it just enough to keep it around but not enough to fix some obvious problems. One
problem that I did fix is that snapshot.jpg is now {homie_device}.jpg

'mv_algo' may be 'adrian_1' or 'intel'. It defaults to 'adrian_1' There are
two methods available for determining 'motion' or 'movement' (hence the mv_)
I borrowed both of them, adrian_1 from Adrian at PyImageSearch.com and 'intel' from
an online traing course at Intel.com.  I use 'adrian_1' but there might be situations
where 'intel' works better. You should look at the code in mqtt-motion-video.py
if you are curious.

'contour_limit' is only used by the adrian_1 scheme to find the points of interest for determining
movement. The comparsion is `contourArea < contour_limit` triggers a possible `active`. My
webcam, 3 feet from me uses a `"contour_limit": 900,` 
Your mileage may vary. 700 wasn't good enough for me. Upper limit is 1800. I Think

mv_thresh_hold is only used by the intel scheme. You'd have play with it
to determine how good the default number is. 

use_ml: can be, None, Remote or Local. None means there won't be any
machine learning processes run. Local means they will be run on this computer
and remote means they will be run at the 'ml_server_ip' which is listening on
'ml_port' The ML/AI  will be covered in more detail below after installation.

'ml_algo' see ML/AI section
'confidence' set ML/AI section

You don't have to get the configuation 100% correct just to get going.
It's really better to do the minimum (set the first 5 and use defaults)
Then see how it works for you. 

Run the script from the terminal and see what you get:
```
python3 mqtt-vision.py -c touchpi.json
```
It prints messages on the console to display settings and info
about what it's doing. Obviously, you have move into and out of camera view
and see what happens, keeping in mind the tick_len and active_hold settings.

Now you need to install the Hubitat driver so it can talk to MQTT and the
camera code. That is described below, after the System Install.

### System Install

Once the code is working well enough in your tests, it needs to be installed
in the system and startup when the system boots.

We use the systemd facility. This allows a lot chances for mis-typing. Nothing
fatal that can't be fixed.  I'm going to use the name 'touchpi' because it's one
of the raspberry pi's I have with a a camera (and a touch screen).

Create a directory in the system space and copy.
```
sudo mkdir -p /usr/local/lib/mqttcamera
sudo cp -a * /usr/local/lib/mqttcamera
```
We want a simple webserver on 'touchpi' that can serve a snapshot image. We
need a directory for the image. The path is hardcoded into the python scripts
```
sudo mkdir -p /var/www/camera
```
We need a launch script - `mqttcamera.sh` that starts the http server and
the motionsensor code
```
#!/usr/bin/env bash
ip=`hostname -I`
#python3 -m http.server 7534 --bind ${ip} --directory /var/www &
cd /usr/local/lib/mqttcamera/
python3 mqtt-motion-video.py --system -c trumpy.json
```
Note; the '--system' means we will log to syslog (/var/log/syslog). 
Change the name of the json file to fit your machine and make that script executable with a
```
chmod +x mqttcamera.sh
sudo cp mqttcamera.sh /usr/local/bin
```
You need to modify mqttcamera.service so systemd can manage the camera for booting and
other system events. Call this `mqttcamera.service`

```
[Unit]
Description=MQTT Camera
After=network-online.target

[Service]
ExecStart=/usr/local/bin/mqttcamera.sh
Restart=on-abort

[Install]
WantedBy=multi-user.target
```
Then you copy the service file to systemd's location and start the server.
```
sudo cp mqttcamera.service /etc/systemd/system
sudo systemctl enable mqttcamera
sudo systemctl start mqttcamera
```
That should get it running now and for every reboot. To stop it use `sudo systemctl stop mqttcamera`
If you want to disable it from starting up at boot time then do `sudo systemctl disable mqttcamera`

To watch the syslog, from any terminal `tail -f /var/log/syslod`

#### Light Http
apt install lighttpd
vi /etc/lighttpd/lighttpd.conf
server.document-root        = "/var/www"
server.port                 = 7534

### Hubitat driver install
 
Remember we have two devices. The Hubitat device and the device over in MQTT.

The Hubitat driver file is `mqtt-motion-video.groovy`. Using a web browser, load the Hubitat
page for your local hub, Select `< > Drivers Code`. Select `New Driver` and copy/paste
the contents of mqtt-motion-video.groovy into the browser page. Click `Save` and if there
are no errors then go to the 'Devices' page and `Add Virtual Device`, name it and from the
drop down `Type*` list select the `MQTT Motion Video V3` (it's way down at the bottom of
the list).

You'll get a page for setting up the device. You **must** fill in the MQTT server and the
two topics. Topic to Subscribe is the the topic that the MQTT camera device using. For the
sample json file above, it would be 'homie/trumpy_cam/motionsensor'
The Additional sub-topic for property is 'active_hold'. You will want to enable logging
if this is the first time you've used the driver/camera pair. Enable the 'Camera Hack"
and leave the ML_Detection alone (No Selection)

Get a Hubitat log page in new browers tab/window. Push the Save Preferences button
and switch to the log pages. You should see messages that it's 'connected' and 'subscribed'
Then switch back to the device page an up top and to the right should be 'Current Status'.
Go move in and out of the camera view and see if the Current Status changes. 

Now you can use it a a motion sensor in Hubitat. I find it useful to create
a motion zone with a PIR motion sensor and a Camera. PIR's work in the dark
and good for getting the zone 'active' and the camera excels at keeping the zone
active. A pair made in Heaven.

The Camera Hack: You may have noticed that the Hubitat Device has On and Off
buttons. Often, when motion is inactive and your motion rules turns off the light for the area
then the sudden darkness will trigger the detector to go active. Then the lights go back on,
resulting in a loop that never turns off the lights. It's very camera and light dependent.
The off button is there to  fix the issue! In your Motion App rule, select 
the `Options for Additional Sensors, Lights-Off and Off options`
and then select `Additional Switches to turn off when turned off` and select the camera device. 
That will give the camera driver advanced notice that the lights were turned off and ignore
it's movement detector, for a while (5 seconds?) 

Enable/Disable buttons if they exist, may pause the MQTT device (camera). **May**. 

There is a webserver on the MQTT device which serves up a snapshot image from the camera
every minute. One minute is hard coded in the MQTT (python) driver. You can 
use the image_url shown in Current States section. You can create a Dashboard Image tile with
that url. Refresh time for the tile would be 60 seconds. Anything else would just be wasteful since its
only going to change once a minute. If the device believes it sent an 'inactive' to Hubitat then 
the image is in gray scale. It's mostly eye candy. It is not a replacement or substitute for MotionEye
or for a Security system.

### Machine Learning (ML/AI) discussion. 
To really make the motionsensor usable it should run additional code that
tries to find people moving, not changes in 'shapes' There are well known
algorithms for doing that and I've supplied a half dozen of them. The names
in the Hubitat dropdown list and the json config reflect the common names. 
I like Cnn_Shapes so that is a good one to start with.

When one is selected in Hubitat the conversation (via MQTT) changes. The Movement
still sends 'active' and 'inactive' to the hub (technically to MQTT) Hubitat (driver)
then sends a 'detect_Cnn_Shapes' for example. The Python driver with the camera
sees that message and it calls the matching code to see if there is the shape
in a single frame (jpeg). Hubitat delays calling for the person detection by a few 
seconds - enough time to sit down or move out the frame. It does something
similar when the motionsensor code wants to go to inactive. If you're still sitting
down doing nothing much, the sensor stays active because someone is there.

You might have picked up something interesting and fun. You can change the
detection algorithm 'on the fly', without any rebooting or changing config
files just by selecting a different one on the Hubitat device page and pressing
the Save Preferences button. 

The detection code can be computational expensive (aka slow). 
Too slow for a Raspberry Pi Zero. Too slow for a Pi 3 or 4, IMO.
Note that IMO means its too slow for me. It does runs on those but no one is happy
about it. If the json setting 'use_ml' is 'Remote' then the camermotion sensor
call sends the single frame (jpeg) to another machine (ml_server_ip + ml_port).
Presumably the ml_server_ip is a much faster machine. My desktop i7 (6 core, 12 thread) 
can spike to 1100% load during that detection. The time/latency is OK and there arent
that many calls (but more than might expect). Old time server
admins cringe just thinking about those kind of spikes for 1 motionsensor.

So I bought a Nvidia Jetson Nano, compiled opencv with CUDA support and
nobody huffs about spikes, not even the Jetson. Yes, you could do the same
thing with a high end graphics card but they cost more than the Nano. A Coral
USB stick might work - not a lot cheaper than the Jetson Nano.

Running the shape_server.py code is pretty similar to running the motionsensor 
code. It's included in the git directoy since they share a lot of code.

### Performance Tuning

The code uses a fairly simple algo to find motion but it does take time and
computer cycles. With bad tuning it can run %200+ utilization of a Intel I7 (i.e.
two cores/threads . That's too much (IMO) and impossible for a 
Pi Zero. Pi 3 ? - maybe, maybe not. 

The first thing to do is reduce the frame size. Just large enough to capture the 
detail you want to detect. Since I only want to detect me, sitting at a desk and barely
moving that's where I aim the camera. I can get by with 400 x 400. Use the smallest frame
that works for you.

Fortunately we don't need 30fps full speed video. In my webcam config I have
`"frame_skip": 10,` which means read a frame, sleep for 10 frames, read a frame and compare.
That works out to have latency of detection of 1/3 second. Of course, if your machine
can't keep up with 30fps then you're already dropping frames. 

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

## Futures
1. Use a real human detection algorithm (one of the xml trained). 
2. Possible face detection
