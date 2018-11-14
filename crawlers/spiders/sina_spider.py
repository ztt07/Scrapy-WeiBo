# -*- coding: UTF-8 -*-
import json
import csv
import scrapy
import time
from datetime import date, timedelta

from text_cleaning import convert_html_to_text

from configs.redis_conn import RDB_HISTORY


UID_HiS_KEY = 'sina:%s:his'


def time_from_str(timestr):
    t = [i.strip() for i in timestr.split('-') if i.strip()]

    if len(t) == 3:
        return '-'.join(t)

    if len(t) == 2:
        year = time.gmtime().tm_year
        return '-'.join([str(year)] + t)

    if len(t) == 1:
        yesterday = date.today() - timedelta(1)
        return yesterday.strftime('%Y-%m-%d')

    return None


def convert_json_to_csv(json_filename, csv_filename, csv_headers):
    with open(json_filename, 'r', encoding='utf-8') as f_json:
        with open(csv_filename, 'w', encoding='utf-8') as f_csv:
            csv_writer = csv.writer(f_csv)
            csv_writer.writerow(csv_headers)

            for line in f_json:
                data = json.loads(line)
                csv_record = [data.get(i, '-') for i in csv_headers]
                csv_writer.writerow(csv_record)


def merge_json_records(in_filename, out_filename):
    data = []  # default
    with open(in_filename, 'r', encoding='utf-8') as fr:
        data = [json.loads(line) for line in fr]

    with open(out_filename, 'w', encoding='utf-8') as fw:
        json.dump(data, fw)

    return len(data)


class SinaSpider(scrapy.Spider):
    name = 'sina'

    def start_requests(self):
        url = 'https://m.weibo.cn/api/container/getIndex?type=uid&value=%s' % self.uid
        yield scrapy.Request(url=url, callback=self.read_containerid)

    def setup(self):
        self.json_filename = 'tmp-sina-%s.json' % self.uid
        self.f_json = open(self.json_filename, 'w', encoding='utf-8')

        mode_value = getattr(self, 'continue_mode', 'FAlSE')
        self.is_continue_mode = (mode_value.upper() in ('Y', 'YES','TRUE'))

        key = UID_HiS_KEY % self.uid
        value = RDB_HISTORY.get(key)
        self.redis_data = json.loads(value) if value else {
            'oldest_create_at': None,
            'newest_create_at': None,
            'crawled_pages': 0,
        }

        if self.is_continue_mode:
            self.cur_page = int(self.redis_data.get('crawled_pages', 0))
            self.stop_date = None
            self.real_time_update_redis = True
        else:
            self.cur_page = 0
            self.stop_date = self.redis_data.get('newest_create_at')
            self.real_time_update_redis = (not self.stop_date)

    def cleandown(self):
        self.f_json.close()

        timestamp = time.strftime('%Y%m%d_%H%M%S', time.gmtime())

        file_basename = 'sina-%s-%sUTC' % (self.uid, timestamp)

        csv_filename = '%s.csv' % file_basename
        csv_haeders = [
            'user_id',
            'created_at',
            'status_id',
            'is_contained_html',
            'cleaned_content',
            'original_content',
            'comment_count',
            'reposts_coun',
            'favorite_count',
            'collect_count',
            'images',
            'video',
            'is_need_ocr',
            'is_repost',
        ]

        convert_json_to_csv(self.json_filename, csv_filename, csv_haeders)

        out_jsonfile = '%s.json' % file_basename
        n = merge_json_records(self.json_filename, out_jsonfile)

        print('=== crawling finished ===')
        print('number of NEW records: %s' % n)
        print(json.dumps(self.redis_data, indent=4))
        print('json file: %s, csv file: %s' % (out_jsonfile, csv_filename))
        print('=' * 20)

    def update_redis(self, oldest_create_at, newest_create_at):
        should_stop = False
        crawled_pages = self.cur_page

        should_update_redis = False

        if self.real_time_update_redis:
            self.redis_data['oldest_create_at'] = oldest_create_at
            self.redis_data['crawled_pages'] = crawled_pages

            should_update_redis = True

        if self.cur_page < 2:
            self.redis_data['newest_create_at'] = max(self.redis_data['newest_create_at'] or '', newest_create_at)

        if self.stop_date and oldest_create_at < self.stop_date:
            self.redis_data['crawled_pages'] += crawled_pages

            should_update_redis = True
            should_stop = True

        if should_update_redis:
            # print('updating redis: %s' % json.dumps(self.redis_data))
            key = UID_HiS_KEY % self.uid
            RDB_HISTORY.set(key, json.dumps(self.redis_data))

        return should_stop

    def build_url(self):
        self.cur_page += 1
        print('requesting. containerID=%s, page=%s' % (self.containerid, self.cur_page))
        return 'https://m.weibo.cn/api/container/getIndex?containerid=%s&page=%s' % (self.containerid, self.cur_page)

    def read_containerid(self, response):
        print('Active UA: %s' % response.request.headers['User-Agent'])

        res = json.loads(response.body)
        tabs = res.get('data', {}).get('tabsInfo', {}).get('tabs', [])

        self.containerid = None
        for tab in tabs:
            if tab['tab_type'] == 'weibo':
                self.containerid = tab['containerid']
                break

        # print('container ID: %s' % self.containerid)
        if self.containerid:

            self.setup()

            url = self.build_url()
            yield scrapy.Request(url=url, callback=self.display_tweets)

    def dump_full_response(self, response):
        filename = 'sina-test.json'
        with open(filename, 'wb') as f:
            f.write(response.body)
        self.log('Saved file %s' % filename)

    def display_tweets(self, response):
        try:
            res = json.loads(response.body)
        except Exception:
            print('parse response body error: %s' % response.body)
            return
        else:
            cards = res.get('data', {}).get('cards', [])

            if len(cards) > 0:
                should_stop = self.build_output_json(cards)
                if should_stop:
                    return

                url = self.build_url()
                yield scrapy.Request(url=url, callback=self.display_tweets)
            else:
                self.cleandown()

    def build_output_json(self, cards):

        newest_create_at = None
        oldest_create_at = None

        for card in cards:

            # 对象ID, agentid
            user_id = card.get('mblog', {}).get('user', {}).get('id')

            if not user_id:
                continue

            # 正文
            original_content = card.get('mblog', {}).get('text')
            cleaned_content = convert_html_to_text(original_content)
            is_contained_html = (original_content != cleaned_content)
            # 评论数
            comment_count = card.get('mblog', {}).get('comments_count')
            # 转发数
            reposts_count = card.get('mblog', {}).get('reposts_count')
            # 点赞数
            favorite_count = card.get('mblog', {}).get('attitudes_count')
            # 收藏数
            collect_count = card.get('mblog', {}).get('pending_approval_count')

            # 状态唯一ID，用于去重，即抓取对象的唯一标志
            status_id = card.get('mblog', {}).get('bid')

            # 图片数组
            images = [p['url'] for p in card.get('mblog', {}).get('pics', []) if 'url' in p]

            # 视频地址
            video = card.get('mblog', {}).get('page_info', {}).get('page_url')

            # 创建时间
            created_at = card.get('mblog', {}).get('created_at')

            # # 只有图片，没有正文，需要ocr
            is_need_ocr = not (cleaned_content and len(cleaned_content) > 0)

            # 是否为转发微博
            is_repost = ('retweeted_status' in card.get('mblog', {}))

            self.f_json.write(json.dumps({
                'user_id': user_id,
                'is_contained_html': is_contained_html,
                'original_content': original_content,
                'cleaned_content': cleaned_content,
                'comment_count': comment_count,
                'repost_count': reposts_count,
                'favorite_count': favorite_count,
                'collect_count': collect_count,
                'status_id': status_id,
                'images': images,
                'video': video,
                'created_at': created_at,
                'is_need_ocr': is_need_ocr,
                'is_repost': is_repost
            }))
            self.f_json.write('\n')

            std_date = time_from_str(created_at)
            if std_date:
                if not newest_create_at or newest_create_at < std_date:
                    newest_create_at = std_date
                if not oldest_create_at or oldest_create_at > std_date:
                    oldest_create_at = std_date

        return self.update_redis(oldest_create_at, newest_create_at)
