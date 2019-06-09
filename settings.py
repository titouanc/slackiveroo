from os import environ as ENV

SLACK_APP_TOKEN = ENV.get('SLACK_APP_TOKEN', "")

try:
    from local_settings import *  # pragma: no flakes
except ImportError:
    pass
