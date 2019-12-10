/**
   * Note: I borrowed a lot of code from the author below and other examples. CJC.
   *
   *  Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
   *  in compliance with the License. You may obtain a copy of the License at:
   *
   *      http://www.apache.org/licenses/LICENSE-2.0
   *
   *  Unless required by applicable law or agreed to in writing, software distributed under the License is distributed
   *  on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License
   *  for the specific language governing permissions and limitations under the License.
   *
   * ------------------------------------------------------------------------------------------------------------------------------
   *
   *
   *  Changes:
   *
   *  1.0.0 - Initial release
   */

import groovy.json.JsonOutput
import groovy.json.JsonSlurper 


metadata {
  definition (name: "MQTT Motion Video", namespace: "ccoupe", 
      author: "Cecil Coupe", 
      importURL: "https://raw.githubusercontent.com/ccoupe/mqtt-camera-motion/master/mqtt-motion-video.groovy"
    ) {
    capability "Initialize"
    capability "MotionSensor"
    capability "IlluminanceMeasurement"
    capability "Configuration"
    capability "Refresh"
		capability "Switch"
    
    //command "off"
    //command "on"
    command "enable"
    command "disable"
       
    attribute "motion", "string"
    attribute "motion","ENUM",["active","inactive"]
    attribute "lux", "number"
    attribute "image_url", "string"
 }

  preferences {
    input name: "MQTTBroker", type: "text", title: "MQTT Broker Address:", required: true, displayDuringSetup: true
    input name: "username", type: "text", title: "MQTT Username:", description: "(blank if none)", required: false, displayDuringSetup: true
    input name: "password", type: "password", title: "MQTT Password:", description: "(blank if none)", required: false, displayDuringSetup: true
    input name: "topicSub", type: "text", title: "Topic to Subscribe:", 
        description: "Example Topic (office/cameras/camera1). Please don't use a #", 
        required: false, displayDuringSetup: true
    input name: "topicPub", type: "text", title: "Topic to Publish:",
        description: "Example Topic (office/cameras/camera1_control)", 
        required: false, displayDuringSetup: true
    input name: "QOS", type: "text", title: "QOS Value:", required: false, 
        defaultValue: "1", displayDuringSetup: true
    input name: "retained", type: "bool", title: "Retain message:", required:false,
        defaultValue: false, displayDuringSetup: true
    input name: "frame_skip", type: "number", title: "Frames to Skip",
        required: false, displayDuringSetup: true, defaultValue: 10,
        description: "Number of frames to skip"
    input name: "tick_len", type: "number", title: "Tick Length",
        required: false, displayDuringSetup: true, defaultValue: 5,
        description: "Number of seconds per 'tick'. Controls frequency of timers"
    input name: "active_hold", type: "number", title: "Active Hold",
        required: false, displayDuringSetup: true, defaultValue: 10,
        description: "Number of 'tick's to keep motion active"
    input name: "contour_limit", type: "number", title: "Contour Limit",
        required: false, displayDuringSetup: true, defaultValue: 900, range: 500..1800
        description: "Controls Contour Area size for movements. "
    input name: "lux_level", type: "number", title: "Lux Level",
        required: false, displayDuringSetup: true, defaultValue: 0.60, range: 0.1..1.00
        description: "Decimal % for detection Lights Out to prevent false actives"
    input name: "lux_secs", type: "number", title: "Lux Report Interval",
        required: false, displayDuringSetup: true, defaultValue: 300, range: 60..3600
        description: "Number of seconds between report device's Lux"
    input("logEnable", "bool", title: "Enable logging", required: true, defaultValue: true)
 }
}


def installed() {
    log.info "installed..."
}

// Parse incoming device messages to generate events
def parse(String description) {
  msg = interfaces.mqtt.parseMessage(description)
  topic = msg.get('topic')
  payload = msg.get('payload')
  if (payload.startsWith("active")){
      if (logEnable) log.info "mqtt ${topic} => ${payload}"
      sendEvent(name: "motion", value: "active")
    }
  else if (payload.startsWith("inactive")){
      if (logEnable) log.info "mqtt ${topic} => ${payload}"
      sendEvent(name: "motion", value: "inactive")
  } else if (payload.startsWith("conf=")) {
    jstr = payload[5..-1]
    if (logEnable) log.debug "recv: conf=${jstr}"
    def parser = new JsonSlurper()
    def rmconf = parser.parseText(jstr)
    // get the values out of rmconf into the gui preferences
    if (rmconf['frame_skip']) {
      device.updateSetting("frame_skip",rmconf['frame_skip'].toInteger())
      //sendEvent(name: "frame_skip", value: rmconf['frame_skip'], displayed: true);
    }
    if (rmconf['lux_level']) {
      device.updateSetting("lux_level",rmconf['lux_level'].toFloat())
      //sendEvent(name: "lux_level", value: rmconf['lux_level'], displayed: true);
    }
    if (rmconf['contour_limit']) {
      device.updateSetting("contour_limit",rmconf['contour_limit'].toInteger())
      //sendEvent(name: "contour_limit", value: rmconf['contour_limit'], displayed: true);
    }
    if (rmconf['tick_len']) {
      device.updateSetting("tick_len",rmconf['tick_len'].toInteger())
      //sendEvent(name: "tick_len", value: rmconf['tick_len'], displayed: true);
    }
    if (rmconf['active_hold']) {
      device.updateSetting("active_hold",rmconf['active_hold'].toInteger())
      //sendEvent(name: "active_hold", value: rmconf['active_hold'], displayed: true);
    }
    if (rmconf['lux_secs']) {
      device.updateSetting("lux_secs",rmconf['lux_secs'].toInteger())
      //sendEvent(name: "lux_secs", value: rmconf['lux_secs'], displayed: true);
    }
    if (rmconf['image_url']) {
      sendEvent(name: "image_url", value: rmconf['image_url'], displayed: true);
    }
  }
  // lux=n can tag along with active,inactive to can be by itself
  if (payload.contains("lux=")) {
    p = payload.indexOf("lux=")
    lux = payload[p+4..-1].toInteger()
    if (logEnable) log.info "lux=${lux}"
    sendEvent(name: "illuminance", value: lux, unit: "lux")
  } 
}


def updated() {
  if (logEnable) log.info "Updated..."
  if (interfaces.mqtt.isConnected() == false)
    initialize()
  // send json struct of all preferences? 
  configure()
}

def uninstalled() {
  if (logEnable) log.info "Disconnecting from mqtt"
  interfaces.mqtt.disconnect()
}

def initialize() {
	//if (logEnable) runIn(900,logsOff) // clears debugging after 900 somethings
  if (logEnable) log.info "Initalize..."
	try {
    def mqttInt = interfaces.mqtt
    //open connection
    mqttbroker = "tcp://" + settings?.MQTTBroker + ":1883"
    mqttInt.connect(mqttbroker, "hubitat_${device}", settings?.username,settings?.password)
    //give it a chance to start
    pauseExecution(1000)
    log.info "Connection established"
		if (logEnable) log.debug "Subscribed to: ${settings?.topicSub}"
    mqttInt.subscribe(settings?.topicSub)
    refresh()   // get device config
  } catch(e) {
    if (logEnable) log.debug "Initialize error: ${e.message}"
  }
}


def mqttClientStatus(String status){
  if (logEnable) log.debug "MQTTStatus- error: ${message}"
}

def logsOff(){
  log.warn "Debug logging disabled."
  device.updateSetting("logEnable",[value:"false",type:"bool"])
}

// Send commands to device via MQTT
def disable() {
  log.debug settings?.topicPub + " disable sensor"
  interfaces.mqtt.publish(settings?.topicPub, "disable", settings?.QOS.toInteger(), settings?.retained)
}

def enable() {
  log.debug settings?.topicPub + " enable sensor"
  interfaces.mqtt.publish(settings?.topicPub, "enable", settings?.QOS.toInteger(), settings?.retained)
}

def refresh() {
  log.debug settings?.topicPub + " get configuation"
  interfaces.mqtt.publish(settings?.topicPub, "conf", settings?.QOS.toInteger(), settings?.retained)
}

def off() {
  log.debug settings?.topicPub + " additional off"
  interfaces.mqtt.publish(settings?.topicPub, "off", settings?.QOS.toInteger(), settings?.retained)
}

def on() {
  log.debug settings?.topicPub + " additional on"
  interfaces.mqtt.publish(settings?.topicPub, "on", settings?.QOS.toInteger(), settings?.retained)
}

def configure() {
  def map = [:]
  map['frame_skip'] = settings.frame_skip.toInteger()
  map['lux_level'] = settings.lux_level.toFloat()
  map['tick_len'] = settings.tick_len.toInteger()
  map['lux_secs'] = settings.lux_secs.toInteger()
  map['active_hold'] = settings.active_hold.toInteger()
  map['contour_limit'] = settings.contour_limit.toInteger()
  def json = JsonOutput.toJson(map)
  interfaces.mqtt.publish(settings?.topicPub, "conf=${json}", settings?.QOS.toInteger(), settings?.retained)
  log.debug "send conf=${json}"
  refresh()
}
