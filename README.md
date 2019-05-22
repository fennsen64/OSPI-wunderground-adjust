OSPI-wunderground-adjust
Adjust the water-level on OpenSprinkler based on Weatherunderground data, migrated to new WU API (V3)
Version 1.3 - 22.05.2019 
All adjustments to the original OSPI included scripts (by Dan-in-CA) found on https://github.com/Dan-in-CA/SIP
     made by A. von de Fenn (fennsen) in May 2019. The code is under GPL licence.
Some parts of this code also includes portions from simonvanderveldt/mqtt-wunderground on GITHUB

Attention: This script is only valid and useable for the python version of the Opensprinkler Board ('OSPi', also as newer versions called 'SIP'),
  which means the Raspberry Version of the program, not the microcode version It is a direct replacement for the available default plugin 'WEATHER-BASED WATER LEVEL' (see and activate under 'PLUGINS', 
 weather_level_adj) and ads an MQTT functionality on top It calculates a percentage value and adds this as parameter "wl_weather" into the data-file './OSPI/data/sd.json

if the plugin is activated in the plugin section (see parameter "auto_wl": "on" in the config file  "weather_level_adj.json",
   it multiplies the main water level (normally 100%) with the value of wl_weather (e.g. 100% * 120%) and adjusts the programs running time to the appropriate level (e.g. 100% = 60 minutes run time is  given as default, it goes to 120% run time which is +12 minutes (+20%): 72 minutes 

# Hint: you can enable or disable this weather-based adjustment in the STATIONS menu per station. This is useful if you 
# have stations/programms who should always run with the given main
#  'Water Level' without the plugin adjustments

# Installation: This version needs JSON and the PAHO-MQTT client
  1. Install json and the paho-mqtt client via npm on the raspberry
  2. copy this script into the plugin directory of your OSPI installation e.g. /home/pi/OSPI/plugins the script must have the executeable bit
  3. copy the html page to the templates directory e.g. /home/pi/OSPI/templates
  4. open plugin menu via the OSPI webpage and adjust parameters. Activate the plugin
 
# Configuration: 
 Please be aware that the config parameters for the 'standalone' modus are set via editing the script file.
 Config parameters for the 'plugin' modus are set via the plugin website. Initial values are included in the config section, but will be overwritten with the first usage per plugin website

 Default days for the calculation is a complete week (3 days history + actual day + 3 days forecast). You can adjust this in the plugin settings.
  Wunderground API available history data are the last 7 days, thereof the fist value '6' is always the actual day
  Wunderground API available forecast data are 5 days, thereof the fist value '0' is the actual day (not used, taken from history which reflects the AS-IS from today) and '1' is always tomorrow
 
# As variant is also possible to run this script on an other server (completely independent from OSPI) and to update water data via normal HTTP GET call to the OSPI's API. 
In this case, the weather-adjustment is made to the main-parameter 'Water Level' (see parameter "wl": xxx) in the config-file sd.json
 To enable this alternative,
  you've to set the parameter config['modus'] = "standalone" in the script header. This disables all definitions and statements who refers to the local web-instance (eg. import web, import gv).
 
# Environment:
  tested under python2.7, OSPI version 3.1.46 (2016-04-30)

# Change log 
# Version 1.1 
  Added description and installation documentation 
  NEW Probability factor - how the sum of forecasted rain from WU is used in calculation - included as config-parameter
# Version 1.2
  NEW consistency check on reported history rain amount. value must not be higher than e.g. 120mm
# Version 1.3
  Configuration via plugin website (adjusted) are implemented

