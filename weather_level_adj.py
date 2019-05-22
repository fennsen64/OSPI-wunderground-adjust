# !/usr/bin/env python 
# This script ajust the water-level on OpenSprinkler based on Weatherunderground data (WU) 
# Version 1.3 - 22.05.2019 
# All adjustments to the original OSPI included scripts (by Dan-in-CA) found on https://github.com/Dan-in-CA/SIP
#     made by A. von de Fenn (fennsen) in May 2019. The code is under GPL licence.
# Some parts of this code also includes portions from simonvanderveldt/mqtt-wunderground on GITHUB
#
# Attention: This script is only valid and useable for the python version of the Opensprinkler Board ('OSPi', also as newer versions called 'SIP'),
#  which means the Raspberry Version of the program, not the microcode version It is a direct replacement for the available default plugin 'WEATHER-BASED WATER LEVEL' (see and activate under 'PLUGINS', 
# weather_level_adj) and ads an MQTT functionality on top It calculates a percentage value and adds this as parameter "wl_weather" into the data-file './OSPI/data/sd.json
# if the plugin is activated in the plugin section (see parameter "auto_wl": "on" in the config file  "weather_level_adj.json",
#   it multiplies the main water level (normally 100%) with the value of wl_weather (e.g. 100% * 120%) and adjusts the programs running time to the appropriate level (e.g. 100% = 60 minutes run time is 
# given as default, it goes to 120% run time which is +12 minutes (+20%): 72 minutes 
# Hint: you can enable or disable this weather-based adjustment in the STATIONS menu per station. This is useful if you 
# have stations/programms who should always run with the given main
#  'Water Level' without the plugin adjustments
#
# Installation: This version needs JSON and the PAHO-MQTT client
#  1. Install json and the paho-mqtt client via npm on the raspberry
#  2. copy this script into the plugin directory of your OSPI installation e.g. /home/pi/OSPI/plugins the script must have the executeable bit
#  3. copy the html page to the templates directory e.g. /home/pi/OSPI/templates
#  4. open plugin menu via the OSPI webpage and adjust parameters. Activate the plugin
# 
# Configuration: 
# Please be aware that the config parameters for the 'standalone' modus are set via editing the script file.
# Config parameters for the 'plugin' modus are set via the plugin website. Initial values are included in the config section, but will be overwritten with the first usage per plugin website
#
# Default days for the calculation is a complete week (3 days history + actual day + 3 days forecast). You can adjust this in the plugin settings.
#  Wunderground API available history data are the last 7 days, thereof the fist value '6' is always the actual day
#  Wunderground API available forecast data are 5 days, thereof the fist value '0' is the actual day (not used, taken from history which reflects the AS-IS from today) and '1' is always tomorrow
# 
# As variant is also possible to run this script on an other server (completely independent from OSPI) and to update water data via normal HTTP GET call to the OSPI's API. In this case, the 
# weather-adjustment is made to the main-parameter 'Water Level' (see parameter "wl": xxx) in the config-file sd.json
# To enable this alternative,
#  you've to set the parameter config['modus'] = "standalone" in the script header. This disables all definitions and statements who refers to the local web-instance (eg. import web, import gv).
# 
# Environment:
#  tested under python2.7, OSPI version 3.1.46 (2016-04-30)
#
# Change log 
# Version 1.1 
#  Added description and installation documentation 
#  NEW Probability factor - how the sum of forecasted rain from WU is used in calculation - included as config-parameter
# Version 1.2
#  NEW consistency check on reported history rain amount. value must not be higher than e.g. 120mm
# Version 1.3
#  Configuration via plugin website (adjusted) are implemented
#
import datetime
from random import randint
from threading import Thread
import sys
import traceback
import shutil
import json
import time
import re
import os
import urllib
import urllib2
import errno

# Specific imports if runs as Plugin in the main OSPI program
import web
import gv  # Get access to ospi's settings
from urls import urls  # Get access to ospi's URLs
from ospi import template_render
from webpages import ProtectedPage
#

#######ADDED####
import json
import paho.mqtt.client as paho
import logging

# Log to STDOUT
logger = logging.getLogger("wunderground")
logger.setLevel(logging.INFO)
consoleHandler = logging.StreamHandler()
logger.addHandler(consoleHandler)

# BEGIN OF CONFIG PART ####################

# Component CONFIG
config = {}
# if modus set to 'plugin' the script gets the setting from the json-settings file. Following defaults will be overwritten
config['modus'] = "plugin" # Main switch if script works under OSPI as plugin or standalone. Default value = 'plugin'. Option = 'standalone'
# MQTT settings
config['auto_mqtt'] = "off" # MQTT Master switch; set to on if you want to publish data to MQTT broker
config['deviceid'] = "wunderground"
config['broker_address'] = "192.168.0.201" # IP address of MQTT broker
config['broker_port'] = 1883 # Port of MQTT broker, default = 1883
config['publish_topic'] = "yourname/home/weather/wu" # MQTT publish path
config['config_topic'] = "config/clients/wunderground" # path where MQTT stores his settings
# Settings for standalone modus
config['ospi_address'] = "192.168.0.200" # Address of open-sprinkler (OSPI); needed to update water-level
config['ospi_port'] = 8080 # Port of open-sprinkler (OSPI), default = 8080
config['ospi_passwd'] = "yourpassword"
#
## if modus set to 'plugin' the script gets the settings from the json-settings file. Following defaults will be overwritten
# Wateroptions CONFIG
config['wl_min'] = 0 # Minimum water level in % # included in options from webpage settings # default = 0
config['wl_max'] = 200 # Maximum water level in % # included in options from webpage settings # default = 200
# Wunderground CONFIG
config['days_history'] = 3
config['days_forecast'] = 3
config['updaterate'] = 3600  # in seconds  (default: update each hour, maximum rate with WU are 30minutes)
config['wu_api_key'] =  "your-wu-api-key"
config['country'] = "de-DE"
config['city'] = "Duesseldorf"
config['stationid_HIST'] = "INORDRHE570" # weatherunderground Station-ID for history (should be your personal PWS or a station near bye)
config['stationid_FC'] = "EDDL" # Station-ID, City or Airport-code for forecast-data, align FC_type appropriate
config['stationid_FC_type'] = "icaoCode" # if you change stationid_FC to another value as an airport code (e.g. geo-location or city, you've to change this parameter. See WU API documentation
config['rain_forecast_propability'] = 50 # factor which is used to multiply the summary of forecasted rain from WU (default = 50 which means only 50% of sum is used); e.g. 10 = 10%, 100 is 100%
#
#
days_overall = config['days_history'] + 1 + config['days_forecast'] # DO NOT CHANGE THIS
#
## end default settings

# Tune the water base to special situation and location
# default from OSPI is 4 mm
# for Germany and my garden, the grass needs 2 liters/sqm per day (mostly shadow in the grass)
# for 1 week (7 days) this means I need 2 liters * 7 days = 14 liter (mm) overall
# my irrigation time in OSPI program settings is adjusted to this:
# default irrigation time is tuned to sprinkler output; in my situation the sprinkler output is around 5 liter in 90 minutes
# which leads to around 3 hours per week, splitted to 2 runs per week each 90 minutes; which defaults to 100% of the needed waterlevel
config['water_base_per_day'] = 4 # Needed water (in liter(=mm) per sqm; default from OSPI is 4 mm; adjusted to personal situation

# END OF CONFIG PART ####################

###################################################################
def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise

# Add a new url to open the data entry page.
urls.extend(['/lwa',  'plugins.weather_level_adj.settings',
             '/lwj',  'plugins.weather_level_adj.settings_json',
             '/luwa', 'plugins.weather_level_adj.update'])

# Add this plugin to the home page plugins menu
gv.plugin_menu.append(['Weather-based Water Level', '/lwa'])

###################################################################
# Create the callbacks for Mosquitto
def on_connect(mosq, obj, rc):
    if rc == 0:
        logger.info("Connected to broker " + str(config['broker_address'] + ":" + str(config['broker_port'])))

        # Subscribe to device config
        logger.info("Subscribing to device config at " + config['config_topic'] + "/#")
        mqttclient.subscribe(config['config_topic'] + "/#")


def on_subscribe(mosq, obj, mid, granted_qos):
    logger.info("Subscribed with message ID " + str(mid) + " and QOS " + str(granted_qos) + " acknowledged by broker")


def on_message(mosq, obj, msg):
    logger.info("Received message: " + msg.topic + ":" + msg.payload)
    if msg.topic.startswith(config['config_topic']):
        configitem = msg.topic.split('/')[-1]
        if configitem in config:
            # unset when value set to ""
            logger.info("Setting configuration " + configitem + " to " + msg.payload)
            config[configitem] = msg.payload
        else:
            logger.info("Ignoring unknown configuration item " + configitem)


def on_publish(mosq, obj, mid):
    # logger.info("Published message with message ID: "+str(mid))
    pass

###########


# Create the Mosquitto client
mqttclient = paho.Client()

# Complete MQTT disabled feature is not yet implemented; setting this to "off" only disables the final payload publishing to the broker
#if config['auto_mqtt'] == "on":
# Bind the Mosquitte events to our event handlers
mqttclient.on_connect = on_connect
mqttclient.on_subscribe = on_subscribe
mqttclient.on_message = on_message
mqttclient.on_publish = on_publish
# Connect to the Mosquitto broker
logger.info("Connecting to broker " + config['broker_address'] + ":" + str(config['broker_port']))
mqttclient.connect(config['broker_address'], config['broker_port'], 60)
# Start the Mosquitto loop in a non-blocking way (uses threading)
mqttclient.loop_start()

time.sleep(5)


################################################################################
# Main function loop:                                                          #
################################################################################

class WeatherLevelChecker(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.daemon = True
        self.start()
        self.status = ''

        self._sleep_time = 0

    def add_status(self, msg):
        if self.status:
            self.status += '\n' + msg
        else:
            self.status = msg
        print msg

    def update(self):
        self._sleep_time = 0

    def _sleep(self, secs):
        self._sleep_time = secs
        while self._sleep_time > 0:
            time.sleep(1)
            self._sleep_time -= 1

    def run(self):
        time.sleep(randint(3, 10))  # Sleep some time to prevent printing before startup information

        while True:
            try:
                self.status = ''
                options = options_data()
		# populate default settings depending from modus the script is running
		if config['modus'] == "plugin":
			# replace default settings with values from json file
			## MQTT CONFIG
                        config['auto_mqtt'] = options["auto_mqtt"]
			config['broker_address'] = options["broker_address"]
			config['publish_topic'] = options["publish_topic"]
			## Wateroptions CONFIG
			config['wl_min'] = int(options["wl_min"])
			config['wl_max'] = int(options["wl_max"])
			config['water_base_per_day'] = int(options["water_base_per_day"])
			## Wunderground CONFIG
			config['days_history'] = int(options["days_history"])
			config['days_forecast'] = int(options["days_forecast"])
			config['days_overall'] = (config['days_history'] + 1 + config['days_forecast'])
                        config['wu_api_key'] = options["wapikey"]
			# added parameter
			config['updaterate'] = int(options["updaterate"])  
			config['country'] = options["country"]
			config['city'] = options["city"]
			config['stationid_HIST'] = options["stationid_HIST"] 
			config['stationid_FC'] = options["stationid_FC"] 
			config['stationid_FC_type'] = options["stationid_FC_type"] 
			config['rain_forecast_propability'] = int(options["rain_forecast_propability"])
			# end added
			## general settings
			days_overall = int(config['days_overall']) 


                if options["auto_wl"] == "off":
                    if 'wl_weather' in gv.sd:   # Master switch if script is enabled or not
                        del gv.sd['wl_weather'] # delete this value means script gets diabled
                else:
			###### START OF OLD PART
			print "Checking weather status..."
			logger.info("Overall days : " + str(days_overall))
			remove_data(['history_', 'conditions_', 'forecast10day_'])

                    	###### START OF NEW CHECK PART, complete new routine
			print "Get Wunderground History Data..."
			wunderground_get_weather_history()
			print "Get Wunderground Forecast Data..."
			wunderground_get_weather_forecast()
			
			# Prepare overall values for average and sum from history and forecast
			# Summarize Data Loop
			# we have to add one day to History which reflects the actual day
			days_history = config['days_history'] + 1
			days_forecast = config['days_forecast']

			# NEW
			# Overall sum of temperature and humidity (History and forecast) are calculated in sub-functions below
			# for effective average value we have to divide the overall sum by the amount of history and forecast days
                        temp_c = ((temp_HIST_sum + temp_FC_sum) / days_overall)
			humidity = (humidity_HIST_sum / days_history)
			# 
			rain_hist = precip_HIST_sum
			rain_fc = precip_FC_sum

			############## OLD #### Berechnung ueber feste Variablen, funktioniert nur wenn immer gleiche Anzahl von Tagen in History und Forecast
			#temp_c = (float(temperatureHIST3) + float(temperatureHIST4) + float(temperatureHIST5) + float(temperatureHIST6) + float(temperatureFC1) + float(temperatureFC2) + float(temperatureFC3))/7
                        #humidity = (float(humidityHIST3) + float(humidityHIST4) + float(humidityHIST5) + float(humidityHIST6))/4
			#rain_hist = float(precipitationHIST3) + float(precipitationHIST4) + float(precipitationHIST5) + float(precipitationHIST6)
			#rain_fc = float(precipitationFC1) + float(precipitationFC2) + float(precipitationFC3)

			# Forecast rain will be rated with a probability of 50 percent as default; can be changed in config part of the script
			rain_mm_org = rain_hist + rain_fc
			rain_mm = rain_hist + (rain_fc * (float(config['rain_forecast_propability']) / 100))
			# 
			logger.info('---------------------------------')
			logger.info('Results of weather check')
			logger.info('---------------------------------')
			logger.info("Temp Average  x days (Celsius):" + str(temp_c))
			logger.info("Hum. Average  x days (Percent):" + str(humidity))
			logger.info("Rain History       x days (mm):" + str(rain_hist))
			logger.info("Rain Forecast      x days (mm):" + str(rain_fc))
                        logger.info("Rain Total, unadjusted    (mm):" + str(rain_mm_org))
                        logger.info("Rain Prop. adjustment(percent):" + str(config['rain_forecast_propability']))
			logger.info("Rain Total, adjusted      (mm):" + str(rain_mm))
			logger.info('---------------------------------')
			logger.info('Calculation Adjustment starts')
			logger.info('---------------------------------')
			# We assume that the default 100% provides 4mm water per day (normal need)
			# We calculate what we will need to provide using the mean data of X days around today
			water_basis = config['water_base_per_day'] * days_overall  
			water_needed = config['water_base_per_day'] * days_overall # original: 4mm per day . adjusted HVF: adjustable via config, see comments in config section in program header
			logger.info('Water needed base: ' + str(water_needed))
			water_needed *= 1 + (temp_c - 20) / 15 # 5 => 0%, 35 => 200%, 20 degrees is reference temperature for 100% irrigation
			logger.info('Water needed after temp adjustment: ' + str(water_needed))
			#water_needed *= 1 + (wind_ms / 100) # 0 => 100%, 20 => 120%
			water_needed *= 1 - (humidity - 50) / 200 # 0 => 125%, 100 => 75%
			logger.info('Water needed after Humidity adjustment: ' + str(water_needed))
			water_needed = round(water_needed, 1)
			water_left = water_needed - rain_mm
			logger.info('Water left: needed - rain: ' + str(water_left))
			water_left = round(max(0, min(100, water_left)), 1)
			water_adjustment = round((water_left / (config['water_base_per_day'] * days_overall)) * 100, 1)  
			logger.info('Water adjustment before min/max: ' + str(water_adjustment))
			water_adjustment = max(float(config['wl_min']), min(float(config['wl_max']), water_adjustment)) # cap to limits (min/max) waterlevel, typically 0 - 200%
			logger.info('Water adjustment after min/max cap: ' + str(water_adjustment))
			logger.info('---------------------------------')
			logger.info('Results of Weather Adjustment')
			logger.info('---------------------------------')
			logger.info('Waterbasis (x days): %.1fmm' % water_basis) 
			logger.info('Average Temp : %.1fC' % temp_c)
			#logger.info('Average Wind : %.1fms' % wind_ms)
			logger.info('Average Humidity : %.1f%%' % humidity)
			logger.info('Water needed (x days): %.1fmm' % water_needed)
			logger.info('Total rainfall : %.1fmm' % rain_mm)
			logger.info('-------------------------------')
			logger.info('Irrigation needed : %.1fmm' % water_left)
			logger.info('Weather Adjustment   : %.1f%%' % water_adjustment)
			logger.info('-------------------------------')
			# Status messages for web-page
			self.add_status('Waterbasis %d mm(%d days)         : %.1fmm' % (config['water_base_per_day'], days_overall, water_basis))
			self.add_status('Average temperature             : %.1fC' % temp_c)
			#self.add_status('Average Wind : %.1fms' % wind_ms)
			self.add_status('Average humidity                : %.1f%%' % humidity)
			self.add_status('Water needed, adjusted (%d days) : %.1fmm' % (days_overall, water_needed))
                        self.add_status('Rainfall history&actual (%d days): %.1fmm' % (days_history, rain_hist))
                        self.add_status('Rainfall forecast (%d days)      : %.1fmm' % (days_forecast, rain_fc))
                        self.add_status('Total rainfall (mm)             : %.1fmm' % rain_mm_org)
			self.add_status('Total rainfall, adjusted        : %.1fmm' % rain_mm)
			self.add_status('--------------------------------------')
			self.add_status('Irrigation needed               : %.1fmm' % water_left)
			self.add_status('Weather Adjustment              : %.1f%%' % water_adjustment)

			################# submit waterlevl adjustment value from plugin to the OSPi (plugin data)
			### Here we go:
			gv.sd['wl_weather'] = water_adjustment
			###############################################################################
			
			# finally submit the waterlevl adjustment value: (directly to the OSPI and) publish to broker
			print "Sending waterlevel adjustment to the OSPI..."
			ospi_update_waterlevel(water_adjustment)
			
			print "Waiting for loop"
                 
			# programm loop: waits for new WU request for the given time (in seconds), defined in config part
			self._sleep(config['updaterate']) # default 3600 seconds which is 1 hour

            except Exception:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                err_string = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
                self.add_status('Weather-base water level encountered error:\n' + err_string)
                self._sleep(3600)
            time.sleep(0.5)

### back to Main function loop 
checker = WeatherLevelChecker()


################################################################################
# Web pages:                                                                   #
################################################################################

class settings(ProtectedPage):
    """Load an html page for entering weather-based irrigation adjustments"""

    def GET(self):
        return template_render.weather_level_adj(options_data())


class settings_json(ProtectedPage):
    """Returns plugin settings in JSON format"""

    def GET(self):
        web.header('Access-Control-Allow-Origin', '*')
        web.header('Content-Type', 'application/json')
        return json.dumps(options_data())


class update(ProtectedPage):
    """Save user input to weather_level_adj.json file"""
    def GET(self):
        qdict = web.input()
        if 'auto_wl' not in qdict:
            qdict['auto_wl'] = 'off'
        with open('./data/weather_level_adj.json', 'w') as f:  # write the settings to file
            json.dump(qdict, f)
        checker.update()
        raise web.seeother('/')


################################################################################
# Helper functions:                                                            #
################################################################################

# Read the plugin option settings from file
def options_data():
    # Defaults:
    result = {
        'auto_wl': 'off',
        'wl_min': 0,
        'wl_max': 200,
        'days_history': 3,
        'days_forecast': 3,
        'wapikey': '',
	# added
	'water_base_per_day': 4,
	'updaterate': 3600,
	'country': 'de-DE',
	'city': 'Duesseldorf',
	'stationid_HIST': 'INORDRHE570',
	'stationid_FC': 'EDDL',
	'stationid_FC_type': 'icaoCode',
	'rain_forecast_propability': 50,
        'auto_mqtt': 'off',
        'broker_address': '172.16.0.200',
        'publish_topic': 'vondefenn/home/weather/wu',
	# end added
        'status': checker.status
    }
    try:
        with open('./data/weather_level_adj.json', 'r') as f:  # Read the settings from file
            file_data = json.load(f)
        for key, value in file_data.iteritems():
            if key in result:
                result[key] = value
    except Exception:
        pass

    return result


# Resolve location to LID
## from old plugin; not used here anymore
def get_wunderground_lid():
    if re.search("pws:", gv.sd['loc']):
        lid = gv.sd['loc']
    else:
        data = urllib2.urlopen("http://autocomplete.wunderground.com/aq?h=0&query="+urllib.quote_plus(gv.sd['loc']))
        data = json.load(data)
        if data is None:
            return ""
        elif len(data['RESULTS']) == 0:
            return ""
        lid = "zmw:" + data['RESULTS'][0]['zmw']

    return lid

# get data from WU
## from old plugin; not used here anymore
def get_data(suffix, name=None, force=False):
    if name is None:
        name = suffix
    options = options_data()
    path = os.path.join('.', 'data', 'weather_level_history', name)
    directory = os.path.dirname(path)
    mkdir_p(directory)
    try_nr = 1
    while try_nr <= 2:
        try:
            if not os.path.exists(path) or force:
                with open(path, 'wb') as fh:
                    req = urllib2.urlopen("http://api.wunderground.com/api/"+options['wapikey']+"/" + suffix)
                    while True:
                        chunk = req.read(20480)
                        if not chunk:
                            break
                        fh.write(chunk)

            try:
                with file(path, 'r') as fh:
                    data = json.load(fh)
            except ValueError:
                raise Exception('Failed to read ' + path + '.')

            if data is not None:
                if 'error' in data['response']:
                    raise Exception(str(data['response']['error']))
            else:
                raise Exception('JSON decoding failed.')

            # If we made it here, we were successful, break
            break

        except Exception as err:
            if try_nr < 2:
                print str(err), 'Retrying.'
                os.remove(path)
                # If we had an exception, this is where we need to increase
                # our count retry
                try_nr += 1
            else:
                raise

    return data

# Remove old data
## from old plugin; not used here anymore
def remove_data(prefixes):
    # Delete old files
    for prefix in prefixes:
        check_date = datetime.date.today()
        start_delta = datetime.timedelta(days=14)
        day_delta = datetime.timedelta(days=1)
        check_date -= start_delta
        for index in range(60):
            datestring = check_date.strftime('%Y%m%d')
            path = os.path.join('.', 'data', 'weather_level_history', prefix + datestring)
            if os.path.isdir(path):
                shutil.rmtree(path)
            check_date -= day_delta


################################################################################
# Info queries:                                                                #
################################################################################

########### NEW Routines added here - HVF May 2019 ##########################
## Adopted to new WU API (V3) structure
## Included publishing via MQTT to a broker in parrallel
################################################################################
def wunderground_get_weather_history():
    if not config['wu_api_key'] or not config['country'] or not config['city'] or not config['publish_topic']:
        logger.info("Required configuration items not set, skipping the Weather Underground update")
        return

    # we start with the available history of last 7 days in the new WU api
    wu_url_hist = "http://api.weather.com/v2/pws/dailysummary/7day?stationId=" + config['stationid_HIST'] + "&format=json&units=m&apiKey=" + config['wu_api_key']
    logger.info("Getting Weather Underground data from " + wu_url_hist)

    try: 
        responseFC = urllib2.urlopen(wu_url_hist)
    except urllib2.URLError as e:
        logger.error('URLError: ' + str(wu_url_hist) + ': ' + str(e.reason))
        return None
    except Exception:
        import traceback
        logger.error('Exception: ' + traceback.format_exc())
        return None

    parsed_json = json.load(responseFC)
    responseFC.close()


    #### Read Data Block

    # new index-based routine here
    # we have to add one day to History which reflects the actual day
    days_history = config['days_history'] + 1

    # Initialize variables
    global temp_HIST_sum
    global humidity_HIST_sum
    global precip_HIST_sum
    temp_HIST_sum = 0
    humidity_HIST_sum = 0
    precip_HIST_sum = 0

    # from returned WU data we need only parts, depending on settings for number of history days. e.g. if history days = 3:
    # thereof we need only the last 3 days: index goes from 0 to 6, where 6 is the actual day; so wee need 3,4,5 and 6 for today
    for index in range(6, 6 - (days_history), -1):
        # it starts always with 6 (which is the actual day) and runs down until index of days_history is reached 
	# Temperature High
	# summarize values for later main calculation
	temp_HIST_sum += float(parsed_json['summaries'][index]['metric']['tempHigh'])
	# Dedicated variable for MQTT
       	globals()['temperatureHIST%s' % index] = str(parsed_json['summaries'][index]['metric']['tempHigh'])
	logger.info("History tempHigh: Day " + str(index) + " : " + str(parsed_json['summaries'][index]['metric']['tempHigh']))
	if config['auto_mqtt'] == "on":
		# Publish the values we parsed from the feed to the broker
		mqttclient.publish(config['publish_topic'] + "/temperature_HIST_" + str(index), str(parsed_json['summaries'][index]['metric']['tempHigh']), retain=False)
		
	# Humidity Average
	# summarize values for later main calculation
	humidity_HIST_sum += float(parsed_json['summaries'][index]['humidityAvg'])
	# Dedicated variable for MQTT
	globals()['humidityHIST%s' % index] = str(parsed_json['summaries'][index]['humidityAvg'])
	# TODO korrekte syntax fuer output der variable zusammengesetzt aus string und index 
	logger.info("History humidityAvg: Day " + str(index) + " : " + str(parsed_json['summaries'][index]['humidityAvg']))
	if config['auto_mqtt'] == "on":
		# Publish the values we parsed from the feed to the broker
		mqttclient.publish(config['publish_topic'] + "/humidity_HIST_" + str(index), str(parsed_json['summaries'][index]['humidityAvg']), retain=False)
		
	# Precipitation Total
	try:
		# NEW consistency check on reported rain amount. value must not be higher than e.g. 120mm
		precip_test = float(parsed_json['summaries'][index]['metric']['precipTotal'])
		if precip_test > 120:
			logger.info("Precipitation returned a too high - wrong value, replacing with '0'")
			globals()['precipitationHIST%s' % index] = str(0)
		else:
			# summarize values for later main calculation
			precip_HIST_sum += float(parsed_json['summaries'][index]['metric']['precipTotal'])
			# Dedicated variable for MQTT
			globals()['precipitationHIST%s' % index] = str(parsed_json['summaries'][index]['metric']['precipTotal'])
			# TODO korrekte syntax fuer output der variable zusammengesetzt aus string und index 
			logger.info("History precipTotal: Day " + str(index) + " : " + str(parsed_json['summaries'][index]['metric']['precipTotal']))
			if config['auto_mqtt'] == "on":
				# Publish the values we parsed from the feed to the broker
				mqttclient.publish(config['publish_topic'] + "/precipitation_HIST_" + str(index), str(parsed_json['summaries'][index]['metric']['precipTotal']), retain=False)
				logger.info("Published " + str(config['deviceid']) + " data to " + str(config['publish_topic']))
	except ValueError:
		logger.info("Precipitation returned a wrong value, replacing with '0'")
		globals()['precipitationHIST%s' % index] = str(0)

	# Debug test
	#logger.info("DEBUG: Temp HIST Sum  : " + str(temp_HIST_sum))
	#logger.info("DEBUG: Hum HIST Sum   : " + str(humidity_HIST_sum))
	#logger.info("DEBUG: Precip HIST Sum: " + str(precip_HIST_sum))
			
    result = {}

    ## we don't need more information for water base calculation


def wunderground_get_weather_forecast():
    if not config['wu_api_key'] or not config['country'] or not config['city'] or not config['publish_topic']:
        logger.info("Required configuration items not set, skipping the Weather Underground update")
        return

    # we continue with the forecast of next 5 days in the new WU api
    # Parse the WeatherUnderground json response
    wu_url_fc = "http://api.weather.com/v3/wx/forecast/daily/5day?" + config['stationid_FC_type'] + "=" + config['stationid_FC'] + "&units=m&language=" + config['country'] + "&format=json&apiKey=" + config['wu_api_key']
    logger.info("Getting Weather Underground Forecast data from " + wu_url_fc)

    try: 
        responseFC = urllib2.urlopen(wu_url_fc)
    except urllib2.URLError as e:
        logger.error('URLError: ' + str(wu_url_fc) + ': ' + str(e.reason))
        return None
    except Exception:
        import traceback
        logger.error('Exception: ' + traceback.format_exc())
        return None

    parsed_json = json.load(responseFC)
    responseFC.close()

    #### Read Data Block
	
    # new index-based routine here
    days_forecast = config['days_forecast']

    # Initialize variables
    global temp_FC_sum
    global precip_FC_sum
    temp_FC_sum = 0
    precip_FC_sum = 0

    # from returned WU data we need only parts, depending on settings for number of forecast days. e.g. if forecast days = 3:
    # thereof we need only the next 3 days: available index goes from 0 to 5, where 0 is the actual day (we use the data for actual day from history at EOD); so wee need 1,2,3
	
    for index in range(1, 1 + days_forecast, +1):
        # it starts always with 1 (which is the next day) and runs up until index of days_forecast 

        # Temperature Max
        # summarize values for later main calculation
        temp_FC_sum += float(parsed_json['temperatureMax'][index])
	# Dedicated variable for MQTT
        globals()['temperatureFC%s' % index] = str(parsed_json['temperatureMax'][index])
	logger.info("Forecast tempHigh: Day " + str(index) + " : " + str(parsed_json['temperatureMax'][index]))
	if config['auto_mqtt'] == "on":
		# Publish the values we parsed from the feed to the broker
		mqttclient.publish(config['publish_topic'] + "/temperature_FC_" + str(index), str(parsed_json['temperatureMax'][index]), retain=False)
		
	# precipTotal
	try:
	        # summarize values for later main calculation
		precip_FC_sum += float(parsed_json['qpf'][index])
		# Dedicated variable for MQTT
		globals()['precipitationFC%s' % index] =  str(int(parsed_json['qpf'][index]))
		# TODO korrekte syntax fuer output der variable zusammengesetzt aus string und index 
		logger.info("Forecast qpf: Day " + str(index) + " : " + str(parsed_json['qpf'][index]))
		if config['auto_mqtt'] == "on":
			# Publish the values we parsed from the feed to the broker
			mqttclient.publish(config['publish_topic'] + "/precipitation_FC_" + str(index), str(int(parsed_json['qpf'][index])), retain=False)
			logger.info("Published " + str(config['deviceid']) + " data to " + str(config['publish_topic']))
	except ValueError:
		logger.info("Precipitation returned a wrong value, replacing with '0'")
		globals()['precipitationFC%s' % index] = str(0)
		
	result = {}

	# Debug test
	#logger.info("DEBUG: Temp FC Sum  : " + str(temp_FC_sum))
	#logger.info("DEBUG: Precip FC Sum: " + str(precip_FC_sum))
    
    ## we don't need more information for water base calculation


def ospi_update_waterlevel(waterlevel):
    if not config['ospi_address'] or not config['ospi_passwd'] or not config['ospi_port']:
        logger.info("Required OSPI configuration items not set, skipping the OSPI waterlevel update")
        return

    if config['modus'] == "standalone":
	##############################################################
    	# OSPI address cal: http://<ip-adress>:><PORT>/cv?pw=<PASSWORD>&wl=<INT waterlevel in %>
    	##############################################################
    	######### THIS PART IS DISABLED in the plugin version! parse is done above in the main loop section
    	ospi_url = "http://" + config['ospi_address'] +":" + str(config['ospi_port']) + "/cv?pw=" + config['ospi_passwd'] + "&wl=" + str(int(waterlevel))
    	logger.info("Getting return feedback from OSPI update: " + config['ospi_address'] +":" + str(config['ospi_port']) + "/cv?pw=******" + "&wl=" + str(int(waterlevel)))

    	try:
    	    response_ospi = urllib2.urlopen(ospi_url)
    	except urllib2.URLError as e:
    	    logger.error('URLError: ' + str(ospi_url) + ': ' + str(e.reason))
    	    return None
    	except Exception:
    	    import traceback
    	    logger.error('Exception: ' + traceback.format_exc())
    	    return None

    	response_ospi.close()
    	logger.info("OK ! ... proceed with data publishing..")


    if config['auto_mqtt'] == "on":
	## Publish the waterlevel adjustment to the broker
	mqttclient.publish(config['publish_topic'] + "/water_level_adjustment", str(int(waterlevel)), retain=False)
	logger.info("Published " + str(config['deviceid']) + " data to " + str(config['publish_topic']))

############################ END INSERTED NEW ROUTINES ######################

##### BEGIN OLD FUNCTIONS, koennen wahrscheinlich geloescht werden wenn der neue Teil funktioniert! Keine weiteren Verweise mehr vorhanden
def history_info(obj):
    options = options_data()
    if int(options['days_history']) == 0:
        return {}

    lid = get_wunderground_lid()
    if lid == "":
        raise Exception('No Location ID found!')

    check_date = datetime.date.today()
    day_delta = datetime.timedelta(days=1)

    info = {}
    for index in range(-1, -1 - int(options['days_history']), -1):
        check_date -= day_delta
        datestring = check_date.strftime('%Y%m%d')
        request = "history_"+datestring+"/q/"+lid+".json"
        # Test geaendert
        #request = "history/q/"+lid+".json"
        # Test neu hinzugefuegt
        #name = "history_"+datestring+"/q/"+lid+".json"
        data = get_data(request)
        # Test geaendert
        #data = get_data(request, name, True)

        if data and len(data['history']['dailysummary']) > 0:
            info[index] = data['history']['dailysummary'][0]

    result = {}
    for index, day_info in info.iteritems():
        try:
            result[index] = {
                # .isdigit check disabled, da Wert mit Dezimalstellen in History anscheinend nicht als digit erkannt wird
                'temp_c': float(day_info['maxtempm']), #if day_info['maxtempm'].isdigit() else 0,
                'rain_mm': float(day_info['precipm']), #if day_info['precipm'].isdigit() else 0,
                'wind_ms': float(day_info['meanwindspdm']) / 3.6, #if day_info['meanwindspdm'].isdigit() else 0,
                'humidity': float(day_info['humidity']), #if day_info['humidity'].isdigit() else 0
            }
        except ValueError:
            obj.add_status("Skipped wundergound data because of a parsing error for %s" % day_info['date']['pretty'])
            continue

    return result

def today_info(obj):
    lid = get_wunderground_lid()
    if lid == "":
        raise Exception('No Location ID found!')

    datestring = datetime.date.today().strftime('%Y%m%d')

    request = "conditions/q/"+lid+".json"
    name = "conditions_"+datestring+"/q/"+lid+".json"
    data = get_data(request, name, True)

    day_info = data['current_observation']

    #!! hier wird anscheinend das Ergebnis von result durch [] auf 0 zurueck gesetzt?
    # auskommentieren oder mit {} versuchen
    result = {}
    #result = []
    try:
        result = {
            'temp_c': float(day_info['temp_c']),
            'rain_mm': float(day_info['precip_today_metric']),
            'wind_ms': float(day_info['wind_kph']) / 3.6,
            'humidity': float(day_info['relative_humidity'].replace('%', ''))
        }
    except ValueError:
        obj.add_status("Skipped wundergound data because of a parsing error for today")

    return result

def forecast_info(obj):
    options = options_data()

    lid = get_wunderground_lid()
    if lid == "":
        raise Exception('No Location ID found!')

    datestring = datetime.date.today().strftime('%Y%m%d')

    request = "forecast10day/q/"+lid+".json"
    name = "forecast10day_"+datestring+"/q/"+lid+".json"
    data = get_data(request, name)

    info = {}
    for day_index, entry in enumerate(data['forecast']['simpleforecast']['forecastday']):
        info[day_index] = entry

    result = {}
    for index, day_info in info.iteritems():
        if index <= int(options['days_forecast']):
            try:
                result[index] = {
                    'temp_c': float(day_info['high']['celsius']),
                    'rain_mm': float(day_info['qpf_allday']['mm']),
                    'wind_ms': float(day_info['avewind']['kph']) / 3.6,
                    'humidity': float(day_info['avehumidity'])
                }
            except ValueError:
                obj.add_status("Skipped wundergound data because of a parsing error for forecast day %s" % index)
                continue

    return result
