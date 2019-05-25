import logging
import requests
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
import time

from homeassistant.setup import setup_component
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.helpers.discovery import load_platform
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.util import slugify

DOMAIN = 'hass_opensprinkler'

VERSION = '0.1.2'

CONF_STATIONS = 'stations'
CONF_PROGRAMS = 'programs'
CONF_WATER_LEVEL = 'water_level'
CONF_LAST_RUN = 'last_run'
CONF_ENABLE_OPERATION = 'enable_operation'
CONF_RAIN_DELAY = 'rain_delay'
CONF_RAIN_DELAY_STOP_TIME = 'rain_delay_stop_time'
CONF_RAIN_SENSOR = 'rain_sensor'
CONF_CONFIG = 'config'

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel('DEBUG')

CONFIG_SCHEMA = vol.Schema({
  DOMAIN: vol.Schema({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_STATIONS, default=[]):
      vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional(CONF_PROGRAMS, default=[]):
      vol.All(cv.ensure_list, [vol.Coerce(int)]),
  })
}, extra=vol.ALLOW_EXTRA)

def setup(hass, config):
  host = config[DOMAIN].get(CONF_HOST)
  password = config[DOMAIN].get(CONF_PASSWORD)
  opensprinkler = Opensprinkler(host, password)
  stationIndexes = config[DOMAIN].get(CONF_STATIONS)

  hass.data[DOMAIN] = {
    DOMAIN: opensprinkler,
    CONF_CONFIG: {
      CONF_STATIONS: stationIndexes,
      CONF_PROGRAMS: config[DOMAIN].get(CONF_PROGRAMS),
    },
  }

  component = EntityComponent(_LOGGER, 'input_number', hass)
  inputNumberConfig = {'input_number': {}}
  for station in opensprinkler.stations():
    if len(stationIndexes) == 0 or (station.index in stationIndexes):
      object_id = '{}_timer'.format(slugify(station.name))
      name = station.name
      minimum = 1
      maximum = 10
      initial = 1
      step = 1
      unit = 'minutes'

      inputNumberConfig['input_number'][object_id] = {
        'min': minimum,
        'max': maximum,
        'name': name,
        'step': step,
        'initial': initial,
        'unit_of_measurement': unit,
      }

  setup_component(hass, 'input_number', inputNumberConfig)

  load_platform(hass, 'binary_sensor', DOMAIN, {}, config)
  load_platform(hass, 'sensor', DOMAIN, {}, config)
  load_platform(hass, 'scene', DOMAIN, {}, config)
  load_platform(hass, 'switch', DOMAIN, {}, config)

  return True


class Opensprinkler(object):
  """ API interface to OpenSprinkler

  For firmware API details, see
  https://openthings.freshdesk.com/support/solutions/articles/5000716363-os-api-documents
  """
  # minimum time interval between API calls in seconds
  MIN_API_INTERVAL = 60
    
  def __init__(self, host, password):
    self._host = host
    self._password = password
    self.data = {}
    #three caches are used to reduce API load:
    self.status_cache = {}
    self.controller_cache = {} 
    self.options_cache = {} 
    self.lock_cache = False
    self.timestamp_cache=0
    #initialize cache when Class is instantiated:
    self.update_cache()
    


  def update_cache(self):
    """ Fetches fresh data from Opensprinkler, but only if last call was at least
    MIN_API_INTERVAL seconds ago. Otherwise it just skips the update.
    """
    #locking is essential because Homeassistant spawns several worker-threads.
    if self.lock_cache == False:
      self.lock_cache = True

      if (time.time() - self.timestamp_cache) > Opensprinkler.MIN_API_INTERVAL:
        self.timestamp_cache = time.time()
        try:
          _LOGGER.debug('updating cache')
          #instead of querying one afer another, just get all info in one call
          url = 'http://{}/ja?pw={}'.format(self._host, self._password)
          self.response = requests.get(url, timeout=10)
          self.status_cache = self.response.json()['status']
          self.controller_cache = self.response.json()['settings']
          self.options_cache = self.response.json()['options']
        except requests.exceptions.ConnectionError:
          _LOGGER.error("No route to device '%s'", self._host)
      else:
        _LOGGER.debug('recycling data')
    
      self.lock_cache = False
      
    
  def stations(self):
    try:
      url = 'http://{}/jn?pw={}'.format(self._host, self._password)
      response = requests.get(url, timeout=10)
      _LOGGER.info("stations API")
    except requests.exceptions.ConnectionError:
      _LOGGER.error("No route to device '%s'", self._host)
    
    self.data[CONF_STATIONS] = []

    for i, name in enumerate(response.json()['snames']):
      self.data[CONF_STATIONS].append(OpensprinklerStation(self._host, self._password, name, i, self))

    return self.data[CONF_STATIONS]


  def programs(self):
    try:
      url = 'http://{}/jp?pw={}'.format(self._host, self._password)
      response = requests.get(url, timeout=10)
      _LOGGER.info("programs API")
    except requests.exceptions.ConnectionError:
      _LOGGER.error("No route to device '%s'", self._host)

    self.data[CONF_PROGRAMS] = []

    for i, data in enumerate(response.json()['pd']):
      self.data[CONF_PROGRAMS].append(OpensprinklerProgram(self._host, self._password, data[5], i))

    return self.data[CONF_PROGRAMS]

  def water_level(self):
    self.update_cache()
    return self.options_cache['wl']
    
  def last_run(self):
    self.update_cache()
    return self.controller_cache['lrun']

  def enable_operation(self):
    self.update_cache()
    return self.controller_cache['en']

  def rain_delay(self):
    self.update_cache()
    return self.controller_cache['rd']

  def rain_delay_stop_time(self):
    self.update_cache()
    return self.controller_cache['rdst']

  def rain_sensor(self):
    self.update_cache()
    return self.controller_cache['rs']


class OpensprinklerStation(object):

  def __init__(self, host, password, name, index, opensprinkler):
    self._host = host
    self._password = password
    self._name = name
    self._index = index
    self._opensprinkler = opensprinkler

  @property
  def name(self):
    return self._name

  @property
  def index(self):
    return self._index

  def status(self):
    self._opensprinkler.update_cache()
    return self._opensprinkler.status_cache['sn'][self._index]

  def p_status(self):
    self._opensprinkler.update_cache()
    return self._opensprinkler.controller_cache['ps'][self._index]

  def turn_on(self, minutes):
    try:
      url = 'http://{}/cm?pw={}&sid={}&en=1&t={}'.format(self._host, self._password, self._index, minutes * 60)
      response = requests.get(url, timeout=10)
      _LOGGER.debug("calling API: turn on/off")
    except requests.exceptions.ConnectionError:
      _LOGGER.error("No route to device '%s'", self._host)

  def turn_off(self):
    try:
      url = 'http://{}/cm?pw={}&sid={}&en=0'.format(self._host, self._password, self._index)
      response = requests.get(url, timeout=10)
      _LOGGER.debug("calling API: turn on/off")
    except requests.exceptions.ConnectionError:
      _LOGGER.error("No route to device '%s'", self._host)


class OpensprinklerProgram(object):

  def __init__(self, host, password, name, index):
    self._host = host
    self._password = password
    self._name = name
    self._index = index

  @property
  def name(self):
    return self._name

  @property
  def index(self):
    return self._index

  def activate(self):
    try:
      url = 'http://{}/mp?pw={}&pid={}&uwt=0'.format(self._host, self._password, self._index)
      response = requests.get(url, timeout=10)
      _LOGGER.debug("calling API: activate")
    except requests.exceptions.ConnectionError:
      _LOGGER.error("No route to device '%s'", self._host)
