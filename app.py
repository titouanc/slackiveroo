import re
import json
import logging
import asyncio
from glob import glob
import aiohttp
from aiohttp import web, ClientSession

from settings import SLACK_APP_TOKEN

logger = logging.getLogger("slackiveroo")
api_root = "https://order-status.deliveroo.net/api/v2-4"

orders_being_tracked = {}


async def get_tracking_url(session, rooit_url):
    """
    Return a Deliveroo API tracking URL from a "roo.it" sharing URL
    """
    async with session.get(rooit_url) as page:
        # 1. Get client frontend page via the shortlink redirection
        assert page.status == 200
        logger.info("Frontend url for %s is %s", rooit_url, page.url)

        # 2. Extract the order ID and access token from the frontend URL
        path = re.match(r'.*/orders/(\d+)/status$', page.url.path)
        url = "{api}/consumer_order_statuses/{order}?sharing_token={token}"
        return url.format(
            api=api_root,
            order=path.group(1),
            token=page.url.query['sharing_token']
        )


async def post_slack_status_update(slack_channel, deliveroo_state):
    """
    Format a deliveroo API response into Slack blocks, and send it
    """
    assert deliveroo_state['included'][0]['type'] == 'order'
    order = deliveroo_state['included'][0]['attributes']

    attributes = deliveroo_state['data']['attributes']
    if 'eta_message' not in attributes:
        text = "*%s* is @here :bowl_with_spoon: !" % order['restaurant_name']
    else:
        text = "*%s*: %s\n*ETA*: %s\n%s" % (
            order['restaurant_name'],
            attributes['message'],
            attributes['eta_message'],
            order['sharing_short_url'],
        )

    message = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": text,
        },
        "accessory": {
            "type": "image",
            "image_url": order['image_url'].format(w=192, h=108),
            "alt_text": "Restaurant preview",
        }
    }

    async with ClientSession() as session:
        posted = await session.post(
            "https://slack.com/api/chat.postMessage",
            headers={'Authorization': 'Bearer %s' % SLACK_APP_TOKEN},
            json={'channel': slack_channel, 'blocks': [message]},
        )
        assert posted.status == 200


async def perform_tracking(rooit_url, polling_period_seconds=30):
    """
    Async task that track the Deliveroo order until complete
    """
    logger.info("Starting to track %s", rooit_url)
    async with ClientSession(headers={'User-Agent': 'titouanc/slackiveroo'}) as session:
        tracking_url = await get_tracking_url(session, rooit_url)
        last_msg = None
        while True:
            # 1. Get status from Deliveroo
            page = await session.get(tracking_url)
            assert page.status == 200
            state = await page.json()

            status = state['data']['attributes']['ui_status']
            msg = state['data']['attributes']['message']

            # 2. Post a status update to Slack when the user message changes
            if msg != last_msg:
                for chan in orders_being_tracked[rooit_url]:
                    await post_slack_status_update(slack_channel, state)
                logger.info("[%s] %s :: %s", rooit_url, status, msg)
                last_msg = msg

            # 3. Stop tracking when the order is delivered
            if status == "COMPLETED":
                logger.info("Tracking %s has ended (COMPLETE)", rooit_url)
                break

            # 4. Then wait a bit
            await asyncio.sleep(polling_period_seconds)


async def start_tracking(rooit_url, slack_channel):
    if rooit_url in orders_being_tracked:
        orders_being_tracked[rooit_url].add(slack_channel)
        logger.info("I'm already tracking %s; also post updates to %s",
                    rooit_url, slack_channel)
    else:
        orders_being_tracked[rooit_url] = set([slack_channel])
        try:
            await perform_tracking(rooit_url)
        except:
            logger.exception("Error while performing tracking of %s",
                             rooit_url)
        orders_being_tracked.pop(rooit_url)


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
                f = start_tracking(link['url'], evt['channel'])
                asyncio.ensure_future(f)

    return web.Response(text="")


if __name__ == "__main__":
    from sys import argv
    logging.basicConfig(level=logging.INFO)

    port = int(argv[1]) if len(argv) > 1 else 8000

    app = web.Application()
    app.add_routes([web.post('/', on_slack_event)])
    web.run_app(app, port=port)
