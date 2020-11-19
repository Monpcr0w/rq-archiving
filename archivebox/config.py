__package__ = 'archivebox'

import os
import io
import re
import sys
import json
import getpass
import shutil
import django

from hashlib import md5
from pathlib import Path
from typing import Optional, Type, Tuple, Dict, Union, List
from subprocess import run, PIPE, DEVNULL
from configparser import ConfigParser
from collections import defaultdict

from .config_stubs import (
    SimpleConfigValueDict,
    ConfigValue,
    ConfigDict,
    ConfigDefaultValue,
    ConfigDefaultDict,
)

# precedence order for config:
# 1. cli args                 (e.g. )
# 2. shell environment vars   (env USE_COLOR=False archivebox add '...')
# 3. config file              (echo "SAVE_FAVICON=False" >> ArchiveBox.conf)
# 4. defaults                 (defined below in Python)

#
# env SHOW_PROGRESS=1 archivebox add '...'
# archivebox config --set TIMEOUT=600
# 

# ******************************************************************************
# Documentation: https://github.com/pirate/ArchiveBox/wiki/Configuration
# Use the 'env' command to pass config options to ArchiveBox.  e.g.:
#     env USE_COLOR=True CHROME_BINARY=chromium archivebox add < example.html
# ******************************************************************************

################################# User Config ##################################

CONFIG_DEFAULTS: Dict[str, ConfigDefaultDict] = {
    'SHELL_CONFIG': {
        'IS_TTY':                   {'type': bool,  'default': lambda _: sys.stdout.isatty()},
        'USE_COLOR':                {'type': bool,  'default': lambda c: c['IS_TTY']},
        'SHOW_PROGRESS':            {'type': bool,  'default': lambda c: c['IS_TTY']},
        'IN_DOCKER':                {'type': bool,  'default': False},
        # TODO: 'SHOW_HINTS':       {'type:  bool,  'default': True},
    },

    'GENERAL_CONFIG': {
        'OUTPUT_DIR':               {'type': str,   'default': None},
        'CONFIG_FILE':              {'type': str,   'default': None},
        'ONLY_NEW':                 {'type': bool,  'default': True},
        'TIMEOUT':                  {'type': int,   'default': 60},
        'MEDIA_TIMEOUT':            {'type': int,   'default': 3600},
        'OUTPUT_PERMISSIONS':       {'type': str,   'default': '755'},
        'RESTRICT_FILE_NAMES':      {'type': str,   'default': 'windows'},
        'URL_BLACKLIST':            {'type': str,   'default': r'\.(css|js|otf|ttf|woff|woff2|gstatic\.com|googleapis\.com/css)(\?.*)?$'},  # to avoid downloading code assets as their own pages
    },

    'SERVER_CONFIG': {
        'SECRET_KEY':               {'type': str,   'default': None},
        'BIND_ADDR':                {'type': str,   'default': lambda c: ['127.0.0.1:8000', '0.0.0.0:8000'][c['IN_DOCKER']]},
        'ALLOWED_HOSTS':            {'type': str,   'default': '*'},
        'DEBUG':                    {'type': bool,  'default': False},
        'PUBLIC_INDEX':             {'type': bool,  'default': True},
        'PUBLIC_SNAPSHOTS':         {'type': bool,  'default': True},
        'PUBLIC_ADD_VIEW':          {'type': bool,  'default': False},
        'FOOTER_INFO':              {'type': str,   'default': 'Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.'},
        'ACTIVE_THEME':             {'type': str,   'default': 'default'},
    },

    'ARCHIVE_METHOD_TOGGLES': {
        'SAVE_TITLE':               {'type': bool,  'default': True, 'aliases': ('FETCH_TITLE',)},
        'SAVE_FAVICON':             {'type': bool,  'default': True, 'aliases': ('FETCH_FAVICON',)},
        'SAVE_WGET':                {'type': bool,  'default': True, 'aliases': ('FETCH_WGET',)},
        'SAVE_WGET_REQUISITES':     {'type': bool,  'default': True, 'aliases': ('FETCH_WGET_REQUISITES',)},
        'SAVE_SINGLEFILE':          {'type': bool,  'default': True, 'aliases': ('FETCH_SINGLEFILE',)},
        'SAVE_READABILITY':         {'type': bool,  'default': True, 'aliases': ('FETCH_READABILITY',)},
        'SAVE_MERCURY':             {'type': bool,  'default': True, 'aliases': ('FETCH_MERCURY',)},
        'SAVE_PDF':                 {'type': bool,  'default': True, 'aliases': ('FETCH_PDF',)},
        'SAVE_SCREENSHOT':          {'type': bool,  'default': True, 'aliases': ('FETCH_SCREENSHOT',)},
        'SAVE_DOM':                 {'type': bool,  'default': True, 'aliases': ('FETCH_DOM',)},
        'SAVE_HEADERS':             {'type': bool,  'default': True, 'aliases': ('FETCH_HEADERS',)},
        'SAVE_WARC':                {'type': bool,  'default': True, 'aliases': ('FETCH_WARC',)},
        'SAVE_GIT':                 {'type': bool,  'default': True, 'aliases': ('FETCH_GIT',)},
        'SAVE_MEDIA':               {'type': bool,  'default': True, 'aliases': ('FETCH_MEDIA',)},
        'SAVE_ARCHIVE_DOT_ORG':     {'type': bool,  'default': True, 'aliases': ('SUBMIT_ARCHIVE_DOT_ORG',)},
    },

    'ARCHIVE_METHOD_OPTIONS': {
        'RESOLUTION':               {'type': str,   'default': '1440,2000', 'aliases': ('SCREENSHOT_RESOLUTION',)},
        'GIT_DOMAINS':              {'type': str,   'default': 'github.com,bitbucket.org,gitlab.com'},
        'CHECK_SSL_VALIDITY':       {'type': bool,  'default': True},

        'CURL_USER_AGENT':          {'type': str,   'default': 'ArchiveBox/{VERSION} (+https://github.com/pirate/ArchiveBox/) curl/{CURL_VERSION}'},
        'WGET_USER_AGENT':          {'type': str,   'default': 'ArchiveBox/{VERSION} (+https://github.com/pirate/ArchiveBox/) wget/{WGET_VERSION}'},
        'CHROME_USER_AGENT':        {'type': str,   'default': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.75 Safari/537.36'},

        'COOKIES_FILE':             {'type': str,   'default': None},
        'CHROME_USER_DATA_DIR':     {'type': str,   'default': None},

        'CHROME_HEADLESS':          {'type': bool,  'default': True},
        'CHROME_SANDBOX':           {'type': bool,  'default': lambda c: not c['IN_DOCKER']},
        'YOUTUBEDL_ARGS':           {'type': list,  'default': ['--write-description',
                                                                '--write-info-json',
                                                                '--write-annotations',
                                                                '--write-thumbnail',
                                                                '--no-call-home',
                                                                '--user-agent',
                                                                '--all-subs',
                                                                '--extract-audio',
                                                                '--keep-video',
                                                                '--ignore-errors',
                                                                '--geo-bypass',
                                                                '--audio-format', 'mp3',
                                                                '--audio-quality', '320K',
                                                                '--embed-thumbnail',
                                                                '--add-metadata']},

        'WGET_ARGS':                {'type': list,  'default': ['--no-verbose',
                                                                '--adjust-extension',
                                                                '--convert-links',
                                                                '--force-directories',
                                                                '--backup-converted',
                                                                '--span-hosts',
                                                                '--no-parent',
                                                                '-e', 'robots=off',
                                                                ]},
        'CURL_ARGS':                {'type': list,  'default': ['--silent',
                                                                '--location',
                                                                '--compressed'
                                                               ]},
        'GIT_ARGS':                 {'type': list,  'default': ['--recursive']},
    },

    'SEARCH_BACKEND_CONFIG' : {
        'USE_INDEXING_BACKEND':     {'type': bool,  'default': True},
        'USE_SEARCHING_BACKEND':    {'type': bool,  'default': True},
        'SEARCH_BACKEND_ENGINE':    {'type': str,   'default': 'sonic'},
        'SEARCH_BACKEND_HOST_NAME': {'type': str,   'default': 'localhost'},
        'SEARCH_BACKEND_PORT':      {'type': int,   'default': 1491},
        'SEARCH_BACKEND_PASSWORD':  {'type': str,   'default': 'SecretPassword'},
        # SONIC
        'SONIC_COLLECTION':         {'type': str,   'default': 'archivebox'},
        'SONIC_BUCKET':             {'type': str,   'default': 'snapshots'},
    },

    'DEPENDENCY_CONFIG': {
        'USE_CURL':                 {'type': bool,  'default': True},
        'USE_WGET':                 {'type': bool,  'default': True},
        'USE_SINGLEFILE':           {'type': bool,  'default': True},
        'USE_READABILITY':          {'type': bool,  'default': True},
        'USE_MERCURY':              {'type': bool,  'default': True},
        'USE_GIT':                  {'type': bool,  'default': True},
        'USE_CHROME':               {'type': bool,  'default': True},
        'USE_NODE':                 {'type': bool,  'default': True},
        'USE_YOUTUBEDL':            {'type': bool,  'default': True},
        
        'CURL_BINARY':              {'type': str,   'default': 'curl'},
        'GIT_BINARY':               {'type': str,   'default': 'git'},
        'WGET_BINARY':              {'type': str,   'default': 'wget'},
        'SINGLEFILE_BINARY':        {'type': str,   'default': 'single-file'},
        'READABILITY_BINARY':       {'type': str,   'default': 'readability-extractor'},
        'MERCURY_BINARY':           {'type': str,   'default': 'mercury-parser'},
        'YOUTUBEDL_BINARY':         {'type': str,   'default': 'youtube-dl'},
        'CHROME_BINARY':            {'type': str,   'default': None},
    },
}

# for backwards compatibility with old config files, check old/deprecated names for each key
CONFIG_ALIASES = {
    alias: key
    for section in CONFIG_DEFAULTS.values()
        for key, default in section.items()
            for alias in default.get('aliases', ())
}
USER_CONFIG = {key for section in CONFIG_DEFAULTS.values() for key in section.keys()}

def get_real_name(key: str) -> str:
    return CONFIG_ALIASES.get(key.upper().strip(), key.upper().strip())

############################## Derived Config ##############################

# Constants

DEFAULT_CLI_COLORS = {
    'reset': '\033[00;00m',
    'lightblue': '\033[01;30m',
    'lightyellow': '\033[01;33m',
    'lightred': '\033[01;35m',
    'red': '\033[01;31m',
    'green': '\033[01;32m',
    'blue': '\033[01;34m',
    'white': '\033[01;37m',
    'black': '\033[01;30m',
}
ANSI = {k: '' for k in DEFAULT_CLI_COLORS.keys()}

COLOR_DICT = defaultdict(lambda: [(0, 0, 0), (0, 0, 0)], {
    '00': [(0, 0, 0), (0, 0, 0)],
    '30': [(0, 0, 0), (0, 0, 0)],
    '31': [(255, 0, 0), (128, 0, 0)],
    '32': [(0, 200, 0), (0, 128, 0)],
    '33': [(255, 255, 0), (128, 128, 0)],
    '34': [(0, 0, 255), (0, 0, 128)],
    '35': [(255, 0, 255), (128, 0, 128)],
    '36': [(0, 255, 255), (0, 128, 128)],
    '37': [(255, 255, 255), (255, 255, 255)],
})

STATICFILE_EXTENSIONS = {
    # 99.999% of the time, URLs ending in these extensions are static files
    # that can be downloaded as-is, not html pages that need to be rendered
    'gif', 'jpeg', 'jpg', 'png', 'tif', 'tiff', 'wbmp', 'ico', 'jng', 'bmp',
    'svg', 'svgz', 'webp', 'ps', 'eps', 'ai',
    'mp3', 'mp4', 'm4a', 'mpeg', 'mpg', 'mkv', 'mov', 'webm', 'm4v', 
    'flv', 'wmv', 'avi', 'ogg', 'ts', 'm3u8',
    'pdf', 'txt', 'rtf', 'rtfd', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx',
    'atom', 'rss', 'css', 'js', 'json',
    'dmg', 'iso', 'img',
    'rar', 'war', 'hqx', 'zip', 'gz', 'bz2', '7z',

    # Less common extensions to consider adding later
    # jar, swf, bin, com, exe, dll, deb
    # ear, hqx, eot, wmlc, kml, kmz, cco, jardiff, jnlp, run, msi, msp, msm, 
    # pl pm, prc pdb, rar, rpm, sea, sit, tcl tk, der, pem, crt, xpi, xspf,
    # ra, mng, asx, asf, 3gpp, 3gp, mid, midi, kar, jad, wml, htc, mml

    # These are always treated as pages, not as static files, never add them:
    # html, htm, shtml, xhtml, xml, aspx, php, cgi
}

PACKAGE_DIR_NAME = 'archivebox'
TEMPLATES_DIR_NAME = 'themes'

ARCHIVE_DIR_NAME = 'archive'
SOURCES_DIR_NAME = 'sources'
LOGS_DIR_NAME = 'logs'
STATIC_DIR_NAME = 'static'
SQL_INDEX_FILENAME = 'index.sqlite3'
JSON_INDEX_FILENAME = 'index.json'
HTML_INDEX_FILENAME = 'index.html'
ROBOTS_TXT_FILENAME = 'robots.txt'
FAVICON_FILENAME = 'favicon.ico'
CONFIG_FILENAME = 'ArchiveBox.conf'

CONFIG_HEADER = (
"""# This is the config file for your ArchiveBox collection.
#
# You can add options here manually in INI format, or automatically by running:
#    archivebox config --set KEY=VALUE
# 
# If you modify this file manually, make sure to update your archive after by running:
#    archivebox init
#
# A list of all possible config with documentation and examples can be found here:
#    https://github.com/pirate/ArchiveBox/wiki/Configuration

""")


DERIVED_CONFIG_DEFAULTS: ConfigDefaultDict = {
    'TERM_WIDTH':               {'default': lambda c: lambda: shutil.get_terminal_size((100, 10)).columns},
    'USER':                     {'default': lambda c: getpass.getuser() or os.getlogin()},
    'ANSI':                     {'default': lambda c: DEFAULT_CLI_COLORS if c['USE_COLOR'] else {k: '' for k in DEFAULT_CLI_COLORS.keys()}},

    'PACKAGE_DIR':              {'default': lambda c: Path(__file__).resolve().parent},
    'TEMPLATES_DIR':            {'default': lambda c: c['PACKAGE_DIR'] / TEMPLATES_DIR_NAME / 'legacy'},

    'OUTPUT_DIR':               {'default': lambda c: Path(c['OUTPUT_DIR']).resolve() if c['OUTPUT_DIR'] else Path(os.curdir).resolve()},
    'ARCHIVE_DIR':              {'default': lambda c: c['OUTPUT_DIR'] / ARCHIVE_DIR_NAME},
    'SOURCES_DIR':              {'default': lambda c: c['OUTPUT_DIR'] / SOURCES_DIR_NAME},
    'LOGS_DIR':                 {'default': lambda c: c['OUTPUT_DIR'] / LOGS_DIR_NAME},
    'CONFIG_FILE':              {'default': lambda c: Path(c['CONFIG_FILE']).resolve() if c['CONFIG_FILE'] else c['OUTPUT_DIR'] / CONFIG_FILENAME},
    'COOKIES_FILE':             {'default': lambda c: c['COOKIES_FILE'] and Path(c['COOKIES_FILE']).resolve()},
    'CHROME_USER_DATA_DIR':     {'default': lambda c: find_chrome_data_dir() if c['CHROME_USER_DATA_DIR'] is None else (Path(c['CHROME_USER_DATA_DIR']).resolve() if c['CHROME_USER_DATA_DIR'] else None)},   # None means unset, so we autodetect it with find_chrome_Data_dir(), but emptystring '' means user manually set it to '', and we should store it as None
    'URL_BLACKLIST_PTN':        {'default': lambda c: c['URL_BLACKLIST'] and re.compile(c['URL_BLACKLIST'] or '', re.IGNORECASE | re.UNICODE | re.MULTILINE)},

    'ARCHIVEBOX_BINARY':        {'default': lambda c: sys.argv[0]},
    'VERSION':                  {'default': lambda c: json.loads((Path(c['PACKAGE_DIR']) / 'package.json').read_text().strip())['version']},
    'GIT_SHA':                  {'default': lambda c: c['VERSION'].split('+')[-1] or 'unknown'},

    'PYTHON_BINARY':            {'default': lambda c: sys.executable},
    'PYTHON_ENCODING':          {'default': lambda c: sys.stdout.encoding.upper()},
    'PYTHON_VERSION':           {'default': lambda c: '{}.{}.{}'.format(*sys.version_info[:3])},

    'DJANGO_BINARY':            {'default': lambda c: django.__file__.replace('__init__.py', 'bin/django-admin.py')},
    'DJANGO_VERSION':           {'default': lambda c: '{}.{}.{} {} ({})'.format(*django.VERSION)},

    'USE_CURL':                 {'default': lambda c: c['USE_CURL'] and (c['SAVE_FAVICON'] or c['SAVE_TITLE'] or c['SAVE_ARCHIVE_DOT_ORG'])},
    'CURL_VERSION':             {'default': lambda c: bin_version(c['CURL_BINARY']) if c['USE_CURL'] else None},
    'CURL_USER_AGENT':          {'default': lambda c: c['CURL_USER_AGENT'].format(**c)},
    'CURL_ARGS':                {'default': lambda c: c['CURL_ARGS'] or []},
    'SAVE_FAVICON':             {'default': lambda c: c['USE_CURL'] and c['SAVE_FAVICON']},
    'SAVE_ARCHIVE_DOT_ORG':     {'default': lambda c: c['USE_CURL'] and c['SAVE_ARCHIVE_DOT_ORG']},

    'USE_WGET':                 {'default': lambda c: c['USE_WGET'] and (c['SAVE_WGET'] or c['SAVE_WARC'])},
    'WGET_VERSION':             {'default': lambda c: bin_version(c['WGET_BINARY']) if c['USE_WGET'] else None},
    'WGET_AUTO_COMPRESSION':    {'default': lambda c: wget_supports_compression(c) if c['USE_WGET'] else False},
    'WGET_USER_AGENT':          {'default': lambda c: c['WGET_USER_AGENT'].format(**c)},
    'SAVE_WGET':                {'default': lambda c: c['USE_WGET'] and c['SAVE_WGET']},
    'SAVE_WARC':                {'default': lambda c: c['USE_WGET'] and c['SAVE_WARC']},
    'WGET_ARGS':                {'default': lambda c: c['WGET_ARGS'] or []},

    'USE_SINGLEFILE':           {'default': lambda c: c['USE_SINGLEFILE'] and c['SAVE_SINGLEFILE']},
    'SINGLEFILE_VERSION':       {'default': lambda c: bin_version(c['SINGLEFILE_BINARY']) if c['USE_SINGLEFILE'] else None},

    'USE_READABILITY':          {'default': lambda c: c['USE_READABILITY'] and c['SAVE_READABILITY']},
    'READABILITY_VERSION':      {'default': lambda c: bin_version(c['READABILITY_BINARY']) if c['USE_READABILITY'] else None},

    'USE_MERCURY':              {'default': lambda c: c['USE_MERCURY'] and c['SAVE_MERCURY']},
    'MERCURY_VERSION':          {'default': lambda c: '1.0.0' if (c['USE_MERCURY'] and c['MERCURY_BINARY']) else None},  # mercury is unversioned

    'USE_GIT':                  {'default': lambda c: c['USE_GIT'] and c['SAVE_GIT']},
    'GIT_VERSION':              {'default': lambda c: bin_version(c['GIT_BINARY']) if c['USE_GIT'] else None},
    'SAVE_GIT':                 {'default': lambda c: c['USE_GIT'] and c['SAVE_GIT']},

    'USE_YOUTUBEDL':            {'default': lambda c: c['USE_YOUTUBEDL'] and c['SAVE_MEDIA']},
    'YOUTUBEDL_VERSION':        {'default': lambda c: bin_version(c['YOUTUBEDL_BINARY']) if c['USE_YOUTUBEDL'] else None},
    'SAVE_MEDIA':               {'default': lambda c: c['USE_YOUTUBEDL'] and c['SAVE_MEDIA']},
    'YOUTUBEDL_ARGS':           {'default': lambda c: c['YOUTUBEDL_ARGS'] or []},

    'USE_CHROME':               {'default': lambda c: c['USE_CHROME'] and (c['SAVE_PDF'] or c['SAVE_SCREENSHOT'] or c['SAVE_DOM'] or c['SAVE_SINGLEFILE'])},
    'CHROME_BINARY':            {'default': lambda c: c['CHROME_BINARY'] if c['CHROME_BINARY'] else find_chrome_binary()},
    'CHROME_VERSION':           {'default': lambda c: bin_version(c['CHROME_BINARY']) if c['USE_CHROME'] else None},
    'USE_NODE':                 {'default': lambda c: c['USE_NODE'] and (c['SAVE_READABILITY'] or c['SAVE_SINGLEFILE'])},
    'SAVE_PDF':                 {'default': lambda c: c['USE_CHROME'] and c['SAVE_PDF']},
    'SAVE_SCREENSHOT':          {'default': lambda c: c['USE_CHROME'] and c['SAVE_SCREENSHOT']},
    'SAVE_DOM':                 {'default': lambda c: c['USE_CHROME'] and c['SAVE_DOM']},
    'SAVE_SINGLEFILE':          {'default': lambda c: c['USE_CHROME'] and c['SAVE_SINGLEFILE'] and c['USE_NODE']},
    'SAVE_READABILITY':         {'default': lambda c: c['USE_READABILITY'] and c['USE_NODE']},
    'SAVE_MERCURY':             {'default': lambda c: c['USE_MERCURY'] and c['USE_NODE']},

    'DEPENDENCIES':             {'default': lambda c: get_dependency_info(c)},
    'CODE_LOCATIONS':           {'default': lambda c: get_code_locations(c)},
    'EXTERNAL_LOCATIONS':       {'default': lambda c: get_external_locations(c)},
    'DATA_LOCATIONS':           {'default': lambda c: get_data_locations(c)},
    'CHROME_OPTIONS':           {'default': lambda c: get_chrome_info(c)},
}



################################### Helpers ####################################

def load_config_val(key: str,
                    default: ConfigDefaultValue=None,
                    type: Optional[Type]=None,
                    aliases: Optional[Tuple[str, ...]]=None,
                    config: Optional[ConfigDict]=None,
                    env_vars: Optional[os._Environ]=None,
                    config_file_vars: Optional[Dict[str, str]]=None) -> ConfigValue:
    """parse bool, int, and str key=value pairs from env"""


    config_keys_to_check = (key, *(aliases or ()))
    for key in config_keys_to_check:
        if env_vars:
            val = env_vars.get(key)
            if val:
                break
        if config_file_vars:
            val = config_file_vars.get(key)
            if val:
                break

    if type is None or val is None:
        if callable(default):
            assert isinstance(config, dict)
            return default(config)

        return default

    elif type is bool:
        if val.lower() in ('true', 'yes', '1'):
            return True
        elif val.lower() in ('false', 'no', '0'):
            return False
        else:
            raise ValueError(f'Invalid configuration option {key}={val} (expected a boolean: True/False)') 

    elif type is str:
        if val.lower() in ('true', 'false', 'yes', 'no', '1', '0'):
            raise ValueError(f'Invalid configuration option {key}={val} (expected a string)')
        return val.strip()

    elif type is int:
        if not val.isdigit():
            raise ValueError(f'Invalid configuration option {key}={val} (expected an integer)')
        return int(val)

    elif type is list:
        return json.loads(val)

    raise Exception('Config values can only be str, bool, int or json')


def load_config_file(out_dir: str=None) -> Optional[Dict[str, str]]:
    """load the ini-formatted config file from OUTPUT_DIR/Archivebox.conf"""

    out_dir = out_dir or Path(os.getenv('OUTPUT_DIR', '.')).resolve()
    config_path = Path(out_dir) / CONFIG_FILENAME
    if config_path.exists():
        config_file = ConfigParser()
        config_file.optionxform = str 
        config_file.read(config_path)
        # flatten into one namespace
        config_file_vars = {
            key.upper(): val
            for section, options in config_file.items()
                for key, val in options.items()
        }
        # print('[i] Loaded config file', os.path.abspath(config_path))
        # print(config_file_vars)
        return config_file_vars
    return None


def write_config_file(config: Dict[str, str], out_dir: str=None) -> ConfigDict:
    """load the ini-formatted config file from OUTPUT_DIR/Archivebox.conf"""

    from .system import atomic_write

    out_dir = out_dir or Path(os.getenv('OUTPUT_DIR', '.')).resolve()
    config_path = Path(out_dir) /  CONFIG_FILENAME
    
    if not config_path.exists():
        atomic_write(config_path, CONFIG_HEADER)

    config_file = ConfigParser()
    config_file.optionxform = str
    config_file.read(config_path)

    with open(config_path, 'r') as old:
        atomic_write(f'{config_path}.bak', old.read())

    find_section = lambda key: [name for name, opts in CONFIG_DEFAULTS.items() if key in opts][0]

    # Set up sections in empty config file
    for key, val in config.items():
        section = find_section(key)
        if section in config_file:
            existing_config = dict(config_file[section])
        else:
            existing_config = {}
        config_file[section] = {**existing_config, key: val}

    # always make sure there's a SECRET_KEY defined for Django
    existing_secret_key = None
    if 'SERVER_CONFIG' in config_file and 'SECRET_KEY' in config_file['SERVER_CONFIG']:
        existing_secret_key = config_file['SERVER_CONFIG']['SECRET_KEY']

    if (not existing_secret_key) or ('not a valid secret' in existing_secret_key):
        from django.utils.crypto import get_random_string
        chars = 'abcdefghijklmnopqrstuvwxyz0123456789-_+!.'
        random_secret_key = get_random_string(50, chars)
        if 'SERVER_CONFIG' in config_file:
            config_file['SERVER_CONFIG']['SECRET_KEY'] = random_secret_key
        else:
            config_file['SERVER_CONFIG'] = {'SECRET_KEY': random_secret_key}

    with open(config_path, 'w+') as new:
        config_file.write(new)
    
    try:
        # validate the config by attempting to re-parse it
        CONFIG = load_all_config()
        return {
            key.upper(): CONFIG.get(key.upper())
            for key in config.keys()
        }
    except:
        # something went horribly wrong, rever to the previous version
        with open(f'{config_path}.bak', 'r') as old:
            atomic_write(config_path, old.read())

    if Path(f'{config_path}.bak').exists():
        os.remove(f'{config_path}.bak')

    return {}

   

def load_config(defaults: ConfigDefaultDict,
                config: Optional[ConfigDict]=None,
                out_dir: Optional[str]=None,
                env_vars: Optional[os._Environ]=None,
                config_file_vars: Optional[Dict[str, str]]=None) -> ConfigDict:
    
    env_vars = env_vars or os.environ
    config_file_vars = config_file_vars or load_config_file(out_dir=out_dir)

    extended_config: ConfigDict = config.copy() if config else {}
    for key, default in defaults.items():
        try:
            extended_config[key] = load_config_val(
                key,
                default=default['default'],
                type=default.get('type'),
                aliases=default.get('aliases'),
                config=extended_config,
                env_vars=env_vars,
                config_file_vars=config_file_vars,
            )
        except KeyboardInterrupt:
            raise SystemExit(0)
        except Exception as e:
            stderr()
            stderr(f'[X] Error while loading configuration value: {key}', color='red', config=extended_config)
            stderr('    {}: {}'.format(e.__class__.__name__, e))
            stderr()
            stderr('    Check your config for mistakes and try again (your archive data is unaffected).')
            stderr()
            stderr('    For config documentation and examples see:')
            stderr('        https://github.com/pirate/ArchiveBox/wiki/Configuration')
            stderr()
            raise
            raise SystemExit(2)
    
    return extended_config

# def write_config(config: ConfigDict):

#     with open(os.path.join(config['OUTPUT_DIR'], CONFIG_FILENAME), 'w+') as f:

def stdout(*args, color: Optional[str]=None, prefix: str='', config: Optional[ConfigDict]=None) -> None:
    ansi = DEFAULT_CLI_COLORS if (config or {}).get('USE_COLOR') else ANSI

    if color:
        strs = [ansi[color], ' '.join(str(a) for a in args), ansi['reset'], '\n']
    else:
        strs = [' '.join(str(a) for a in args), '\n']

    sys.stdout.write(prefix + ''.join(strs))

def stderr(*args, color: Optional[str]=None, prefix: str='', config: Optional[ConfigDict]=None) -> None:
    ansi = DEFAULT_CLI_COLORS if (config or {}).get('USE_COLOR') else ANSI

    if color:
        strs = [ansi[color], ' '.join(str(a) for a in args), ansi['reset'], '\n']
    else:
        strs = [' '.join(str(a) for a in args), '\n']

    sys.stderr.write(prefix + ''.join(strs))

def hint(text: Union[Tuple[str, ...], List[str], str], prefix='    ', config: Optional[ConfigDict]=None) -> None:
    ansi = DEFAULT_CLI_COLORS if (config or {}).get('USE_COLOR') else ANSI

    if isinstance(text, str):
        stderr('{}{lightred}Hint:{reset} {}'.format(prefix, text, **ansi))
    else:
        stderr('{}{lightred}Hint:{reset} {}'.format(prefix, text[0], **ansi))
        for line in text[1:]:
            stderr('{}      {}'.format(prefix, line))


def bin_version(binary: Optional[str]) -> Optional[str]:
    """check the presence and return valid version line of a specified binary"""

    abspath = bin_path(binary)
    if not binary or not abspath:
        return None

    try:
        version_str = run([abspath, "--version"], stdout=PIPE).stdout.strip().decode()
        # take first 3 columns of first line of version info
        return ' '.join(version_str.split('\n')[0].strip().split()[:3])
    except OSError:
        pass
        # stderr(f'[X] Unable to find working version of dependency: {binary}', color='red')
        # stderr('    Make sure it\'s installed, then confirm it\'s working by running:')
        # stderr(f'        {binary} --version')
        # stderr()
        # stderr('    If you don\'t want to install it, you can disable it via config. See here for more info:')
        # stderr('        https://github.com/pirate/ArchiveBox/wiki/Install')
    return None

def bin_path(binary: Optional[str]) -> Optional[str]:
    if binary is None:
        return None

    node_modules_bin = Path('.') / 'node_modules' / '.bin' / binary
    if node_modules_bin.exists():
        return str(node_modules_bin.resolve())

    return shutil.which(Path(binary).expanduser()) or binary

def bin_hash(binary: Optional[str]) -> Optional[str]:
    if binary is None:
        return None
    abs_path = bin_path(binary)
    if abs_path is None or not Path(abs_path).exists():
        return None

    file_hash = md5()
    with io.open(abs_path, mode='rb') as f:
        for chunk in iter(lambda: f.read(io.DEFAULT_BUFFER_SIZE), b''):
            file_hash.update(chunk)
            
    return f'md5:{file_hash.hexdigest()}'

def find_chrome_binary() -> Optional[str]:
    """find any installed chrome binaries in the default locations"""
    # Precedence: Chromium, Chrome, Beta, Canary, Unstable, Dev
    # make sure data dir finding precedence order always matches binary finding order
    default_executable_paths = (
        'chromium-browser',
        'chromium',
        '/Applications/Chromium.app/Contents/MacOS/Chromium',
        'chrome',
        'google-chrome',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        'google-chrome-stable',
        'google-chrome-beta',
        'google-chrome-canary',
        '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
        'google-chrome-unstable',
        'google-chrome-dev',
    )
    for name in default_executable_paths:
        full_path_exists = shutil.which(name)
        if full_path_exists:
            return name
    
    return None

def find_chrome_data_dir() -> Optional[str]:
    """find any installed chrome user data directories in the default locations"""
    # Precedence: Chromium, Chrome, Beta, Canary, Unstable, Dev
    # make sure data dir finding precedence order always matches binary finding order
    default_profile_paths = (
        '~/.config/chromium',
        '~/Library/Application Support/Chromium',
        '~/AppData/Local/Chromium/User Data',
        '~/.config/chrome',
        '~/.config/google-chrome',
        '~/Library/Application Support/Google/Chrome',
        '~/AppData/Local/Google/Chrome/User Data',
        '~/.config/google-chrome-stable',
        '~/.config/google-chrome-beta',
        '~/Library/Application Support/Google/Chrome Canary',
        '~/AppData/Local/Google/Chrome SxS/User Data',
        '~/.config/google-chrome-unstable',
        '~/.config/google-chrome-dev',
    )
    for path in default_profile_paths:
        full_path = Path(path).resolve()
        if full_path.exists():
            return full_path
    return None

def wget_supports_compression(config):
    try:
        cmd = [
            config['WGET_BINARY'],
            "--compression=auto",
            "--help",
        ]
        return not run(cmd, stdout=DEVNULL, stderr=DEVNULL).returncode
    except (FileNotFoundError, OSError):
        return False

def get_code_locations(config: ConfigDict) -> SimpleConfigValueDict:
    return {
        'PACKAGE_DIR': {
            'path': (config['PACKAGE_DIR']).resolve(),
            'enabled': True,
            'is_valid': (config['PACKAGE_DIR'] / '__main__.py').exists(),
        },
        'TEMPLATES_DIR': {
            'path': (config['TEMPLATES_DIR']).resolve(),
            'enabled': True,
            'is_valid': (config['TEMPLATES_DIR'] / 'static').exists(),
        },
    }

def get_external_locations(config: ConfigDict) -> ConfigValue:
    abspath = lambda path: None if path is None else Path(path).resolve()
    return {
        'CHROME_USER_DATA_DIR': {
            'path': abspath(config['CHROME_USER_DATA_DIR']),
            'enabled': config['USE_CHROME'] and config['CHROME_USER_DATA_DIR'],
            'is_valid': False if config['CHROME_USER_DATA_DIR'] is None else (Path(config['CHROME_USER_DATA_DIR']) / 'Default').exists(),
        },
        'COOKIES_FILE': {
            'path': abspath(config['COOKIES_FILE']),
            'enabled': config['USE_WGET'] and config['COOKIES_FILE'],
            'is_valid': False if config['COOKIES_FILE'] is None else Path(config['COOKIES_FILE']).exists(),
        },
    }

def get_data_locations(config: ConfigDict) -> ConfigValue:
    return {
        'OUTPUT_DIR': {
            'path': config['OUTPUT_DIR'].resolve(),
            'enabled': True,
            'is_valid': (config['OUTPUT_DIR'] / SQL_INDEX_FILENAME).exists(),
        },
        'SOURCES_DIR': {
            'path': config['SOURCES_DIR'].resolve(),
            'enabled': True,
            'is_valid': config['SOURCES_DIR'].exists(),
        },
        'LOGS_DIR': {
            'path': config['LOGS_DIR'].resolve(),
            'enabled': True,
            'is_valid': config['LOGS_DIR'].exists(),
        },
        'ARCHIVE_DIR': {
            'path': config['ARCHIVE_DIR'].resolve(),
            'enabled': True,
            'is_valid': config['ARCHIVE_DIR'].exists(),
        },
        'CONFIG_FILE': {
            'path': config['CONFIG_FILE'].resolve(),
            'enabled': True,
            'is_valid': config['CONFIG_FILE'].exists(),
        },
        'SQL_INDEX': {
            'path': (config['OUTPUT_DIR'] / SQL_INDEX_FILENAME).resolve(),
            'enabled': True,
            'is_valid': (config['OUTPUT_DIR'] / SQL_INDEX_FILENAME).exists(),
        },
    }

def get_dependency_info(config: ConfigDict) -> ConfigValue:
    return {
        'PYTHON_BINARY': {
            'path': bin_path(config['PYTHON_BINARY']),
            'version': config['PYTHON_VERSION'],
            'hash': bin_hash(config['PYTHON_BINARY']),
            'enabled': True,
            'is_valid': bool(config['DJANGO_VERSION']),
        },
        'DJANGO_BINARY': {
            'path': bin_path(config['DJANGO_BINARY']),
            'version': config['DJANGO_VERSION'],
            'hash': bin_hash(config['DJANGO_BINARY']),
            'enabled': True,
            'is_valid': bool(config['DJANGO_VERSION']),
        },
        'CURL_BINARY': {
            'path': bin_path(config['CURL_BINARY']),
            'version': config['CURL_VERSION'],
            'hash': bin_hash(config['PYTHON_BINARY']),
            'enabled': config['USE_CURL'],
            'is_valid': bool(config['CURL_VERSION']),
        },
        'WGET_BINARY': {
            'path': bin_path(config['WGET_BINARY']),
            'version': config['WGET_VERSION'],
            'hash': bin_hash(config['WGET_BINARY']),
            'enabled': config['USE_WGET'],
            'is_valid': bool(config['WGET_VERSION']),
        },
        'SINGLEFILE_BINARY': {
            'path': bin_path(config['SINGLEFILE_BINARY']),
            'version': config['SINGLEFILE_VERSION'],
            'hash': bin_hash(config['SINGLEFILE_BINARY']),
            'enabled': config['USE_SINGLEFILE'],
            'is_valid': bool(config['SINGLEFILE_VERSION']),
        },
        'READABILITY_BINARY': {
            'path': bin_path(config['READABILITY_BINARY']),
            'version': config['READABILITY_VERSION'],
            'hash': bin_hash(config['READABILITY_BINARY']),
            'enabled': config['USE_READABILITY'],
            'is_valid': bool(config['READABILITY_VERSION']),
        },
        'MERCURY_BINARY': {
            'path': bin_path(config['MERCURY_BINARY']),
            'version': config['MERCURY_VERSION'],
            'hash': bin_hash(config['MERCURY_BINARY']),
            'enabled': config['USE_MERCURY'],
            'is_valid': bool(config['MERCURY_VERSION']),
        },
        'GIT_BINARY': {
            'path': bin_path(config['GIT_BINARY']),
            'version': config['GIT_VERSION'],
            'hash': bin_hash(config['GIT_BINARY']),
            'enabled': config['USE_GIT'],
            'is_valid': bool(config['GIT_VERSION']),
        },
        'YOUTUBEDL_BINARY': {
            'path': bin_path(config['YOUTUBEDL_BINARY']),
            'version': config['YOUTUBEDL_VERSION'],
            'hash': bin_hash(config['YOUTUBEDL_BINARY']),
            'enabled': config['USE_YOUTUBEDL'],
            'is_valid': bool(config['YOUTUBEDL_VERSION']),
        },
        'CHROME_BINARY': {
            'path': bin_path(config['CHROME_BINARY']),
            'version': config['CHROME_VERSION'],
            'hash': bin_hash(config['CHROME_BINARY']),
            'enabled': config['USE_CHROME'],
            'is_valid': bool(config['CHROME_VERSION']),
        },
    }

def get_chrome_info(config: ConfigDict) -> ConfigValue:
    return {
        'TIMEOUT': config['TIMEOUT'],
        'RESOLUTION': config['RESOLUTION'],
        'CHECK_SSL_VALIDITY': config['CHECK_SSL_VALIDITY'],
        'CHROME_BINARY': config['CHROME_BINARY'],
        'CHROME_HEADLESS': config['CHROME_HEADLESS'],
        'CHROME_SANDBOX': config['CHROME_SANDBOX'],
        'CHROME_USER_AGENT': config['CHROME_USER_AGENT'],
        'CHROME_USER_DATA_DIR': config['CHROME_USER_DATA_DIR'],
    }


################################## Load Config #################################


def load_all_config():
    CONFIG: ConfigDict = {}
    for section_name, section_config in CONFIG_DEFAULTS.items():
        CONFIG = load_config(section_config, CONFIG)

    return load_config(DERIVED_CONFIG_DEFAULTS, CONFIG)

CONFIG = load_all_config()
globals().update(CONFIG)

# Timezone set as UTC
os.environ["TZ"] = 'UTC'

# add ./node_modules/.bin to $PATH so we can use node scripts in extractors
NODE_BIN_PATH = str((Path(CONFIG["OUTPUT_DIR"]).absolute() / 'node_modules' / '.bin'))
sys.path.append(NODE_BIN_PATH)


############################## Importable Checkers #############################

def check_system_config(config: ConfigDict=CONFIG) -> None:
    ### Check system environment
    if config['USER'] == 'root':
        stderr('[!] ArchiveBox should never be run as root!', color='red')
        stderr('    For more information, see the security overview documentation:')
        stderr('        https://github.com/pirate/ArchiveBox/wiki/Security-Overview#do-not-run-as-root')
        raise SystemExit(2)

    ### Check Python environment
    if sys.version_info[:3] < (3, 6, 0):
        stderr(f'[X] Python version is not new enough: {config["PYTHON_VERSION"]} (>3.6 is required)', color='red')
        stderr('    See https://github.com/pirate/ArchiveBox/wiki/Troubleshooting#python for help upgrading your Python installation.')
        raise SystemExit(2)

    if config['PYTHON_ENCODING'] not in ('UTF-8', 'UTF8'):
        stderr(f'[X] Your system is running python3 scripts with a bad locale setting: {config["PYTHON_ENCODING"]} (it should be UTF-8).', color='red')
        stderr('    To fix it, add the line "export PYTHONIOENCODING=UTF-8" to your ~/.bashrc file (without quotes)')
        stderr('    Or if you\'re using ubuntu/debian, run "dpkg-reconfigure locales"')
        stderr('')
        stderr('    Confirm that it\'s fixed by opening a new shell and running:')
        stderr('        python3 -c "import sys; print(sys.stdout.encoding)"   # should output UTF-8')
        raise SystemExit(2)

    # stderr('[i] Using Chrome binary: {}'.format(shutil.which(CHROME_BINARY) or CHROME_BINARY))
    # stderr('[i] Using Chrome data dir: {}'.format(os.path.abspath(CHROME_USER_DATA_DIR)))
    if config['CHROME_USER_DATA_DIR'] is not None:
        if not (Path(config['CHROME_USER_DATA_DIR']) / 'Default').exists():
            stderr('[X] Could not find profile "Default" in CHROME_USER_DATA_DIR.', color='red')
            stderr(f'    {config["CHROME_USER_DATA_DIR"]}')
            stderr('    Make sure you set it to a Chrome user data directory containing a Default profile folder.')
            stderr('    For more info see:')
            stderr('        https://github.com/pirate/ArchiveBox/wiki/Configuration#CHROME_USER_DATA_DIR')
            if '/Default' in str(config['CHROME_USER_DATA_DIR']):
                stderr()
                stderr('    Try removing /Default from the end e.g.:')
                stderr('        CHROME_USER_DATA_DIR="{}"'.format(config['CHROME_USER_DATA_DIR'].split('/Default')[0]))
            raise SystemExit(2)


def check_dependencies(config: ConfigDict=CONFIG, show_help: bool=True) -> None:
    invalid_dependencies = [
        (name, info) for name, info in config['DEPENDENCIES'].items()
        if info['enabled'] and not info['is_valid']
    ]
    if invalid_dependencies and show_help:
        stderr(f'[!] Warning: Missing {len(invalid_dependencies)} recommended dependencies', color='lightyellow')
        for dependency, info in invalid_dependencies:
            stderr(
                '    ! {}: {} ({})'.format(
                    dependency,
                    info['path'] or 'unable to find binary',
                    info['version'] or 'unable to detect version',
                )
            )
            if dependency in ('SINGLEFILE_BINARY', 'READABILITY_BINARY', 'MERCURY_BINARY'):
                hint(('npm install --prefix . "git+https://github.com/pirate/ArchiveBox.git"',
                    f'or archivebox config --set SAVE_{dependency.rsplit("_", 1)[0]}=False to silence this warning',
                    ''), prefix='      ')
        stderr('')

    if config['TIMEOUT'] < 5:
        stderr(f'[!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={config["TIMEOUT"]} seconds)', color='red')
        stderr('    You must allow *at least* 5 seconds for indexing and archive methods to run succesfully.')
        stderr('    (Setting it to somewhere between 30 and 3000 seconds is recommended)')
        stderr()
        stderr('    If you want to make ArchiveBox run faster, disable specific archive methods instead:')
        stderr('        https://github.com/pirate/ArchiveBox/wiki/Configuration#archive-method-toggles')
        stderr()

    elif config['USE_CHROME'] and config['TIMEOUT'] < 15:
        stderr(f'[!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={config["TIMEOUT"]} seconds)', color='red')
        stderr('    Chrome will fail to archive all sites if set to less than ~15 seconds.')
        stderr('    (Setting it to somewhere between 30 and 300 seconds is recommended)')
        stderr()
        stderr('    If you want to make ArchiveBox run faster, disable specific archive methods instead:')
        stderr('        https://github.com/pirate/ArchiveBox/wiki/Configuration#archive-method-toggles')
        stderr()

    if config['USE_YOUTUBEDL'] and config['MEDIA_TIMEOUT'] < 20:
        stderr(f'[!] Warning: MEDIA_TIMEOUT is set too low! (currently set to MEDIA_TIMEOUT={config["MEDIA_TIMEOUT"]} seconds)', color='red')
        stderr('    Youtube-dl will fail to archive all media if set to less than ~20 seconds.')
        stderr('    (Setting it somewhere over 60 seconds is recommended)')
        stderr()
        stderr('    If you want to disable media archiving entirely, set SAVE_MEDIA=False instead:')
        stderr('        https://github.com/pirate/ArchiveBox/wiki/Configuration#save_media')
        stderr()
        
def check_data_folder(out_dir: Optional[str]=None, config: ConfigDict=CONFIG) -> None:
    output_dir = out_dir or config['OUTPUT_DIR']
    assert isinstance(output_dir, (str, Path))

    sql_index_exists = (Path(output_dir) / SQL_INDEX_FILENAME).exists()
    if not sql_index_exists:
        stderr('[X] No archivebox index found in the current directory.', color='red')
        stderr(f'    {output_dir}', color='lightyellow')
        stderr()
        stderr('    {lightred}Hint{reset}: Are you running archivebox in the right folder?'.format(**config['ANSI']))
        stderr('        cd path/to/your/archive/folder')
        stderr('        archivebox [command]')
        stderr()
        stderr('    {lightred}Hint{reset}: To create a new archive collection or import existing data in this folder, run:'.format(**config['ANSI']))
        stderr('        archivebox init')
        raise SystemExit(2)

    from .index.sql import list_migrations

    pending_migrations = [name for status, name in list_migrations() if not status]

    if (not sql_index_exists) or pending_migrations:
        if sql_index_exists:
            pending_operation = f'apply the {len(pending_migrations)} pending migrations'
        else:
            pending_operation = 'generate the new SQL main index'

        stderr('[X] This collection was created with an older version of ArchiveBox and must be upgraded first.', color='lightyellow')
        stderr(f'    {output_dir}')
        stderr()
        stderr(f'    To upgrade it to the latest version and {pending_operation} run:')
        stderr('        archivebox init')
        raise SystemExit(3)

    sources_dir = Path(output_dir) / SOURCES_DIR_NAME
    if not sources_dir.exists():
        sources_dir.mkdir()



def setup_django(out_dir: Path=None, check_db=False, config: ConfigDict=CONFIG) -> None:
    check_system_config()
    
    output_dir = out_dir or Path(config['OUTPUT_DIR'])

    assert isinstance(output_dir, Path) and isinstance(config['PACKAGE_DIR'], Path)

    try:
        import django
        sys.path.append(str(config['PACKAGE_DIR']))
        os.environ.setdefault('OUTPUT_DIR', str(output_dir))
        assert (config['PACKAGE_DIR'] / 'core' / 'settings.py').exists(), 'settings.py was not found at archivebox/core/settings.py'
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
        django.setup()

        if check_db:
            sql_index_path = Path(output_dir) / SQL_INDEX_FILENAME
            assert sql_index_path.exists(), (
                f'No database file {SQL_INDEX_FILENAME} found in OUTPUT_DIR: {config["OUTPUT_DIR"]}')
    except KeyboardInterrupt:
        raise SystemExit(2)

os.umask(0o777 - int(OUTPUT_PERMISSIONS, base=8))  # noqa: F821
