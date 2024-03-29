# -*- coding: utf-8 -*-
import asyncio
import hashlib
import logging
import os
import random
import sqlite3
import string
import sys
import uuid
from uuid import uuid4

import aiohttp
from faker import Faker
from unidecode import unidecode
from volgactf.final.checker.result import Result

logger = logging.getLogger(__name__)
fake = Faker()

# region Environment variables

SERVICE_IP = os.getenv('SERVICE_IP', '0.0.0.0')
PORT = int(os.getenv('PORT', 8080))
ROUND_DURATION = int(os.getenv('ROUND_DURATION', 30))
CONNECTION_TOTAL_TIMEOUT = int(os.getenv('CONNECTION_TIMEOUT', 30))
SAMPLES_DB_PATH = os.getenv('SAMPLES_DB_PATH', '/dist/checker/samples.db')

PUSH_TASK_RET_CODE_OK = 200
PUSH_CAPSULE_RET_CODE_OK = 200
PULL_CAPSULE_RET_CODE_OK = 200

PUSH_TASK_URI_FMT = os.getenv('PUSH_TASK_URI_FMT', 'http://{endpoint}:{port}/task')
PUSH_CAPSULE_URI_FMT = os.getenv('PUSH_CAPSULE_URI_FMT', 'http://{endpoint}:{port}/push')
PULL_CAPSULE_URI_FMT = os.getenv('PULL_CAPSULE_URI_FMT', 'http://{endpoint}:{port}/pull/{task_id}')


# endregion Environment variables


# region Utils

def decode_if_unicode(*args):
    n_args = len(args)
    if n_args == 0:
        return None
    elif n_args == 1:
        s = args[0]
        return unidecode(s) if s is not None else None
    else:
        return [unidecode(s) if s is not None else None for s in args]


def get_random_user_agent():
    return fake.user_agent()


# endregion Utils


async def do_push(endpoint, capsule, _label, _metadata):
    # 1. preprocess the capsule
    capsule = decode_if_unicode(capsule)

    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True),
                                     timeout=aiohttp.ClientTimeout(total=CONNECTION_TOTAL_TIMEOUT),
                                     skip_auto_headers={'User-Agent'}) as session:

        # 2. POST the next task and get result
        logger.info('[%s] on PUSH: sending the next task via POST /task', endpoint)
        try:
            # select a task and generate a unique id
            with sqlite3.connect(SAMPLES_DB_PATH) as conn:
                c = conn.cursor()
                c.execute('SELECT * FROM samples ORDER BY RANDOM() LIMIT 1')
                task_content, task_result, task_comments = c.fetchone()

            task_content, task_result, task_comments = decode_if_unicode(task_content, task_result, task_comments)
            task_id = uuid4().hex

            # make the request
            headers = {'User-Agent': get_random_user_agent()}
            url = PUSH_TASK_URI_FMT.format(endpoint=endpoint, port=PORT)
            data = {'id': task_id, 'data': task_content}
            if task_comments is not None and task_comments != '':
                data['comments'] = task_comments

            async with session.post(url, headers=headers, json=data) as r:
                if r.status != PUSH_TASK_RET_CODE_OK:
                    logger.info('[%s] on PUSH: uploading task failed, received code: %s', endpoint, r.status)
                    return Result.MUMBLE, '', 'Incorrect response code on POST /task'
                response_record = await r.json()
                if 'data' not in response_record:
                    return Result.MUMBLE, '', 'Incorrect response format on POST /task'
                response_result = response_record['data']

        except sqlite3.Error as ex:
            logger.exception('[%s] on PUSH: Failed to get a random sample: %s', endpoint, ex)
            return Result.INTERNAL_ERROR, '', ''
        except aiohttp.ClientResponseError as ex:
            logger.error('[%s] on PUSH: failed to proceed after server had responded: %s', endpoint, ex)
            return Result.MUMBLE, '', 'Incorrect response on POST /task'
        except aiohttp.ClientConnectionError as ex:
            logger.error('[%s] on PUSH: failed to establish connection: %s', endpoint, ex)
            return Result.DOWN, '', 'Connection error on POST /task'
        except Exception as ex:
            logger.error('[%s] on PUSH: Exception while POSTing task: %s', endpoint, ex)
            return Result.DOWN, '', 'Connection error on POST /task'

        # 3. check if the answer is correct
        logger.info('[%s] on PUSH: checking the received solution', endpoint)
        if response_result != task_result:
            logger.info('[%s] on PUSH: the received result is incorrect', endpoint)
            logger.debug('[%s] on PUSH: received=%s', endpoint, response_result)
            logger.debug('[%s] on PUSH: actual  =%s', endpoint, task_result)
            return Result.CORRUPT, '', 'Incorrect result'

        # 4. POST capsule and its id
        logger.info('[%s] on PUSH: POSTing the capsule', endpoint)
        try:
            url = PUSH_CAPSULE_URI_FMT.format(endpoint=endpoint, port=PORT)
            data = {'id': task_id, 'data': capsule}
            async with session.post(url, headers=headers, json=data) as r:
                if r.status != PUSH_CAPSULE_RET_CODE_OK:
                    logger.info('[%s] on PUSH: POSTing capsule failed, status=%d', endpoint, r.status)
                    return Result.MUMBLE, '', 'Incorrect response code on POST /push'
                logger.info('[%s] on PUSH: POSTed capsule', endpoint)

        except aiohttp.ClientResponseError as ex:
            logger.error('[%s] on PUSH: failed to proceed after server had responded: %s', endpoint, ex)
            return Result.MUMBLE, '', 'Incorrect response on POST /push'
        except aiohttp.ClientConnectionError as ex:
            logger.error('[%s] on PUSH: failed to establish connection: %s', endpoint, ex)
            return Result.DOWN, '', 'Connection error on POST /push'
        except Exception as ex:
            logger.error('[%s] on PUSH: Exception while POSTing capsule: %s', endpoint, ex)
            return Result.DOWN, '', 'Connection error on POST /push'

    # 5. save the task id and return status UP
    return Result.UP, task_id, ''


async def do_pull(endpoint, capsule, label, _metadata):
    # 1. get the task id
    capsule = decode_if_unicode(capsule)
    task_id = decode_if_unicode(label)

    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True),
                                     timeout=aiohttp.ClientTimeout(total=CONNECTION_TOTAL_TIMEOUT),
                                     skip_auto_headers={'User-Agent'}) as session:
        # 2. GET capsule by task id
        logger.info('[%s] on PULL: GETing capsule by task_id=%s', endpoint, task_id)
        try:
            headers = {'User-Agent': get_random_user_agent()}
            url = PULL_CAPSULE_URI_FMT.format(endpoint=endpoint, port=PORT, task_id=task_id)
            async with session.get(url, headers=headers) as r:
                if r.status != PULL_CAPSULE_RET_CODE_OK:
                    logger.info('[%s] on PULL: failed to GET capsule, status=%s', endpoint, r.status)
                    return Result.MUMBLE, 'Incorrect response code on GET /pull/{id}'
                response_record = await r.json()
                if 'data' not in response_record:
                    return Result.MUMBLE, 'Incorrect response format on GET /pull/{id}'
                response_capsule = response_record['data']

        except aiohttp.ClientResponseError as ex:
            logger.error('[%s] on PULL: failed to proceed after server had responded: %s', endpoint, ex)
            return Result.MUMBLE, 'Incorrect response on GET /pull/{id}'
        except aiohttp.ClientConnectionError as ex:
            logger.error('[%s] on PULL: failed to establish connection: %s', endpoint, ex)
            return Result.DOWN, 'Connection error on GET /pull/{id}'
        except Exception as ex:
            logger.error('[%s] on PULL: Exception while GETing capsule: %s', endpoint, ex)
            return Result.DOWN, 'Connection error on GET /pull/{id}'

        # 3. check the capsule
        if response_capsule != capsule:
            logger.info('[%s] on PULL: the received capsule is incorrect', endpoint)
            logger.info('[%s] on PULL: received=%s', endpoint, response_capsule)
            logger.info('[%s] on PULL: actual  =%s', endpoint, capsule)
            return Result.CORRUPT, 'Incorrect flag'

    return Result.UP, ''


async def push(endpoint, capsule, label, metadata):
    try:
        return await do_push(endpoint, capsule, label, metadata)
    except Exception as ex:
        # N.B. PARANOIA MODE ON!!! JAVA STYLE PROGRAMMING MODE ON!!!
        logger.exception('[%s] on PUSH: Exception while PUSHing capsule: %s', endpoint, ex)
        return Result.MUMBLE, '', 'Incorrect server response'


async def pull(endpoint, capsule, label, metadata):
    try:
        return await do_pull(endpoint, capsule, label, metadata)
    except Exception as ex:
        # N.B. PARANOIA MODE ON!!! JAVA STYLE PROGRAMMING MODE ON!!!
        logger.exception('[%s] on PULL: Exception while PULLing capsule: %s', endpoint, ex)
        return Result.MUMBLE, 'Incorrect server response'


# region Themis imitator

class Metadata(object):
    def __init__(self, round_number):
        self.round_number = round_number

    @property
    def round(self):
        return self.round_number


def print_stats(stats, name, put_rn=False):
    print(name)
    n = 0
    for k in stats:
        print(k, ':', stats[k])
        n += stats[k]
    print('Total:', n)
    if put_rn:
        print('\n')
    else:
        print('')


def add_flag_to_pool(pool_flag_labels, flag, flag_adj, pull_count=5):
    if len(pool_flag_labels) != pull_count:
        del pool_flag_labels[:]
        for _ in range(pull_count):
            pool_flag_labels.append({'flag': flag, 'label': flag_adj})
    else:
        del pool_flag_labels[0]
        pool_flag_labels.append({'flag': flag, 'label': flag_adj})


async def main(team_ip, timeout):
    # set service ip and timeout
    level = logging.DEBUG if len(sys.argv) > 3 else logging.INFO

    # initialize logger
    logging.basicConfig(level=level,
                        format='[%(asctime)s %(name)-12s %(levelname)s]: %(message)s',
                        datefmt='%m/%d %H:%M:%S')
    logger = logging.getLogger('checker')
    logger.setLevel(level)

    round_number = 0
    pool_flag_labels = []
    push_stats = {Result.UP: 0, Result.MUMBLE: 0, Result.CORRUPT: 0, Result.DOWN: 0}
    pull_stats = {Result.UP: 0, Result.MUMBLE: 0, Result.CORRUPT: 0, Result.DOWN: 0}

    while True:
        round_number += 1
        print('Round', round_number)

        md = Metadata(round_number)
        label = hashlib.md5(uuid.uuid4().bytes).hexdigest()[:16]

        chars = string.ascii_uppercase + string.ascii_lowercase + string.digits
        # cur_flag = '{0}='.format(hashlib.md5(uuid.uuid4().bytes).hexdigest())
        cur_flag = 'VolgaCTF{{{0}.{1}.{2}}}'.format(
            ''.join(random.choice(chars) for _ in range(301)),
            ''.join(random.choice(chars) for _ in range(301)),
            ''.join(random.choice(chars) for _ in range(301))
        )

        print('Pushing flag', cur_flag, end='\n')
        r = await push(team_ip, cur_flag, label, md)
        cur_res, label = r[0], r[1]
        print('result:', cur_res)
        push_stats[cur_res] += 1
        if cur_res == Result.UP:
            add_flag_to_pool(pool_flag_labels, cur_flag, label)

        for i in range(len(pool_flag_labels)):
            cur_flag = pool_flag_labels[i]['flag']
            label = pool_flag_labels[i]['label']
            print('Pulling flag', cur_flag, end='\n')
            r = await pull(team_ip, cur_flag, label, md)
            cur_res = r if type(r) is not tuple else r[0]
            print('result:', cur_res)
            pull_stats[cur_res] += 1
        print('\n')

        if round_number % 10 == 0:
            print_stats(push_stats, 'PUSH statistics')
            print_stats(pull_stats, 'PULL statistics', put_rn=True)

        await asyncio.sleep(timeout)


# endregion Themis imitator


if __name__ == '__main__':
    # start the checker
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(SERVICE_IP, ROUND_DURATION))
    loop.close()
