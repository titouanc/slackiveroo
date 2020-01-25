import hmac
import hashlib
import logging
import aioredis
from time import time
from typing import Dict, List
from aiohttp import web, ClientSession

import settings

logger = logging.getLogger('slack')


class Channel:
    def __init__(self, team_id, channel_id):
        self.team_id, self.channel_id = team_id, channel_id
        self.token = None

    def __eq__(self, other):
        return (self.team_id, self.channel_id) == (other.team_id, other.channel_id)

    async def get_token(self):
        if not self.token:
            redis = await aioredis.create_redis_pool(settings.REDIS_URL)
            self.token = await redis.hget('slackiveroo.tokens', self.team_id,
                                          encoding='utf-8')
            redis.close()
            await redis.wait_closed()
        return self.token

    async def join(self, http_session):
        token = await self.get_token()
        posted = await http_session.post(
            "https://slack.com/api/conversations.join",
            headers={'Authorization': 'Bearer %s' % token},
            json={
                'channel': self.channel_id
            }
        )
        assert posted.status == 200
        response = await posted.json()
        assert response['ok'], str(response)

    async def post_message(self, text, blocks, http_session):
        token = await self.get_token()
        posted = await http_session.post(
            "https://slack.com/api/chat.postMessage",
            headers={'Authorization': 'Bearer %s' % token},
            json={
                'channel': self.channel_id,
                'blocks': blocks,
                'text': text
            },
        )
        assert posted.status == 200
        response = await posted.json()
        if not response['ok'] and response['error'] == 'not_in_channel':
            await self.join(http_session)
            await self.post_message(text, blocks, http_session)
        else:
            assert response['ok'], str(response)


def get_http_session():
    return ClientSession(headers={'User-Agent': 'titouanc/slackiveroo'})


def sign_request(timestamp, message, key=settings.SLACK_SIGN_SECRET):
    """
    Compute the Slack Signature hash.
    See details on https://api.slack.com/docs/verifying-requests-from-slack
    """
    version = 'v0'
    msg = f'{version}:{timestamp}:{message}'
    return version + '=' + hmac.new(
        key=key.encode(),
        msg=msg.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


async def get_oauth_token(grant_code):
    async with get_http_session() as session:
        page = await session.post("https://slack.com/api/oauth.v2.access", data={
            "client_id": settings.SLACK_CLIENT_ID,
            "client_secret": settings.SLACK_CLIENT_SECRET,
            "code": grant_code,
        })
        assert page.status == 200
        auth = await page.json()
        if not auth['ok']:
            raise Exception("Invalid OAuth2 access: " + auth['error'])

        logger.debug("AUTH: %s", auth)

        logger.info(
            "Got OAuth2 %s token with scope %s as %s in Team %s: %s",
            auth["token_type"], auth['scope'], auth['bot_user_id'],
            auth['team']['name'], auth['access_token']
        )

        redis = await aioredis.create_redis_pool(settings.REDIS_URL)
        await redis.hset('slackiveroo.tokens', auth['team']['id'], auth['access_token'])
        redis.close()
        await redis.wait_closed()


async def post_message(channels, text: str, blocks: List[Dict]) -> None:
    async with get_http_session() as session:
        for chan in channels:
            await chan.post_message(text, blocks, session)


def verify_signature(func):
    """
    Decorator that run a view only if the Slack signature is verified
    Otherwise, return a 403
    """
    async def wrapper(request, *args, **kwargs):
        body = await request.text()
        timestamp = int(request.headers['X-Slack-Request-Timestamp'])
        if abs(time() - timestamp) > 300:
            logger.error(
                "Slack request cannot be authenticated: "
                "timestamp (%d) is not within 5 minutes from now (%d)",
                timestamp, time()
            )
            return web.Response(text="Invalid timestamp", status=403)

        signature = sign_request(timestamp, body)
        if signature == request.headers['X-Slack-Signature']:
            return await func(request, *args, **kwargs)
        else:
            logger.error(
                "Slack request cannot be authenticated: "
                "signature mismatch (given: %s, computed: %s)",
                signature, request.headers['X-Slack-Signature']
            )
            return web.Response(text="You're not Slack", status=403)
    return wrapper
