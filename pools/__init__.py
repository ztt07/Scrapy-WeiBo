# -*- coding: utf-8 -*-
import random

from .ua import USER_AGENTS


def get_random_ua():
    return random.choice(USER_AGENTS)
