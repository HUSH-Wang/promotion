# -*- coding: utf-8 -*-
from __future__ import unicode_literals, division, absolute_import
from builtins import *  # noqa pylint: disable=unused-import, redefined-builtin

import logging

from flexget import plugin
from flexget.event import event
from flexget.config_schema import one_or_more

import requests
from bs4 import BeautifulSoup
import re

log = logging.getLogger('promotion')


class Filter_Promotion(object):
	"""
		Detect torrent's *current* promotion status.
		Only support sites based on NexusPHP
	Support sites (tested):
		HDChina TJUPT NYPT Ourbits BYRBT NPUBits MTeam TTG...

		Example::
			promotion: 
			  action: accept
			  cookie: * your cookie here *
			  username: * your username here *
			  promotion: free/twoupfree/halfdown/twouphalfdown/thirtypercent/none
			  not_hr: yes [optional]

	"""

	schema = {'type': 'object',
	          'properties': {
		          'action': {
			          'type': 'string',
			          'enum': ['accept', 'reject'],
			          'default': 'accept',
		          },
		          'cookie': {
			          'type': 'string',
		          },
		          'username': {
			          'type': 'string',
		          },
		          'promotion': one_or_more({
					  'type': 'string', 
					  'enum': ['free', 'twoup', 'halfdown', 'twoupfree', 'twouphalfdown', 'thirtypercent', 'none']
				  }),
		          'not_hr': {
			          'type': 'boolean',
			          'enum': [True, False],
			          'default': False,
		          },
				  'amount': {
			          'type': 'integer',
			          'default': 10,
		          },
	          },
	          }

	# Run later to avoid unnecessary lookups
	@plugin.priority(115)
	def on_task_filter(self, task, config):
		# some time flexget do strange things, do this to prevent exception
		if not task.entries:
			return False

		# check some details first
		# `amount` range from 1 to 100
		if (config['amount']<1 or config['amount']>100):
			log.critical('amount out of range. [1,100]')
			return False
		
		# check entry's link field
		if not task.entries[0].get('link'):
			log.critical('link not found, plz add "other_fields: [link]" to rss plugin config')
			return False
		
		##`not_hr` is only available for certain sites
		if config['not_hr']:
			if not re.findall('ourbits|totheglory', task.entries[0].get('link')):
				log.critical('"not_hr" parameter is not available for this site')
				return False

		# check amount one time. DOSE NOT support multi threads now
		seed_amount = 0
		for entry in task.entries:
			seed_amount += 1
			if seed_amount > config['amount']:
				entry.reject('reach max seed amount [%d] one time.' % (config['amount']))
			else:
				link = entry.get('link')
				if config['action'] == 'accept':
					flag, promo = self.detect_promotion_status(link, config)
					if flag:
						entry.accept('promotion is [%s]' % (promo), remember=True)
						#entry.accept('Entry `%s` is `%s`' % (entry['title'], promo), remember=True)
					else:
						entry.reject('promotion [%s] not mach' % (promo))
						#entry.reject('Entry `%s` is `%s` not mach' % (entry['title'], promo))

	def detect_promotion_status(self, link, config):
		log.info('start to detect %s promotion status' % link)

		cookie = config['cookie']
		username = config['username']

		# get detail page
		headers = {
			'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Safari/537.36',
			'accept-encoding': 'gzip, deflate',
			'cookie': cookie,
		}
		
		try:
			r = requests.get(link, headers=headers, timeout=30)
			r.raise_for_status()
			r.encoding = r.apparent_encoding
			response = r.text
			#log.info('get page succeed')
		except:
			log.critical('get page failed, please check connection')
			try:
				log.info(response)
			except:
				log.info(r.status_code)
			finally:
				return False
 
		# assert login status
		try:
			assert username in response
			#log.info('cookie is valid')
		except:
			log.critical('cookie is expired or username not right, response is logged')
			log.info(response)
			return False

		# assert torrent id
		try:
			assert '没有该ID的种子' not in response
			assert '你没有该权限！' not in response
		
		# log.info('torrent id is valid')
		except:
			log.critical('torrent id is not valid, torrent {} does not exist'.format(link))
			log.info(response)
			return False

		# get details_dict
		if "hdchina.org" in link:
			details_dict = self.analyze_hdc_detail(response)
		elif "tjupt.org" in link:
			details_dict = self.analyze_tju_detail(response)
		elif "ourbits.club" in link:
			details_dict = self.analyze_ob_detail(response)
		elif "npupt.com" in link:
			details_dict = self.analyze_npu_detail(response)
		elif "bt.byr.cn" in link:
			details_dict = self.analyze_byr_detail(response)
		elif "totheglory.im" in link:
			details_dict = self.analyze_ttg_detail(response)
		elif "chdbits.co" in link:
			details_dict = self.analyze_chd_detail(response)
		else:
			details_dict = self.analyze_nexusphp_detail(response)

		# process h&r
		if config['not_hr'] and details_dict['is_hr']:
			return False

		# return accept or reject according to config['promotion']
		for each in config['promotion']:
			if details_dict['promotion'] == each:
				return True, details_dict['promotion']
		
		return False, details_dict['promotion']


	def analyze_hdc_detail(self, response):
		convert = {
			'Free': 'free',
			'2X Free': 'twoupfree',
			'50%': 'halfdown',
			'2X 50%': 'twouphalfdown',  # never seen, key maybe wrong
			'30%': 'thirtypercent',
		}
		soup = BeautifulSoup(response, 'html.parser')
		topic_element = soup.find_all('h2', id="top")[0]
		promotion_element = topic_element.img
		if promotion_element:
			promotion = convert[promotion_element['alt']]
			log.info('torrent promotion status is {}'.format(promotion))
			return {'promotion': promotion}
		else:
			log.info('torrent has no promotion')
			return {'promotion': 'none'}

	def analyze_nexusphp_detail(self, response):
		soup = BeautifulSoup(response, 'html.parser')
		topic_element = soup.find_all('h1', id="top")[0]
		promotion_element = topic_element.b
		if promotion_element:
			promotion = promotion_element.font['class'][0]
			log.info('torrent promotion status is {}'.format(promotion))
			return {'promotion': promotion}
		else:
			log.info('torrent has no promotion')
			return {'promotion': 'none'}

	def analyze_byr_detail(self, response):
		soup = BeautifulSoup(response, 'html.parser')
		topic_element = soup.find_all('h1', id="share")[0]
		promotion_element = topic_element.b
		if promotion_element:
			promotion = promotion_element.font['class'][0]
			log.info('torrent promotion status is {}'.format(promotion))
			return {'promotion': promotion}
		else:
			log.info('torrent has no promotion')
			return {'promotion': 'none'}

	def analyze_tju_detail(self, response):
		soup = BeautifulSoup(response, 'html.parser')
		topic_element = soup.find_all('h1', id="top")[0]
		promotion_element = topic_element.font
		if promotion_element:
			promotion = promotion_element['class'][0]
			log.info('torrent promotion status is {}'.format(promotion))
			return {'promotion': promotion}
		else:
			log.info('torrent has no promotion')
			return {'promotion': 'none'}

	def analyze_ob_detail(self, response):
		details_dict = {}
		soup = BeautifulSoup(response, 'html.parser')
		topic_element = soup.find_all('h1', id="top")[0]

		promotion_element = topic_element.b
		if promotion_element:
			promotion = promotion_element.font['class'][0]
			log.info('torrent promotion status is {}'.format(promotion))
			details_dict['promotion'] = promotion
		else:
			log.info('torrent has no promotion')
			details_dict['promotion'] = 'none'

		hr_element = topic_element.img
		if hr_element:
			log.info('torrent is h&r')
			details_dict['is_hr'] = True
		else:
			log.info('torrent is not h&r')
			details_dict['is_hr'] = False

		return details_dict

	def analyze_npu_detail(self, response):
		convert = {
			'Free': 'free',
			'2X Free': 'twoupfree',
			'50%': 'halfdown',
			'2X 50%': 'twouphalfdown',
			'30%': 'thirtypercent',
		}
		soup = BeautifulSoup(response, 'html.parser')
		topic_element = soup.find_all('div', class_="jtextfill")[0]
		promotion_element = topic_element.span.img
		if promotion_element:
			promotion = convert[promotion_element['alt']]
			log.info('torrent promotion status is {}'.format(promotion))
			return {'promotion': promotion}
		else:
			log.info('torrent has no promotion')
			return {'promotion': 'none'}

	def analyze_ttg_detail(self, response):
		convert = {
			'free': 'free',
			'half': 'halfdown',
			'30': 'thirtypercent',
		}
		details_dict = {}
		soup = BeautifulSoup(response, 'html.parser')

		promotion_element = soup.find_all('img', class_="topic", src=re.compile(r".*pic/ico_.*"))
		if promotion_element:
			promotion_raw = re.findall(r'.*pic/ico_(.*).gif', promotion_element[0]['src'])[0]
			try:
				promotion = convert[promotion_raw]
				log.info('torrent promotion status is {}'.format(promotion))
			except:
				promotion = ''
				log.warning('torrent promotion status is {}, unsupported'.format(promotion_raw))
			details_dict['promotion'] = promotion
		else:
			log.info('torrent has no promotion')
			details_dict['promotion'] = 'none'

		hr_element = soup.find_all('img', alt='Hit & Run')
		if hr_element:
			log.info('torrent is h&r')
			details_dict['is_hr'] = True
		else:
			log.info('torrent is not h&r')
			details_dict['is_hr'] = False

		return details_dict

	def analyze_chd_detail(self, response):
		convert = {
			'Free': 'free',
			'2X Free': 'twoupfree',
			'50%': 'halfdown',
			'2X 50%': 'twouphalfdown',
			'30%': 'thirtypercent',
		}
		soup = BeautifulSoup(response, 'html.parser')
		topic_element = soup.find_all('h1', id="top")[0]
		promotion_element = topic_element.img
		if promotion_element:
			promotion = convert[promotion_element['alt']]
			log.info('torrent promotion status is {}'.format(promotion))
			return {'promotion': promotion}
		else:
			log.info('torrent has no promotion')
			return {'promotion': 'none'}


@event('plugin.register')
def register_plugin():
	plugin.register(Filter_Promotion, 'promotion', api_ver=2)
