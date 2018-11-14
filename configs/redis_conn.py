# -*- coding: utf-8 -*-

import os
import redis

REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')

RDB_HISTORY = redis.StrictRedis(REDIS_HOST, port=6379, db=3)
