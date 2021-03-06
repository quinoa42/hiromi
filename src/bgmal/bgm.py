# -*- coding: utf-8 -*-
"""
    bgm_mal_immigration.bgm
    ~~~~~~~~~~~~~~~~~~~~~~~

    Deal with the bangumi APIs

    :copyright: (c) 2017 by quinoa42.
    :license: MIT, see LICENSE for more details.
"""

import logging
import time

import requests
from bs4 import BeautifulSoup

from hiromi.cache import period_cache

from .api import AnimeItem, AnimeWebsite, LoginFailedException

logger = logging.getLogger(__name__)


class Bangumi(AnimeWebsite):
    """Manipulate the bgm api"""

    def __init__(self, account, password):
        """Construct a bangumi object with given account and password

        :param str account: user's email address
        :param str password: user's password
        :returns: a ``Bangumi`` object

        """
        data = {
            'password': password,
            'username': account,
            'auth': 0,
            'sysuid': 0,
            'sysusername': 0
        }
        url = 'https://api.bgm.tv/auth?source=onAir'
        r = requests.post(url, data=data)
        r.raise_for_status()

        output = r.json()

        try:
            self._uid = output['username']
            self._auth = output['auth']
        except Exception as e:
            logger.error("logging failed: %s", e)
            raise LoginFailedException()

    def watching_list(self):
        r = requests.get(
            "https://api.bgm.tv/user/"
            "{0}/collection?cat=watching".format(self._uid)
        )
        r.raise_for_status()
        data = r.json()
        return [
            AnimeItem(
                status=item['ep_status'],
                episode=(
                    item['subject']['eps'] if 'eps' in item['subject'] else 13
                ),
                userscore=None,
                score=None,
                id=item['subject']['id'],
                title=item['subject']['name']
            ) for item in data
        ]

    @period_cache("bgm", period=3600)
    def watched_list(self):
        """Return the watched list of anime

        :returns: a list of anime entries, described in dict of name and score

        """

        def has_next_page(soup):
            """Return if this page have a next page.

            :param BeautifulSoup soup: the soup of the given page
            :returns: True or False

            """
            pages = soup.find(class_='page_inner')
            return pages.find_all(class_='p')[-1].string == '››'

        url = 'https://bgm.tv/anime/list/{0}/collect'.format(self._uid)
        page = 1
        watched = []
        while True:
            r = requests.get(url, params={'page': page})
            r.raise_for_status()
            soup = BeautifulSoup(r.content, 'lxml')
            items = soup.find_all('li', class_='item')
            for item in items:
                watched.append(self._bgmanime(item))
            if not has_next_page(soup):
                break
            page += 1
            time.sleep(1)

        return watched

    def search(self, title):
        """Return an ``AnimeItem`` object representing the anime entry
        of this search result.

        :param str title: the title user wish to search
        :returns: an ``AnimeItem`` object representing the search result
        :rtype: AnimeItem

        """
        url = 'https://api.bgm.tv/search/subject/{0}'.format(title)

        def get_raw_result():
            """Return the search result.

            :returns: a list of pre-edited items

            """
            params = {
                'responseGroup': 'large',
                'max_results': '11',
                'start': '0'
            }
            r = requests.get(url, params)
            r.raise_for_status()

            result = r.json()
            return result['list']

        def raw_to_AnimeItem(raw):
            """Return the parsed ``AnimeItem`` object for the given raw item.

            :param raw: the raw BeautifulSoup Tag
            :returns: a parsed AnimeItem
            :rtype: AnimeItem

            """
            return AnimeItem(
                raw['name'], raw['rating']['score'], None, raw['eps']
                if 'eps' in raw else 1, None, raw['id']
            )

        return raw_to_AnimeItem(
            next((raw for raw in get_raw_result() if raw['type'] == 2), None)
        )

    def mark_as_watched(self, anime_item):
        """Mark the given anime as watched with the given score, return true
        if this call succeeds.

        :param AnimeItem anime_item: an AnimeItem that the user want to mark
                                as watched.
        :returns: true or false
        :rtype: bool

        """
        pass

    def _bgmanime(self, item):
        """Build an AnimeItem with the given soup."""

        def score():
            """Return the user's score of this anime
            :returns: score
            :rtype: int

            """
            starsinfo = item.find(class_='starsinfo')['class']
            stars = (
                starsinfo[0] if starsinfo[0] != 'starsinfo' else starsinfo[-1]
            )
            return int(stars[6:])

        def title():
            """Return the title of this anime
            :returns: title of this anime
            :rtype: str

            """
            return (
                item.find(class_='grey').string
                if item.find(class_='grey') is not None else
                item.find(class_='l').string
            )

        def episodes():
            """TODO: Docstring for episodes.
            :returns: TODO

            """
            URL = (
                "https://api.bgm.tv/subject/{0}".format(
                    item['id'].split('_')[-1]
                )
            )
            r = requests.get(
                URL,
                params={
                    'responseGroup': 'simple',
                    'source': 'onAir',
                    'auth': self._auth
                }
            )
            r.raise_for_status()
            data = r.json()
            episode = data['eps'] if data['eps'] != 0 else 1
            return {
                'episode': episode,
                'status': episode,
                'score': data['rating']['score'],
                'id': data['id']
            }

        return AnimeItem(title=title(), userscore=score(), **episodes())

    def increment_status(self, anime_item):
        """Mark the next episode of this given anime as watched.

        :param AnimeItem anime_item: an AnimeItem that the user want to mark
                                as watched.
        :returns: true or false
        :rtype: bool

        """

        def get_all_episodes(anime_id):
            url = (
                "https://api.bgm.tv/subject/{0}?responseGroup=large".
                format(anime_id)
            )
            r = requests.get(url)
            r.raise_for_status()
            return [ep['id'] for ep in r.json()['eps']]

        def get_watched_episodes(anime_id):
            url = "https://api.bgm.tv/user/{0}/progress".format(self._uid)
            params = {
                'source': 'onAir',
                'auth': self._auth,
                'subject_id': anime_id
            }
            r = requests.get(url, params=params)
            r.raise_for_status()
            return [ep['id'] for ep in r.json()['eps']]

        watched = get_watched_episodes(anime_item.id)
        all_episodes = get_all_episodes(anime_item.id)
        all_episodes.sort()
        next_episode = next(
            filter(lambda x: x not in watched, all_episodes), None
        )
        if next_episode is None:
            return False
        url = (
            'https://api.bgm.tv/ep/'
            '{0}/status/watched?source=onAir'.format(next_episode)
        )
        data = {'auth': self._auth}
        r = requests.post(url, data=data)
        r.raise_for_status()

        result = r.json()
        if result['code'] == 200:
            return True
        else:
            return False
