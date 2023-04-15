#!/usr/bin/python -u

# This script is designed to interface an
# IntesisBox DK-RC-MBS-1 behind a modbus TCP/RTU gateway
# to Home Assistant, via MQTT, although it does dump
# a lot more info to MQTT than HA can use at this time.
#
# I'm sure with a bit of work it would work with some of the
# other IntesisBox gateways as well, but I don't have any
# to play with.
#
# David Monro <davidm@davidmonro.net>
#
import paho.mqtt.client as mqtt
from pymodbus.client.sync import ModbusTcpClient
import time
import uuid
import sys
from os import environ

# Poll rate, in seconds
timeslice = 5

# Mapping from modbus registers to topics for publishing
modbustotopic = {
  0: 'power_state',
  1: 'operating_mode',
  2: 'fan_speed',
  3: 'vane_position',
  4: 'temp_setpoint_decidegrees',
  5: 'temp_ref_decidegrees',
  6: 'window_contact_state',
  7: 'bridge_disabled',
  8: 'remote_disabled',
  9: 'ac_operation_hours',
  10: 'alarm_status',
  11: 'alarm_error_code',
  13: 'window_switchoff_timeout',
  14: 'modbus_rtu_baud_rate',
  15: 'modbus_slave_address',
  21: 'max_number_fan_speeds',
  22: 'ext_temp_ref_decidegrees',
  23: 'temp_setpoint_actual_decidegrees',
  26: 'horizontal_vane_position',
  48: 'switch_value',
  49: 'device_id',
  50: 'software_version',
  55: 'under_voltage_counter',
  97: 'block_periodic_sending'
}

# Synthesized topics for HA
synthopstatetopic='combined_operating_mode_power'
synthtempstatetopic='temp_setpoint_for_ha'
synthfanstatetopic='fan_speed_for_ha'
synthmodestatetopic='mode_state_for_ha'

# Map from HA modes to modbus values
opmode_to_modbus = {
  'auto': 0,
  'heat': 1,
  'dry': 2,
  'fan_only': 3,
  'cool': 4
}

powerstate_to_modbus = {
  'ON': 1,
  'OFF': 0
}

fanstate_to_modbus = {
  'low': 1,
  'medium': 2,
  'high': 3
}

synthmode_to_ha = {
  -1: 'off',
  0: 'auto',
  1: 'heat',
  2: 'dry',
  3: 'fan_only',
  4: 'cool'
}

# MQTT callbacks
# The callback for when the client receives a CONNACK response from the server.
def on_connect(client, userdata, flags, rc):
  print("Connected with result code "+str(rc))

  # Subscribing in on_connect() means that if we lose the connection and
  # reconnect then subscriptions will be renewed.
  client.subscribe(controltopicbase+'#')

# The callback for when a PUBLISH message is received from the server.
def on_message(client, userdata, msg):
  print(msg.topic+" "+str(msg.payload))
  # We are making a change, so schedule the next scan 1 second from now
  # (we don't want to do it immediately, the intesis box does seem to take
  # a non-zero amount of time to reflect the changes)
  global nextpub
  nextpub = int(time.time()) + 1
  controltarget = msg.topic[len(controltopicbase):]
  if controltarget == 'operating_mode':
    try:
      if msg.payload.decode() != 'off':
        print('request to set opmode to '+msg.payload.decode())
        regval = opmode_to_modbus[msg.payload.decode()]
        print('setting register 1 to '+str(regval))
        modbusclient.write_register(1,regval,unit=modbus_unit)
        print('set register 1 to '+str(regval))
    except Exception as e:
      print('Exception!' + e)
  if controltarget == 'power_state':
    try:
      print('request to set power to '+msg.payload.decode())
      regval = powerstate_to_modbus[msg.payload.decode()]
      print('setting register 0 to '+str(regval))
      modbusclient.write_register(0,regval,unit=modbus_unit)
      print('set register 0 to '+str(regval))
    except Exception as e:
      print('Exception!' + e)
  if controltarget == 'temp_setpoint_decidegrees':
    try:
      print('request to set temp setpoint to '+msg.payload.decode())
      print(str(float(msg.payload.decode())))
      regval = int(float(msg.payload.decode()) * 10)
      print('setting register 4 to '+str(regval))
      modbusclient.write_register(4,regval,unit=modbus_unit)
      print('set register 4 to '+str(regval))
    except Exception as e:
      print('Exception!' + e)
  if controltarget == 'fan_speed':
    try:
      print('request to set fan speed to '+msg.payload.decode())
      regval = fanstate_to_modbus[msg.payload.decode()]
      print('setting register 2 to '+str(regval))
      modbusclient.write_register(2,regval,unit=modbus_unit)
      print('set register 2 to '+str(regval))
    except Exception as e:
      print('Exception!' + e)

    

# Scan the modbus device and publish into mqtt
def scan_modbus_target(modbusclient, mqttclient):
  #print('scanning modbus target')
  rr50 = modbusclient.read_holding_registers(0,50,unit=modbus_unit)
  for reg in modbustotopic:
    if reg <= 49:
      mqttclient.publish(statetopicbase+modbustotopic[reg], rr50.registers[reg], qos=2, retain=False)
    else:
      rr = modbusclient.read_holding_registers(reg, 1, unit=modbus_unit)
      mqttclient.publish(statetopicbase+modbustotopic[reg], rr.registers[0], qos=2, retain=False)
  # Special case - the HA MQTT climate module expects the state to be 'off' if it isn't currently powered.
  # Synthesize a special topic to make this work - return a value of '-1' if the system is off, or else
  # return the normal value
  synthopstate = rr50.registers[1]
  if rr50.registers[0] == 0:
    synthopstate = -1
  mqttclient.publish(statetopicbase+synthopstatetopic, synthopstate, qos=2, retain=False)
  mqttclient.publish(statetopicbase+synthmodestatetopic, synthmode_to_ha[synthopstate], qos=2, retain=False)

  # The intesis box returns nonsense when the mode doesn't have a setpoint
  # So just return the curent ref temp
  if rr50.registers[4] == 32768:
    synthtempstate=rr50.registers[5]
  else:
    synthtempstate=rr50.registers[4]
  mqttclient.publish(statetopicbase+synthtempstatetopic, synthtempstate, qos=2, retain=False)

  if rr50.registers[2] == 1:
    synthfanstate = 'low'
  if (rr50.registers[2] == 2):
    if(rr50.registers[21] == 2):
      synthfanstate = 'high'
    else:
      synthfanstate = 'medium'
  if (rr50.registers[2] == 3):
    synthfanstate = 'high'
  mqttclient.publish(statetopicbase+synthfanstatetopic, synthfanstate, qos=2, retain=False)

#synthtempstate='temp_setpoint_for_ha'
#synthfanstate='fan_speed_for_ha'
  
# Main program starts here
# Pull all the stuff we need from environment variables
try:
  mqtt_host = environ['MQTT_HOST']
except:
  sys.exit('MQTT_HOST not defined')

try:
  mqtt_port = int(environ['MQTT_PORT'])
except:
  mqtt_port = 1883

try:
  mqtt_clientid = environ['MQTT_CLIENTID']
except:
  mqtt_clientid = str(uuid.uuid1())

try:
  statetopicbase = environ['MQTT_STATE_TOPIC_BASE'].rstrip('/')+'/'
except:
  sys.exit('MQTT_STATE_TOPIC_BASE not defined')

print('statetopicbase is '+statetopicbase)

try:
  controltopicbase = environ['MQTT_CONTROL_TOPIC_BASE'].rstrip('/')+'/'
except:
  sys.exit('MQTT_CONTROL_TOPIC_BASE not defined')

print('controltopicbase is '+controltopicbase)

mqtt_use_tls = False
try:
  if environ['MQTT_TLS'] == "True":
    mqtt_use_tls = True
except:
  pass

mqtt_use_tls_insecure = False
try:
  if environ['MQTT_TLS_INSECURE'] == "True":
    mqtt_use_tls_insecure = True
except:
  pass

mqtt_username = None
try:
  mqtt_username = environ['MQTT_USERNAME']
except:
  pass

mqtt_password = None
try:
  mqtt_password = environ['MQTT_PASSWORD']
except:
  pass

try:
  modbus_host = environ['MODBUS_HOST']
except:
  sys.exit('MODBUS_HOST not set')

try:
  modbus_port = environ['MODBUS_PORT']
except:
  modbus_port = 502

try:
  modbus_unit = int(environ['MODBUS_UNIT'])
except:
  sys.exit('MODBUS_UNIT not set')

# Create the mqtt client and make it run
mqttclient = mqtt.Client(client_id = mqtt_clientid)
mqttclient.on_connect = on_connect
mqttclient.on_message = on_message
mqttclient.will_set(statetopicbase+'online_state', payload='offline', qos=2, retain=True)
if mqtt_use_tls:
  mqttclient.tls_set()
  if mqtt_use_tls_insecure:
    mqttclient.tls_insecure_set(True)

if mqtt_username:
  # This works because mqtt_password will be None if it isn't set
  mqttclient.username_pw_set(mqtt_username, mqtt_password)

mqttclient.connect(mqtt_host, mqtt_port, 60)
mqttclient.publish(statetopicbase+'online_state', payload='online', qos=2, retain=True)
modbusclient = ModbusTcpClient(modbus_host, modbus_port)
modbusclient.connect()

# Trigger next scan immediately
nextpub = int(time.time())

while mqttclient.loop(timeout=1.0) == 0:
  now = int(time.time())
  if now >= nextpub:
    nextpub = int(time.time()) + timeslice
    scan_modbus_target(modbusclient, mqttclient)
