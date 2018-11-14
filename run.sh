#!/bin/bash

read -p 'Input weibo UID: ' uid
read -p 'continue mode [Y/n]? N: ' continue_mode
# uid=1594052081
# continue_mode=n
scrapy crawl -L WARNING sina -a uid=$uid -a continue_mode=$continue_mode
