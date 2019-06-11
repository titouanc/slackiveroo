from os import environ as ENV

# The static app token used to post to Slack
SLACK_APP_TOKEN = ENV.get('SLACK_APP_TOKEN', "")

# URL for self-querying the application, to prevent the Heroku web worker
# to go to sleep on Free Plan Dynos
SELF_QUERY_URL = ENV.get('SELF_QUERY_URL', None)

try:
    from local_settings import *  # pragma: no flakes
except ImportError:
    pass
