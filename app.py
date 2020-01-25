import json
import logging
import asyncio
from aiohttp import web, ClientSession
from typing import Dict

import slack
import settings

if not settings.USE_MOCK:
    from tracker import Tracker
else:
    from tracker import MockingTracker
    class Tracker(MockingTracker):
        responses = [
            json.load(open("examples/deliveroo-order-ongoing.json")),
            json.load(open("examples/deliveroo-order-delivering.json")),
            json.load(open("examples/deliveroo-order-complete.json")),
        ]


logger = logging.getLogger("slackiveroo")
active_trackers: Dict[str, Tracker] = {}


@slack.verify_signature
async def on_slack_event(request):
    """
    Handler for the Slack event API (HTTP POST)
    """
    payload = await request.json()
    logger.debug("Received event: %s", payload)

    # Verification for app installation
    if payload['type'] == 'url_verification':
        return web.Response(text=payload['challenge'])

    # A "roo.it" link was shared
    evt = payload['event']
    if evt['type'] == 'link_shared':
        for link in evt['links']:
            if link['domain'] == 'roo.it':
                url = link['url']
                chan = slack.Channel(
                    team_id=payload['team_id'],
                    channel_id=evt['channel'],
                )
                if url in active_trackers:
                    # Add channel if we already have a tracker for that order
                    tracker = active_trackers[url]
                    asyncio.ensure_future(tracker.add_channel(chan))
                else:
                    # Otherwise spawn a new tracker
                    t = await Tracker.from_sharing_url(url, chan)
                    active_trackers[link['url']] = t
                    asyncio.ensure_future(t.run())

    return web.Response(text="")


async def on_slack_oauth(request):
    """
    Handler for the "add to slack" OAuth callback
    """
    grant_code = request.query['code']
    logger.info("Got OAuth grant code %s", grant_code)
    asyncio.ensure_future(slack.get_oauth_token(grant_code))
    return web.Response(text="")


async def heroku_web_keepalive(ping_url=settings.SELF_QUERY_URL, period=300):
    """
    Regulargly hit the /ping endpoint of this webapp
    """
    if not ping_url:
        logger.warn("No self-query URL given, Heroku keepalive is disabled")
        return

    async with ClientSession() as session:
        while True:
            if len(active_trackers) > 0:
                page = await session.get(ping_url)
                assert page.status == 200
            await asyncio.sleep(period)


home_html = open("home.html").read().format(**settings.__dict__)

app = web.Application()
app.add_routes([
    web.get('/', lambda request: web.Response(
        text=home_html,
        content_type='text/html'
    )),
    web.post('/slack/event', on_slack_event),
    web.get('/slack/oauth', on_slack_oauth),
    web.get('/ping', lambda request: web.Response(text="pong"))
])

logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)

if __name__ == "__main__":
    from sys import argv
    port = int(argv[1]) if len(argv) > 1 else 8000

    asyncio.ensure_future(heroku_web_keepalive())
    web.run_app(app, port=port)
