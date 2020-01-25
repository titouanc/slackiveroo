from os import environ as env


REDIS_URL: str = env.get('REDIS_URL', 'redis://localhost')

# The Slack application OAuth2 client ID
SLACK_CLIENT_ID: str = env.get('SLACK_CLIENT_ID', "")

# The Slack application OAuth2 client secret
SLACK_CLIENT_SECRET: str = env.get('SLACK_CLIENT_SECRET', "")

# The Slack signing secret, used to authenticate incoming Slack events
# https://api.slack.com/docs/verifying-requests-from-slack
SLACK_SIGN_SECRET: str = env.get('SLACK_SIGN_SECRET', "")

# This is used to run the app on Heroku with a free plan, where the web
# server is put to sleep if it receives no requests for 30minutes.
# We therefore make this app query itself every 5 minutes to keep the
# web server alive. Put the full URL to the /ping endpoint
SELF_QUERY_URL: str = env.get('SELF_QUERY_URL', 'http://localhost:8000/ping')

# If true, use mocked responses instead of the Deliveroo API
USE_MOCK: bool = 'USE_MOCK' in env

# If true, run in debug mode
DEBUG: bool = 'DEBUG' in env

try:
    from local_settings import *  # pragma: no flakes
except ImportError:
    pass
