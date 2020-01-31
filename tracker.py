import re
import asyncio
import logging
from aiohttp import ClientSession

import slack
import settings

logger = logging.getLogger('tracker')
api_root = "https://order-status.deliveroo.net/api/v2-4"


class Tracker:
    """
    ALl the state needed to track an ongoing Deliveroo order
    """
    def __init__(self, tracking_url, *channels):
        self.channels = list(channels)   # Channles to which to post status updates
        self.completed = False           # True if the order is complete (no more tracking)
        self.tracking_url = tracking_url # The deliveroo API tracking URL
        self.current_state = None        # The current deliveroo status

    @classmethod
    async def from_sharing_url(cls, sharing_url, *channels):
        """
        Obtain a tracker from a sharing url (https://roo.it/s/...)
        """
        async with slack.get_http_session() as session:
            # 1. Get client frontend page via the shortlink redirection
            page = await session.get(sharing_url)
            assert page.status == 200
            logger.info("Frontend url for %s is %s", sharing_url, page.url)

            # 2. Extract the order ID and access token from the frontend URL
            path = re.match(r'.*/orders/(\d+)/status$', page.url.path)
            url = "{api}/consumer_order_statuses/{order}?sharing_token={token}"
            tracking_url = url.format(
                api=api_root,
                order=path.group(1),
                token=page.url.query['sharing_token']
            )
            return cls(tracking_url, *channels)

    async def add_channel(self, chan):
        """
        Add a channel to be notified when the order status changes
        """
        # 1. Do not duplicate channels
        for known_chan in self.channels:
            if chan == known_chan:
                return
        self.channels.append(chan)

        # 2. Post a status update if the status is already known
        if self.current_state is not None:
            text, blocks = self.format_slack_status_update(self.current_state)
            await slack.post_message([chan], text, blocks)

    def format_slack_status_update(self, deliveroo_state):
        """
        Format a deliveroo API response into Slack text and blocks
        """
        assert deliveroo_state['included'][0]['type'] == 'order'
        order = deliveroo_state['included'][0]['attributes']

        attributes = deliveroo_state['data']['attributes']
        if attributes['ui_status'] == 'FAILED':
            text = "@here :rotating_light: The order from *%s* has *FAILED* _(%s)_\n%s" % (
                order['restaurant_name'],
                attributes['message'],
                order['sharing_short_url'],
            )
        elif 'eta_message' not in attributes:
            text = "*%s* is here, @hungry people :bowl_with_spoon: !" % order['restaurant_name']
        else:
            text = "*%s*: %s\n*ETA*: %s\n%s" % (
                order['restaurant_name'],
                attributes['message'],
                attributes['eta_message'],
                order['sharing_short_url'],
            )

        block = {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
            "accessory": {
                "type": "image",
                "image_url": order['image_url'].format(w=192, h=108),
                "alt_text": "Restaurant preview",
            }
        }

        return text.split('\n')[0], [block]

    async def get_order_status(self):
        page = await self.session.get(self.tracking_url)
        assert page.status == 200
        return await page.json()

    async def run(self, polling_period_seconds=15):
        """
        Async task that tracks the Deliveroo order until complete
        """
        logger.info(f"Starting to track {self.tracking_url}")
        last_msg = None
        while not self.completed:
            # 1. Get status from Deliveroo
            self.current_state = await self.get_order_status()
            status = self.current_state['data']['attributes']['ui_status']
            msg = self.current_state['data']['attributes']['message']

            # 2. Post a status update to Slack when the user message changes
            if msg != last_msg:
                text, blocks = self.format_slack_status_update(self.current_state)
                logger.info(f"[{self.tracking_url}] {status} :: {msg}")
                await slack.post_message(self.channels, text, blocks)
                last_msg = msg

            # 3. Stop tracking when the order is delivered
            if status in ('COMPLETED', 'FAILED'):
                logger.info(f"Tracking {self.tracking_url} has ended ({status})")
                self.completed = True
                break

            # 4. Then wait a bit
            await asyncio.sleep(polling_period_seconds)


class MockingTracker(Tracker):
    """
    Like a tracker, but the list of deliveroo responses is predefined, using
    the class attribute responses. Usefule in development. Example:
    
    class MyTracker(MockingTracker):
        responses = [{"data": {"attributes": {"ui_status": "COMPLETED"}}}]
    """
    def __init__(self, *args, **kwargs):
        super(MockingTracker, self).__init__(*args, **kwargs)
        self.backlog = self.responses

    @classmethod
    async def from_sharing_url(cls, rooit_url, *args, **kwargs):
        logger.info("MOCK ! Bypass tracking url obtention")
        return cls("[MOCK]", *args, **kwargs)

    async def get_order_status(self):
        await asyncio.sleep(.125)
        this_response, self.backlog = self.backlog[0], self.backlog[1:]
        return this_response
