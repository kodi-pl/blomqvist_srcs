import sys
import re
import os
import time

from collections.abc import Sequence, Mapping
from collections import namedtuple
from datetime import date, datetime, timedelta
from contextlib import contextmanager
import random
from inspect import ismethod
from kodipl import SimplePlugin
from kodipl.site import JSONDecodeError
from kodipl.addon import call
from kodipl.addon import entry
from kodipl.logs import log, flog
from kodipl.kodi import K18
from kodipl.utils import adict
from kodipl.format import sectfmt

from urllib.parse import parse_qs, parse_qsl, urlencode, quote_plus, unquote_plus

if sys.version_info >= (3, 0):
    basestring = str
    unicode = str


import json
import io


def save_ints(path, seq):
    if seq:
        log.error('### %r %r %r' % (io.open, type(seq), path))
        with io.open(path, 'w') as f:
            json.dump(tuple(seq), f)


def load_ints(path):
    with io.open(path, 'r') as f:
        return set(json.load(f))



from threading import Thread
import requests
import urllib3  # already used by "requests"
from kodipl.kodi import xbmcgui
from kodipl.kodi import xbmcplugin
from kodipl.kodi import xbmcaddon
from kodipl.kodi import xbmc
from kodipl.kodi import xbmcvfs
import inputstreamhelper

from resources.lib.udata import AddonUserData
# from resources.lib.tools import U, uclean, NN, fragdict


MetaDane = namedtuple('MetaDane', 'tytul opis foto sezon epizod fanart thumb landscape poster allowed')
MetaDane.__new__.__defaults__ = 5*(None,)
MetaDane.art = property(lambda self: {k: v for k in 'fanart thumb landscape poster'.split()
                                      for v in (getattr(self, k),) if v})

ExLink = namedtuple('ExLink', 'gid slug mode a1 a2')
ExLink.__new__.__defaults__ = 3*(None,)
ExLink.new = classmethod(lambda cls, exlink: cls(*exlink.split(':')[:5]))
# slug = "eurosport", mode = "schedule"
ExLink.beginTimestamp = property(lambda self: self.a1)
ExLink.endTimestamp = property(lambda self: self.a2)


UA = 'okhttp/3.3.1 Android'
# UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:87.0) Gecko/20100101 Firefox/87.0'
PF = 'ANDROID_TV'
# PF = 'BROWSER

base_url = sys.argv[0]
addon_handle = int(sys.argv[1])
params = dict(parse_qsl(sys.argv[2][1:]))
addon = xbmcaddon.Addon(id='plugin.video.playermb')

PATH = addon.getAddonInfo('path')
DATAPATH = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
CACHEPATH = os.path.join(DATAPATH, 'cache')

RESOURCES = os.path.join(PATH, 'resources')
COOKIEFILE = os.path.join(DATAPATH, 'player.cookie')
SUBTITLEFILE = os.path.join(DATAPATH, 'temp.sub')
MEDIA = os.path.join(RESOURCES, 'media')

ADDON_ICON = os.path.join(RESOURCES, '../icon.png')
FANART = os.path.join(RESOURCES, '../fanart.jpg')
sys.path.append(os.path.join(RESOURCES, 'lib'))

HISTORY_SIZE = 50

addon_data = AddonUserData(os.path.join(DATAPATH, 'data.json'))
exlink = params.get('url')
# name = params.get('name')
# page = params.get('page', '')
# rys = params.get('image')
kukz = ''

slug_blacklist = {
    'pobierz-i-ogladaj-offline',
}


TIMEOUT = 15


# URL to test: https://wrong.host.badssl.com
class GlobalOptions(object):
    """Global options."""

    def __init__(self, settings):
        self.settings = settings
        self._session_level = 0
        self.verify_ssl = self.settings.get_bool('verify_ssl')
        self.use_urllib3 = self.settings.get_bool('use_urllib3')
        self.ssl_dialog_launched = self.settings.get_bool('ssl_dialog_launched')

    def ssl_dialog(self, using_urllib3=False):
        if self.ssl_dialog_launched and self._session_level == 0:
            return
        using_urllib3 = bool(using_urllib3)
        options = [u'Wyłącz weryfikację SSL', u'Bez zmian']
        if using_urllib3:
            options.insert(0, u'Użyj wolniejszego połączenia (zalecane)')
        num = xbmcgui.Dialog().select(u'Problem z połączeniem SSL, co teraz?', options)
        if using_urllib3:
            # getRequests3() error
            if num == 0:  # Użyj wolniejszego połączenia
                self.use_urllib3 = False
            elif num == 1:  # Wyłącz weryfikację SSL
                self.verify_ssl = False
        else:
            # getRequests() error
            if num == 0:  # Wyłącz weryfikację SSL
                self.verify_ssl = False
        self.settings.set_bool('use_urllib3', self.use_urllib3)
        self.settings.set_bool('verify_ssl', self.verify_ssl)
        self.settings.set_bool('ssl_dialog_launched', True)
        self.ssl_dialog_launched = True

    def __enter__(self):
        self._session_level += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._session_level -= 1


# goptions = GlobalOptions()


def media(name, fallback=None):
    """Returns full path to media file."""
    path = os.path.join(MEDIA, name)
    if fallback and not os.path.exists(path):
        return fallback
    return path


def build_url(query):
    query = deunicode_params(query)
    return base_url + '?' + urlencode(query)


def add_item(url, name, image, mode, folder=False, isPlayable=False, infoLabels=None, movie=True,
             itemcount=1, page=1, fanart=None, moviescount=0, properties=None, thumb=None,
             contextmenu=None, art=None, linkdata=None, fallback_image=ADDON_ICON,
             label2=None):
    assert False
    list_item = xbmcgui.ListItem(label=name)
    if label2 is not None:
        list_item.setLabel2(label2)
    if isPlayable:
        list_item.setProperty("isPlayable", 'true')
    if not infoLabels:
        infoLabels = {'title': name, 'plot': name}
    list_item.setInfo(type="video", infoLabels=infoLabels)
    if not image:
        image = fallback_image
    if image and image.startswith('//'):
        image = 'https:' + image
    art = {} if art is None else dict(art)
    if fanart:
        art['fanart'] = fanart
    if thumb:
        art['thumb'] = fanart
    art.setdefault('thumb', image)
    art.setdefault('poster', image)
    art.setdefault('banner', art.get('landscape', image))
    art.setdefault('fanart', FANART)
    art = {k: 'https:' + v if v and v.startswith('//') else v for k, v in art.items()}
    list_item.setArt(art)
    if properties:
        list_item.setProperties(properties)
    if contextmenu:
        list_item.addContextMenuItems(contextmenu, replaceItems=False)
    # link data used to build link,to support old one
    linkdata = {} if linkdata is None else dict(linkdata)
    linkdata.setdefault('name', name)
    linkdata.setdefault('image', image)
    linkdata.setdefault('page', page)
    # add item
    ok = xbmcplugin.addDirectoryItem(
        handle=addon_handle,
        url=build_url({'mode': mode, 'url': url, 'page': linkdata['page'], 'moviescount': moviescount,
                       'movie': movie, 'name': linkdata['name'], 'image': linkdata['image']}),
        listitem=list_item,
        isFolder=folder)
    return ok


def setView(typ):
    if addon.getSetting('auto-view') == 'false':
        xbmcplugin.setContent(addon_handle, 'videos')
    else:
        xbmcplugin.setContent(addon_handle, typ)


def remove_html_tags(text, nice=True):
    """Remove html tags from a string"""
    if nice:
        if re.match(r'^<table .*<td [^>]+$', text, re.DOTALL):
            return ''  # remove player.pl lead fackup
        text = re.sub(r'<p\b[^>]*?>\s*</p>|<br/?>', '\n', text, 0, re.DOTALL)
    return re.sub('<.*?>', '', text, 0, re.DOTALL)


def dialog_progress():
    return xbmcgui.DialogProgress()


def xbmc_sleep(time):
    return xbmc.sleep(time)


def deunicode_params(params):
    if sys.version_info < (3,) and isinstance(params, dict):
        def encode(s):
            return s.encode('utf-8') if isinstance(s, unicode) else s
        params = {encode(k): encode(v) for k, v in params.items()}
    return params


class ThreadCall(Thread):
    """
    Async call. Create thread for func(*args, **kwargs), should be started.
    Result will be in thread.result after therad.join() call.
    """

    def __init__(self, func, *args, **kwargs):
        super(ThreadCall, self).__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.result = None

    def run(self):
        self.result = self.func(*self.args, **self.kwargs)

    @classmethod
    def started(cls, func, *args, **kwargs):
        th = cls(func, *args, **kwargs)
        th.start()
        return th


class ThreadPool(object):
    """
    Async with-statement.
    """

    def __init__(self, max_workers=None):
        self.result = None
        self.thread_list = []
        self.thread_by_id = {}
        if max_workers is None:
            # number of workers like in Python 3.8+
            self.max_workers = min(32, os.cpu_count() + 4)
        else:
            self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def start(self, func, *args, **kwargs):
        th = ThreadCall.started(func, *args, **kwargs)
        self.thread_list.append(th)

    def start_with_id(self, id, func, *args, **kwargs):
        th = ThreadCall.started(func, *args, **kwargs)
        self.thread_list.append(th)
        self.thread_by_id[id] = th

    def join(self):
        for th in self.thread_list:
            th.join()

    def close(self):
        self.join()
        if self.thread_by_id:
            self.result = self.result_dict
        else:
            self.result = self.result_list

    @property
    def result_dict(self):
        return adict((key, th.result) for key, th in self.thread_by_id.items())

    @property
    def result_list(self):
        return [th.result for th in self.thread_list]


def idle():

    if float(xbmcaddon.Addon('xbmc.addon').getAddonInfo('version')[:4]) > 17.6:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
    else:
        xbmc.executebuiltin('Dialog.Close(busydialog)')


def busy():

    if float(xbmcaddon.Addon('xbmc.addon').getAddonInfo('version')[:4]) > 17.6:
        xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    else:
        xbmc.executebuiltin('ActivateWindow(busydialog)')


def PLchar(*args, **kwargs):
    sep = kwargs.pop('sep', ' ')
    if kwargs:
        raise TypeError('Unexpected keywoard arguemnt(s): %s' % ' '.join(kwargs.keys()))
    out = ''
    for i, char in enumerate(args):
        if type(char) is not str:
            char = char.encode('utf-8')
        char = char.replace('\\u0105','\xc4\x85').replace('\\u0104','\xc4\x84')
        char = char.replace('\\u0107','\xc4\x87').replace('\\u0106','\xc4\x86')
        char = char.replace('\\u0119','\xc4\x99').replace('\\u0118','\xc4\x98')
        char = char.replace('\\u0142','\xc5\x82').replace('\\u0141','\xc5\x81')
        char = char.replace('\\u0144','\xc5\x84').replace('\\u0144','\xc5\x83')
        char = char.replace('\\u00f3','\xc3\xb3').replace('\\u00d3','\xc3\x93')
        char = char.replace('\\u015b','\xc5\x9b').replace('\\u015a','\xc5\x9a')
        char = char.replace('\\u017a','\xc5\xba').replace('\\u0179','\xc5\xb9')
        char = char.replace('\\u017c','\xc5\xbc').replace('\\u017b','\xc5\xbb')
        char = char.replace('&#8217;',"'")
        char = char.replace('&#8211;',"-")
        char = char.replace('&#8230;',"...")
        char = char.replace('&#8222;','"').replace('&#8221;','"')
        char = char.replace('[&hellip;]',"...")
        char = char.replace('&#038;',"&")
        char = char.replace('&#039;',"'")
        char = char.replace('&quot;','"')
        char = char.replace('&nbsp;',".").replace('&amp;','&')
        if i:
            out += sep
        out += char
    return out


def historyLoad():
    return addon_data.get('history.items', [])


def historyAdd(entry):
    if not isinstance(entry, unicode):
        entry = entry.decode('utf-8')
    history = historyLoad()
    history.insert(0, entry)
    addon_data.set('history.items', history[:HISTORY_SIZE])


def historyDel(entry):
    if not isinstance(entry, unicode):
        entry = entry.decode('utf-8')
    history = [item for item in historyLoad() if item != entry]
    addon_data.set('history.items', history[:HISTORY_SIZE])


def historyClear():
    addon_data.remove('history.items')


class CountSubfolders(object):
    """Count subfolders (avaliable items in sections) with statement object."""

    def __init__(self, plugin, data, loader, kwargs, sumarize_item=False):
        self.plugin = plugin
        self.data = data
        self.loader = loader
        self.kwargs = kwargs
        self._count = None
        self.sumarize_item = sumarize_item

    @property
    def count(self):
        """Returns avaliable item count in section by section id."""
        if self._count is None:
            def convert(data):
                if isinstance(data, Mapping):
                    return sum(1 for item in data.get('items', data) if self.plugin.is_allowed(item))
                elif isinstance(data, Sequence):
                    return sum(1 for item in data if self.plugin.is_allowed(item))
                return data

            # self.plugin.refreshTokenTVN()
            xbmc.log('PLAYER.PL: count folder start', xbmc.LOGDEBUG)
            threads = {item['id']: ThreadCall.started(self.loader, item, **self.kwargs)
                       for item in self.data}
            if self.sumarize_item and len(self.data) > 1:
                threads[None] = ThreadCall.started(self.loader, {'id': None}, **self.kwargs)
            xbmc.log('PLAYER.PL: count folder prepared', xbmc.LOGDEBUG)
            for th in threads.values():
                th.join()
            xbmc.log('PLAYER.PL: count folder joined', xbmc.LOGDEBUG)
            self._count = {sid: convert(thread.result) for sid, thread in threads.items()}
            xbmc.log('PLAYER.PL: count folder catch data: %r' % self._count, xbmc.LOGINFO)
        return self._count

    def get(self, vid):
        """Get count for Vod ID."""
        return self.count.get(vid, 0)

    def title(self, item, title, info=None):
        """Change title name (and title in info if not None)."""
        if self.plugin.settings.available_only:
            count = self.count.get(item['id'], 0)
            if count:
                fmt = u'{title} [COLOR :gray]({count})[/COLOR]'
            else:
                fmt = u'{title} [COLOR :gray]([COLOR red]brak[/COLOR])[/COLOR]'
            title = fmt.format(title=title, count=count)
            if info is not None:
                info['title'] = title  # K19 uses infoLabels["title"] with SORT_METHOD_TITLE
        return title


class API(object):
    """API proxy to collect all URLs."""

    def __init__(self, base):
        self.base = base

    def __getattribute__(self, key):
        value = super(API, self).__getattribute__(key)
        if key.startswith('_') or key == 'base' or '//' in value:
            return value
        base = super(API, self).__getattribute__('base')
        if base is None:
            return value
        if not base.endswith('/'):
            base += '/'
        return base + value


class PlayerPL(SimplePlugin):

    MaxMax = 10000

    def __init__(self):
        base = 'https://player.pl/playerapi/'
        super(PlayerPL, self).__init__(base=base, cookiefile=COOKIEFILE)
        self.colors['1'] = 'orange'
        self.colors['2'] = 'blue'
        self.colors['warn'] = 'orange'
        self.colors['missing'] = 'khaki'
        self.colors['gray'] = 'gray'

        self.api = API(base)
        self.api.login = 'https://konto.tvn.pl/oauth/'
        self.api.category_list = 'item/category/list'
        self.api.category_genre_list = 'item/category/{cid}/genre/list'
        self.api.vod_list = 'product/vod/list'
        self.api.live_list = 'product/live/list'
        self.api.live_plus_list = 'product/section/list/live_plus'
        self.api.section_list = 'product/section/list'
        self.api.section_list_slug = 'product/section/list/{slug}'
        self.api.section = 'product/section/{id}'
        self.api.player_configuration = 'product/{vid}/player/configuration'
        self.api.vod_playlist = 'item/{vid}/playlist'
        self.api.series = 'product/vod/serial/{id}'
        self.api.season_list = 'product/vod/serial/{id}/season/list'
        self.api.episode_list = 'product/vod/serial/{id}/season/{sid}/episode/list'

        self.GETTOKEN = self.api.login + 'tvn-reverse-onetime-code/create'
        self.POSTTOKEN = self.api.login + 'token'
        self.SUBSCRIBER = self.api.base + 'subscriber/login/token'
        self.SUBSCRIBERDETAIL = self.api.base + 'subscriber/detail'
        self.JINFO = self.api.base + 'info'
        self.TRANSLATE = self.api.base + 'item/translate'
        self.KATEGORIE = self.api.base + 'item/category/list'
        self.GATUNKI_KATEGORII = self.api.base + 'item/category/{cid}/genre/list'

        self.PRODUCTVODLIST = self.api.base + 'product/vod/list'

        self._mylist = None

        self.PARAMS = {'4K': 'true', 'platform': PF}

        self.HEADERS3 = {
            'Host': 'konto.tvn.pl',
            'user-agent': UA,
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8'
        }

        #: Data from last _refreshTokenTVN()
        self._tokenTVN_data = None
        self.update_headers2()

        self.MYLIST_CACHE_TIMEOUT = 3 * 3600  # cache valid time for mylist: 3h
        self.partial_size = self.settings.get_int('partial_size', 1000)
        self.force_media_fanart = True
        self.force_media_fanart_width = 1280
        self.force_media_fanart_quality = 85
        self._precessed_vid_list = set()
        self.dywiz = '–'
        self.hard_separator = ' '
        self.week_days = (u'poniedziałek', u'wtorek', u'środa', u'czwartek', u'piątek', u'sobota', u'niedziela')
        if not self.settings.days_ago:
            self.settings.days_ago = 31

        self.all_items_title = '[B]Wszystkie[/B]'
        self.categories_without_genres = set(addon.getSetting('categories_without_genres').split(','))
        ### xbmcplugin.setPluginFanart(self.handle, FANART, '#ff000066')

    def params(self, maxResults=False, **kwargs):
        """
        Get default query params. Extend self.PARAMS.

        maxResults : bool or int
            False to skip, Ftrue for auto or integer
        kwargs : dict(str, any)
            Extra pamars appended to result
        """
        params = dict(self.PARAMS)
        if maxResults or isinstance(maxResults, int):
            if maxResults is True:
                # maxResults = self.MaxMax if self.settings.available_only else self.partial_size
                maxResults = self.MaxMax
            params['maxResults'] = maxResults or 0
            params['firstResult'] = kwargs.pop('firstResult', 0)
        params.update(kwargs)
        return params

    def update_headers2(self):
        self.HEADERS2 = {
            'Authorization': 'Basic',
            'API-DeviceInfo': '%s;%s;Android;9;%s;1.0.38(62);' % (
                self.settings.usagent, self.settings.usagentver, self.settings.maker),
            'API-DeviceUid': self.settings.device_id,
            'User-Agent': UA,
            'Host': 'player.pl',
            'X-NewRelic-ID': 'VQEOV1JbABABV1ZaBgMDUFU=',
            'API-Authentication': self.settings.access_token,
            'API-SubscriberHash': self.settings.user_hash,
            'API-SubscriberPub': self.settings.user_pub,
            'API-ProfileUid': self.settings.selected_profile_id,
        }

    def _refreshTokenTVN(self):
        params = ('grant_type=refresh_token&refresh_token=%s&client_id=Player_TV_Android_28d3dcc063672068' %
                  self.settings.refresh_token)
        try:
            data = self.jpost(self.POSTTOKEN, data=params, headers=self.HEADERS3)
        except JSONDecodeError:
            xbmc.log('PLAYER.PL: Can not refresh token, there is no JSON', xbmc.LOGERROR)
            return
        flog('****************** {data!r}')
        if data.get('error_description') == 'Token is still valid.':
            return
        self.settings.access_token = data.get('access_token')
        self.settings.user_pub = data.get('user_pub')
        self.settings.user_hash = data.get('user_hash')
        self.settings.refresh_token = data.get('refresh_token')
        self.update_headers2()
        return data

    def refreshTokenTVN(self):
        if self._tokenTVN_data is None:
            self._tokenTVN_data = self._refreshTokenTVN()
        return self._tokenTVN_data

    def get_meta_data(self, data):
        if not data.get('active', True):
            return '', '', '', None, None
        tytul = data['title']
        if data.get('uhd'):
            tytul = '%s [4K]' % (tytul or '')
        opis = data.get("description")
        if not opis:
            opis = data.get("lead")
        if opis:
            opis = remove_html_tags(opis).strip()
        images = {}
        # See: https://kodi.wiki/view/Artwork_types
        # New art images must be added to MetaDane
        for prop, (iname, uname) in {'foto': ('smart_tv', 'mainUrl'),
                                     'fanart': ('smart_tv', 'mainUrl'),
                                     'thumb': ('smart_tv', 'miniUrl'),
                                     'poster': ('vertical', 'mainUrl'),
                                     'landscape': ('smart_tv', 'mainUrl')}.items():
            try:
                images[prop] = data['images'][iname][0][uname]
            except (KeyError, IndexError) as exc:
                xbmc.log('PLAYER.PL: no image %s.%s %r in %r' % (
                    iname, uname, exc, data.get('images')), xbmc.LOGDEBUG)
                images[prop] = None
        if self.force_media_fanart and images['fanart']:
            iurl, _, iparams = images['fanart'].partition('?')
            iparams = dict(parse_qsl(iparams))
            if iparams.get('dstw', '').isdigit() and iparams.get('dstw', '').isdigit():
                w, h = int(iparams['dstw']), int(iparams['dsth'])
                if w != self.force_media_fanart_width:
                    iparams['dstw'] = self.force_media_fanart_width
                    iparams['dsth'] = h * self.force_media_fanart_width // (w or 1)
                iparams['quality'] = self.force_media_fanart_quality
            images['fanart'] = '%s?%s' % (iurl, urlencode(iparams))
        sezon = bool(data.get('showSeasonNumber')) or data.get('type') == 'SERIAL'
        epizod = bool(data.get("showEpisodeNumber"))
        allowed = self.is_allowed(data)
        return MetaDane(tytul, opis, sezon=sezon, epizod=epizod, allowed=allowed, **images)

    def create_datas(self):
        """Create device IDs for player API."""
        def gen_hex_code(n):
            return ''.join(random.choice('0123456789abcdef') for _ in range(n))

        if not self.settings.usagent_id:
            self.settings.usagent_id = '2e520525f3%s' % gen_hex_code(6)
        if not self.settings.usagentver_id:
            self.settings.usagentver_id = '2e520525f2%s' % gen_hex_code(6)
        if not self.settings.maker_id:
            self.settings.maker_id = gen_hex_code(16)
        if not self.settings.device_id:
            self.settings.device_id = gen_hex_code(16)

    def check_and_login(self):
        """Check and login. Refresh all tokens."""
        # sprawdzenie1
        if not all(self.settings[k] for k in ('device_id', 'maker', 'usagent', 'usagentver')):
            self.create_datas()
        if not self.settings.refresh_token and self.settings.logged:
            self.remove_mylist()
            POST_DATA = 'scope=/pub-api/user/me&client_id=Player_TV_Android_28d3dcc063672068'
            data = self.jpost(self.GETTOKEN, data=POST_DATA, headers=self.HEADERS3)
            kod = data.get('code')
            dg = dialog_progress()
            dg.create('Uwaga', 'Przepisz kod: [B]%s[/B]\n Na stronie https://player.pl/zaloguj-tv' % kod)

            time_to_wait = 340
            secs = 0
            increment = 100 // time_to_wait
            cancelled = False
            while secs <= time_to_wait:
                if (dg.iscanceled()):
                    cancelled = True
                    break
                if secs != 0:
                    xbmc_sleep(3000)
                secs_left = time_to_wait - secs
                if not secs_left:
                    percent = 100
                else:
                    percent = increment * secs
                POST_DATA = 'grant_type=tvn_reverse_onetime_code&code=%s&client_id=Player_TV_Android_28d3dcc063672068' % kod
                data = self.jpost(self.POSTTOKEN, data=POST_DATA, headers=self.HEADERS3)
                token_type = data.get("token_type")
                if token_type == 'bearer':
                    break
                secs += 1

                dg.update(percent)
                secs += 1
            dg.close()

            if not cancelled:
                self.settings.access_token = data.get('access_token')
                self.settings.user_pub = data.get('user_pub')
                self.settings.user_hash = data.get('user_hash')
                self.settings.refresh_token = data.get('refresh_token')

        # sprawdzenie2
        if self.settings.refresh_token:
            PARAMS = {'4K': 'true', 'platform': PF}
            self.HEADERS2['Content-Type'] = 'application/json; charset=UTF-8'
            POST_DATA = {
                "agent": self.settings.usagent,
                "agentVersion": self.settings.usagentver,
                "appVersion": "1.0.38(62)",
                "maker": self.settings.maker,
                "os": "Android",
                "osVersion": "9",
                "token": self.settings.access_token,
                "uid": self.settings.device_id
            }
            data = self.jpost(self.SUBSCRIBER, data=POST_DATA, headers=self.HEADERS2, params=PARAMS)

            self.settings.selected_profile = data.get('profile', {}).get('name')
            self.settings.selected_profile_id = data.get('profile', {}).get('externalUid')
            self.HEADERS2['API-ProfileUid'] = self.settings.selected_profile_id

    def getTranslate(self, id):
        PARAMS = {'4K': 'true', 'platform': PF, 'id': id}
        data = self.jget(self.TRANSLATE, headers=self.HEADERS2, params=PARAMS)
        return data

    def getPlaylist(self, id_):
        self.refreshTokenTVN()
        data = self.getTranslate(str(id_))
        rodzaj = "LIVE" if data.get("type_", "MOVIE") == "LIVE" else "MOVIE"

        HEADERSz = {
            'Authorization': 'Basic',
            'API-Authentication': self.settings.access_token,
            'API-DeviceUid': self.settings.device_id,
            'API-SubscriberHash': self.settings.user_hash,
            'API-SubscriberPub': self.settings.user_pub,
            'API-ProfileUid': self.settings.selected_profile_id,
            'User-Agent': 'okhttp/3.3.1 Android',
            'Host': 'player.pl',
            'X-NewRelic-ID': 'VQEOV1JbABABV1ZaBgMDUFU=',
        }
        data = self.jget(self.api.player_configuration.format(vid=id_), headers=HEADERSz,
                         params=self.params(type=rodzaj))

        try:
            vidsesid = data["videoSession"]["videoSessionId"]
            # prolongvidses = data["prolongVideoSessionUrl"]
        except Exception:
            vidsesid = False

        params = {'type': rodzaj, 'platform': PF}
        url = self.api.vod_playlist.format(vid=id_)
        data = self.jget(url, headers=HEADERSz, params=params)
        errcode = data.get('code')
        if errcode:
            xbmcgui.Dialog().ok(u'[COLOR red]Bład[/COLOR]', u'Nie można odtworzyć: %s' % errcode)

        if not data:
            params = {'type': rodzaj, 'platform': UA, 'videoSessionId': vidsesid}
            data = self.jget(url, headers=HEADERSz, params=params)

        xbmc.log('PLAYER.PL: getPlaylist(%r): data: %r' % (id_, data), xbmc.LOGWARNING)
        vid = data['movie']
        outsub = []
        try:
            subs = vid['video']['subtitles']
            for lan, sub in subs.items():
                lang = sub['label']

                srcsub = sub['src']
                outsub.append({'lang': lang, 'url': srcsub})
        except Exception:
            pass

        protect = vid['video']['protections']
        if 'widevine' in protect:
            src = vid['video']['sources']['dash']['url']
            tshiftl = vid.get('video', {}).get('time_shift', {}).get('total_length', 0)
            if tshiftl > 0:
                src += '&dvr=' + str(tshiftl * 1000 + 1000)
            widev = protect['widevine']['src']
            if vidsesid:
                widev += '&videoSessionId=%s' % vidsesid
        else:
            src = vid['video']['sources']['hls']['url']
            widev = None
        return src, widev, outsub

    # @entry('/play/<id:int>')
    def play(self, id):
        def download_subtitles():
            if subt:
                r = requests.get(subt)
                with open(SUBTITLEFILE, 'wb') as f:
                    f.write(r.content)
                play_item.setSubtitles([SUBTITLEFILE])

        stream_url, license_url, subtitles = self.getPlaylist(str(id))
        subt = ''
        if subtitles and self.settings.enable_subs:
            t = [x.get('lang') for x in subtitles]
            u = [x.get('url') for x in subtitles]
            al = "subtitles"
            if len(subtitles) > 1:
                if self.settings.subs_default and self.settings.subs_default in t:
                    subt = next((x for x in subtitles if x.get('lang') == self.settings.subs_default), None).get('url')
                else:
                    select = xbmcgui.Dialog().select(al, t)
                    if select > -1:
                        subt = u[select]
                        addon.setSetting(id='subtitles_lang_default', value=str(t[select]))
                    else:
                        subt = ''
            else:
                subt = u[0]

        if license_url:
            # DRM
            PROTOCOL = 'mpd'
            DRM = 'com.widevine.alpha'

            str_url = stream_url

            HEADERSz = {
                'User-Agent': UA,
            }

            is_helper = inputstreamhelper.Helper(PROTOCOL, drm=DRM)
            if not is_helper.check_inputstream():
                raise ValueError('To i tak się by wcześniej wywaliło !!!')
            play_item = xbmcgui.ListItem(path=str_url)
            play_item.setContentLookup(False)
            download_subtitles()

            if sys.version_info >= (3, 0):
                play_item.setProperty('inputstream', is_helper.inputstream_addon)
            else:
                play_item.setProperty('inputstreamaddon', is_helper.inputstream_addon)
            play_item.setMimeType('application/xml+dash')
            play_item.setContentLookup(False)
            play_item.setProperty('inputstream.adaptive.manifest_type', PROTOCOL)
            play_item.setProperty('inputstream.adaptive.license_type', DRM)
            if 'dvr' in str_url:
                play_item.setProperty('inputstream.adaptive.manifest_update_parameter', 'full')
            play_item.setProperty('inputstream.adaptive.license_key', license_url+'|Content-Type=|R{SSM}|')
            play_item.setProperty('inputstream.adaptive.license_flags', "persistent_storage")
            play_item.setProperty('inputstream.adaptive.stream_headers', urlencode(HEADERSz))
        else:
            # no DRM
            play_item = xbmcgui.ListItem(path=stream_url)
            download_subtitles()
        xbmcplugin.setResolvedUrl(addon_handle, True, listitem=play_item)

    def vod_list(self, slug=None, gid=None, maxResults=True, plOnly=False, sort=None, order=None,
                 params=None, url=None):
        """
        List of VoD and VoD groups (like series).

        Parameters
        ----------
        slug : str
            Category slug.
        gid : int
            Genre ID. If None, get all genres.
        maxResults : int | bool
            Item limits. If True, standard limit is used.
        plOnly : bool
            Returns only Polish videos if True.
        sort : str
            Sort by given name, like "createdAt".
        order : str
            Order by given name, like "desc".
        params : dict[str, str]
            Extra params to network request.
        url : str
            Custom URL.

        Returns
        -------
        List if VOD items ot None.
        """
        flog('PLAYER.PL: slug {slug}, gid {gid} started')
        allparams = self.params(maxResults=maxResults)
        if slug is not None:
            allparams['category[]'] = slug
        if sort is not None:
            allparams['sort'] = sort
        if order is not None:
            allparams['order'] = order
        if gid:
            allparams['genreId[]'] = gid
        if plOnly:
            allparams['vodFilter[]'] = 'POLISH'
        if params:
            allparams.update(params)
        if url is None:
            url = self.api.vod_list
        data = self.jget(url, headers=self.HEADERS2, params=allparams)
        flog.info('PLAYER.PL: slug {slug}, gid {gid} done, data: {str(data)[:200]})')
        # --- XXX --- XXX ---
        import json
        with open('/tmp/vod.json', 'w') as f:
            json.dump(data, f)
        # --- XXX ---
        if isinstance(data, Mapping):
            if isinstance(data.get('items'), list):
                data = data['items']
            elif 'id' in data and 'type' in data:
                data = [data]
            else:
                data = []
        # remove duplicates
        if self.settings.remove_duplicates:
            exist = set()  # warning, there is side effect of use `exist.add() or item`
            data = [exist.add(item['id']) or item for item in data if 'id' in item and item['id'] not in exist]
        return data

    def async_slug_data(self, idslug, maxResults=True, plOnly=False):
        thread = ThreadCall(self.slug_data, idslug, maxResults=maxResults, plOnly=plOnly)
        thread.start()
        return thread

    def get_mylist(self):
        xbmc.log('PLAYER.PL: mylist started', xbmc.LOGWARNING)
        data = self.jget('https://player.pl/playerapi/subscriber/product/available/list?4K=true&platform=ANDROID_TV',
                         headers=self.HEADERS2, params={})
        xbmc.log('PLAYER.PL: mylist done', xbmc.LOGWARNING)
        return set(data)

    @property
    def mylist_cache_path(self):
        return os.path.join(CACHEPATH, 'mylist.json')

    def save_mylist(self, mylist=None):
        path = self.mylist_cache_path
        if mylist is None:
            mylist = self.get_mylist()
        try:
            os.makedirs(CACHEPATH)
        except OSError:
            pass  # exists
        save_ints(path, mylist)

    def load_mylist(self, auto_cache=True):
        path = self.mylist_cache_path
        try:
            if time.time() - os.stat(path).st_mtime < self.MYLIST_CACHE_TIMEOUT:
                return set(load_ints(path))
        except OSError:
            pass
        except Exception as exc:
            xbmc.log('PLAYER.PL: Can not load mylist from %r: %r' % (path, exc), xbmc.LOGWARNING)
            self.remove_mylist()
        mylist = self.get_mylist()
        if auto_cache:
            try:
                self.save_mylist(mylist)
            except OSError:
                xbmc.log('PLAYER.PL: Can not save mylist to %r' % path, xbmc.LOGWARNING)
        return mylist

    def remove_mylist(self):
        path = self.mylist_cache_path
        if os.path.exists(path):
            try:
                os.unlink(path)
            except Exception as exc:
                xbmc.log('PLAYER.PL: Can not remove mylist cache %r: %r' % (path, exc),
                         xbmc.LOGWARNING)

    @property
    def mylist(self):
        if self._mylist is None:
            self._mylist = self.load_mylist()
        return self._mylist

    @mylist.deleter
    def mylist(self):
        self.remove_mylist()

    def is_allowed(self, vod):
        """Check if item (video, folder) is available in current pay plan."""
        return (
            # not have to pay and not on ncPlus, it's means free
            not (vod.get('payable') or vod.get('ncPlus'))
            # or it's on myslit, it's means it is in pay plan
            or vod.get('id') in self.mylist)

    def add_media_item(self, mud, vid, meta=None, prefix=None, suffix=None, folder=False, isPlayable=None,
                       vod=None, linkdata=None, label2=None, info=None):
        """
        Add default media item to xbmc.list.
        if `isPlayable` is None (default) it's forced to `not folder`,
        because folder is not playable.
        """
        if vid in self._precessed_vid_list:
            xbmc.log(u'PLAYER.PL: item %s (%r) already processed' % (vid, meta.tytul), xbmc.LOGWARNING)
            if self.settings.remove_duplicates:
                return
        if meta is None and vod is not None:
            meta = self.get_meta_data(vod)
        if meta is None:
            meta = MetaDane('', '', '', '', '')  # tytul opis foto sezon epizod
        allowed = (meta and meta.allowed is True) or vid in self.mylist
        if allowed or not self.settings.available_only:
            no_playable = not (mud or '').strip() or meta.sezon
            if no_playable:
                isPlayable = False
                folder = True
            elif isPlayable is None:
                isPlayable = not folder
            if suffix is None:
                suffix = u''
                if no_playable and not allowed:
                    # auto suffix for non-playable video
                    suffix += u' - [COLOR khaki]([I]brak w pakiecie[/I])[/COLOR]'
                sched = vod and vod.get('displaySchedules')
                if sched and sched[0].get('type') == 'SOON':
                    suffix += u' [COLOR gray] [LIGHT] (od %s)[/LIGHT][/COLOR]' % sched[0]['till'][:-3]
            suffix = suffix or ''
            title = PLchar(prefix or '', meta.tytul, suffix, sep='')
            descr = PLchar(meta.opis or meta.tytul, suffix, sep='\n')
            info = {
                'title': title,
                'plot': descr,
                'plotoutline': descr,
                'tagline': descr,
                # 'genre': 'Nawalanka',  # this is shown in Arctic: Zephyr 2 - Resurrection Mod
            }
            if info:
                info.update(info)
            add_item(str(vid), title, meta.foto or ADDON_ICON, mud,
                     folder=folder, isPlayable=isPlayable, infoLabels=info, art=meta.art,
                     linkdata=linkdata, label2=label2)
            self._precessed_vid_list.add(vid)

    def listFavorites(self):
        self.refreshTokenTVN()

        data = getRequests('https://player.pl/playerapi/subscriber/bookmark',
                           headers=self.HEADERS2, params=self.params(type='FAVOURITE'))
        try:
            self.process_vod_list(data['items'], subitem='item')
            setView('tvshows')
            # xbmcplugin.setContent(addon_handle, 'tvshows')
            xbmcplugin.addSortMethod(addon_handle, sortMethod=xbmcplugin.SORT_METHOD_TITLE, label2Mask="%R, %Y, %P")
            xbmcplugin.endOfDirectory(addon_handle)
        except:
            raise  # skip fallback
            # Falback: Kodi Favorites
            xbmc.executebuiltin("ActivateWindow(10134)")

    def listSearch(self, query):
        self.refreshTokenTVN()
        PARAMS = self.params(keyword=query)

        urlk = 'https://player.pl/playerapi/product/live/search'
        lives = getRequests(urlk, headers=self.HEADERS2, params=PARAMS)
        xbmc.log('PLAYER.PL: listSearch(%r): params=%r, lives=%r' % (query, PARAMS, lives), xbmc.LOGWARNING)
        lives = lives['items']
        # -- commented out, it does do nothing   (rysson)
        # if len(lives)>0:
        #     for live in lives:
        #         ac=''
        urlk = 'https://player.pl/playerapi/product/vod/search'
        data = getRequests(urlk, headers=self.HEADERS2, params=PARAMS)
        self.process_vod_list(data['items'])
        # setView('tvshows')
        xbmcplugin.setContent(addon_handle, 'videos')
        xbmcplugin.addSortMethod(addon_handle, sortMethod=xbmcplugin.SORT_METHOD_TITLE, label2Mask = "%R, %Y, %P")
        xbmcplugin.endOfDirectory(addon_handle)

    def category_tree(self):
        # TODO: add cache
        self.refreshTokenTVN()
        return self.jget(url=self.KATEGORIE, headers=self.HEADERS2, params=self.params())

    @contextmanager
    def counter_directory(self, data, loader, *args, **kwargs):
        """Start Kodi Addon Directory with sub-items counter."""
        sumarize_item = kwargs.pop('sumarize_item', False)  # Py2 doesn't allow: func(*args, key=None, **kwargs)
        with self.directory(*args, **kwargs) as kd:
            kd.sumarize_item = {'id': None, 'name': self.all_items_title, '_properies_': {'SpecialSort': 'top'}}
            # if all_items and len(data) > 1:
            #     data = list(data)
            #     data.insert(0, kd.sumarize_item)
            kd.counter = CountSubfolders(self, data, loader, {}, sumarize_item=sumarize_item)
            # if all_items and len(data) > 1:
            #     kd.add(kd.parse(data[0]))
            yield kd

    def parse_list_item(self, kd, data, parent=None, endpoint=None, series=None, fallback_items=None):
        """
        Get kodipl.addon.ListItem from JSON vod/folder item.

        Parameters
        ----------
        kd : kodipl.addon.AddonDirectory
            Kodi-pl directory (inside "with" statement).
        data : dict[str, Any]
            JSON VoD / Folder item form Player API

        Returns
        -------
        kodipl.addon.ListItem
            Created list item, can be added by kd.add().
        None
            Skip this item (not allowed to process).
        """
        def get(key, default=None):
            try:
                return data[key]
            except KeyError:
                pass
            for d in fallback_items:
                try:
                    return d[key]
                except KeyError:
                    pass
            return default

        # flog('ITEM: {data!r}')  # XXX DEBUG
        if fallback_items is None:
            fallback_items = []
        elif not isinstance(fallback_items, Sequence):
            fallback_items = [fallback_items]
        else:
            fallback_items = list(fallback_items)

        iid = data.get('id')
        # slug = data.get('slug')
        itype = data.get('type_', data.get('type'))
        play = call(self.play, id=iid)
        if series is None:
            series = {}
        if not series and fallback_items and fallback_items[0].get('type_', fallback_items[0].get('type')) == 'SERIAL':
            series = fallback_items[0]  # XXX  koszmar !!!
        elif series:
            fallback_items.append(series)
        endpoints = {
            'LIVE': call(self.live),
            'SECTION': call(self.section, id=iid),
            'SERIAL': call(self.series, id=iid),
            'SEASON': call(self.season, id=series.get('id'), sid=iid),
            'EPISODE': play,
            'VOD': play,
            # 'category:VOD': call(self.genres),
            # 'category:': call(self.category_genre, slug=slug, id=iid),
        }
        if 'externalId' in data:  # category tree
            itype = 'NONE'
        if endpoint is None:
            endpoint = endpoints.get('%s:%s' % (parent or '', itype or ''), endpoints.get(itype or ''))
        # if endpoint is None:
        #     log.warning('Unsupported item type %r' % itype)
        #     return None

        # --- Process access rights
        allowed = iid is None or self.is_allowed(data)
        if self.settings.available_only and not allowed:
            # skip unavailable VoD if available_only is selected
            return
        folder = endpoint != play
        playable = endpoint == play

        # --- Process title and description
        if not data.get('active', True):
            return None
        title = data.get('title', data.get('name'))
        if data.get('uhd'):
            title = '%s [4K]' % (title or '')
        descr = data.get("description")
        if not descr:
            descr = data.get("lead")
        if not descr:
            descr = get('description')
            if not descr:
                descr = get('lead')
        if descr:
            descr = remove_html_tags(descr).strip()

        # --- Process info
        info = {}
        for attr, convert in {
                'year': None,
                'rating': None,
                'duration': lambda v: 60 * v
        }.items():
            if attr in data:
                info[attr] = data[attr] if convert is None else convert(data[attr])

        # --- Process images
        art = {}
        # See: https://kodi.wiki/view/Artwork_types
        # New art images must be added to MetaDane
        for prop, (iname, uname) in {'landscape': ('smart_tv', 'mainUrl'),
                                     'fanart': ('smart_tv', 'mainUrl'),
                                     'thumb': ('smart_tv', 'miniUrl'),
                                     'poster': ('vertical', 'mainUrl')}.items():
            try:
                art[prop] = data['images'][iname][0][uname]
            except (KeyError, IndexError) as exc:
                log.debug('PLAYER.PL: no image %s.%s %r in %r' % (iname, uname, exc, data.get('images')))
                for d in fallback_items:
                    try:
                        art[prop] = d['images'][iname][0][uname]
                        break
                    except (KeyError, IndexError):
                        pass
        if self.force_media_fanart and art.get('fanart'):
            iurl, sep, iparams = art['fanart'].partition('?')
            if sep:
                iparams = dict(parse_qsl(iparams))
                if iparams.get('dstw', '').isdigit() and iparams.get('dstw', '').isdigit():
                    w, h = int(iparams['dstw']), int(iparams['dsth'])
                    if w != self.force_media_fanart_width:
                        iparams['dstw'] = self.force_media_fanart_width
                        iparams['dsth'] = h * self.force_media_fanart_width // (w or 1)
                    iparams['quality'] = self.force_media_fanart_quality
                art['fanart'] = '%s?%s' % (iurl, urlencode(iparams))

        # --- Process series data
        if itype == 'SEASON':
            fmt = ''
            info['season'] = int(data['number'])
            if series.get('title'):
                fmt += '{series[title]} – '
            fmt += 'Sezon {number}'
            if data.get('display') and str(data['display']) != str(data['number']):
                fmt += ' ({display})'
            if data.get('title'):
                fmt += ': {title}'
            title = fmt.format(series=series, info=info, **data)
        elif itype == 'EPISODE':
            season = data.get('season', {})
            series = season.get('serial', series)
            info['episode'] = int(data['episode'])
            if season.get('number'):
                info['season'] = int(season['number'])
            fmt = '[{series[title]} – ][S{info[season]:02d}][E{info[episode]:02d}][: {title}]'
            title = sectfmt(fmt, series=series, info=info, **data)

            ### season = data.get('season', {})
            ### series = season.get('serial', series)
            ### info['episode'] = int(data['episode'])
            ### if series.get('title'):
            ###     fmt += '{series[title]} – '
            ### if season.get('number'):
            ###     info['season'] = int(season['number'])
            ###     log.error(f'EPISODE: |{info["season"]!r}| info:{info} season:{season!r}')  # XXX XXX
            ###     fmt += 'S{info[season]:02d}'
            ### fmt += 'E{info[episode]:02d}'
            ### if data.get('title'):
            ###     fmt += ': {title}'
            ### title = fmt.format(series=series, info=info, **data)
        # sezon = bool(data.get('showSeasonNumber')) or data.get('type') == 'SERIAL'
        # epizod = bool(data.get("showEpisodeNumber"))

        # --- Process extra format (access rights, soon)
        pure_title = title
        # count subitems
        if self.settings.available_only and folder and hasattr(kd, 'counter'):
            if self.settings.skip_empty_folders and not kd.counter.get(iid):
                return None
            title = kd.counter.title(data, title)
        # mark if not avaliable
        if not allowed:
            title += ' [COLOR :missing]([I]brak w pakiecie[/I] )[/COLOR] ⚠'
            sched = data.get('displaySchedules')
            if sched and sched[0].get('type') == 'SOON':
                title += ' [COLOR :gray] [LIGHT] (od %s)[/LIGHT][/COLOR]' % sched[0]['till'][:-3]

        # --- Process access rights
        kitem = kd.new(title, endpoint, descr=descr, art=art, info=info, folder=folder, playable=playable,
                       properties=data.get('_properies_'))
        kitem.allowed = allowed
        kitem.pure_title = pure_title
        return kitem

    def add_list_item(self, kd, data, *args, **kwargs):
        """Parse and add item to addon directory list."""
        kitem = self.parse_list_item(kd, data, *args, **kwargs)
        kd.add(kitem)
        return kitem

    def process_vod_list(self, vod_list, subitem=None, view=None, sort=None, isort=None, **kwargs):
        """
        Process list of VOD items.
        Check if playable or serial. Add items to Kodi list.
        """
        self.refreshTokenTVN()
        with self.directory(view=view, sort=sort, isort=isort) as kd:
            for vod in vod_list:
                if subitem:
                    vod = vod[subitem]
                self.add_list_item(kd, vod, **kwargs)

    def skip_soon_vod_iter(self, lst):
        return (vod for vod in lst if (vod.get('displaySchedules') or [{}])[0].get('type') != 'SOON')

    @entry(title='[B][COLOR :2]Zaloguj[/COLOR][/B]')
    def login(self):
        self.settings.logged = True
        self.refresh()

    @entry(title='[B][COLOR :2]Wyloguj[/COLOR][/B]')
    def logout(self):
        if xbmcgui.Dialog().yesno("[COLOR :warn]Uwaga[/COLOR]",
                                  ('Wylogowanie spowoduje konieczność ponownego wpisania kodu na stronie.[CR]'
                                   'Jesteś pewien?'),
                                  yeslabel='TAK', nolabel='NIE'):
            self.settings.logged = False
            del self.settings.refresh_token
            self.refresh()

    def home(self):
        """Get ROOT folder (main menu)."""
        self.check_and_login()
        with self.directory(view='addons') as kd:
            if not self.settings.logged:
                kd.item(self.login)
            kd.menu('[B][COLOR :1]Ulubione[/COLOR][/B]', self.listFavorites)
            for item in self.category_tree():
                if item.get('genres') and item['slug'] not in slug_blacklist:
                    slug, cid = item['slug'], item['id']
                    lit = self.parse_list_item(kd, item)
                    if item.get('layout') == 'SCHEDULE':  # special case, ex. Eurosport
                        kd.add(lit, call(self.schedule, cid=cid, slug=slug))
                    elif slug in self.categories_without_genres:
                        kd.add(lit, call(self.category_genre, slug=slug))
                    else:
                        kd.add(lit, call(self.category, cid=cid, slug=slug))
            kd.menu('Kolekcje', self.collections)
            kd.menu('[B][COLOR :1]Szukaj[/COLOR][/B]', "search")
            kd.item('[B][COLOR :2]Opcje[/COLOR][/B]', self.settings)
            if playerpl.settings.logged:
                kd.item(self.logout)
            kd.item('[B][COLOR :warn]Debug skórki[/COLOR][/B]', call(self.builtin, command='Skin.ToggleDebug()'))  # XXX XXX XXX

    def category(self, cid, slug):
        """Get category content -> list of category genres."""
        def loader(item):
            url = self.api.live_list if slug == 'live' else None
            return self.vod_list(slug=slug, gid=item.get('id'), maxResults=True, url=url)

        cid = int(cid)
        category = next(cat for cat in self.category_tree() if cat['id'] == cid)
        genres = category['genres']
        with self.counter_directory(genres, loader, sumarize_item=True, view='tvshows') as kd:
            for item in genres:
                self.add_list_item(kd, item, endpoint=call(self.category_genre, slug=slug, gid=item['id']))
            if kd.item_count() > 1:
                self.add_list_item(kd, kd.sumarize_item, endpoint=call(self.category_genre, slug=slug))

    def category_genre(self, slug, gid=None):
        """Get cetegory genre list -> list of VoD and VoD's group (like series)."""
        def loader(item):
            return self.vod_list(slug=slug, gid=item.get('id'), maxResults=True)

        url = self.api.live_list if slug == 'live' else None
        data = self.vod_list(slug, gid=gid, maxResults=True, url=url)
        with self.counter_directory(data, loader, view='tvshows', sort='|%y, %d;auto', isort='title,-year') as kd:
            for item in data:
                self.add_list_item(kd, item)

    def live(self):
        pass

    def season(self, id, sid):
        """Season folder, create episode list."""
        data = self.vod_list(url=self.api.episode_list.format(id=id, sid=sid))
        self.process_vod_list(data, view='episodes')

    def series(self, id):
        """Series folder, create seasons list."""
        self.refreshTokenTVN()  # to avoid raise in threads, TODO: mutex on token
        with ThreadPool() as th:
            th.start(self.vod_list, url=self.api.series.format(id=id))
            th.start(self.vod_list, url=self.api.season_list.format(id=id))
        series, data = th.result
        self.process_vod_list(data, series=series[0])

    def section(self, id):
        """Section folder, create section content list."""
        data = self.vod_list(url=self.api.section.format(id=id))
        self.process_vod_list(data)

    def genres(self, gid=None):
        pass

    def collections(self):
        """Collections folder, create collections content (sections) list."""
        data = self.vod_list(url=self.api.section_list, order='asc')
        self.process_vod_list(data, sort='title')

    def schedule(self, cid, slug):
        top = {'SpecialSort': 'top'}
        with self.directory() as kd:
            kd.folder('Transmisje sportowe wg daty i godziny (ostatnie dni)',
                      call(self.schedule_schedule, slug=slug),
                      properties=top)
            kd.folder('Transmisje sportowe wg dyscypliny',
                      call(self.schedule_genre, cid=cid, slug=slug),
                      properties=top)
            # kd.folder('Archiwum wszystkich transmisji',
            #           call(self.listCategContent, exlink=':%s' % slug),
            #           properties=top)
            data = self.jget(self.api.section_list_slug.format(slug=slug), headers=self.HEADERS2, params=self.params())
            for item in self.skip_soon_vod_iter(data):
                self.add_list_item(kd, item)
        return
        #         gid = item['id']
        #         slug = item['slug']
        #         try:
        #             foto = item['images']['smart_tv'][0]['mainUrl']
        #             foto = 'https:' + foto if foto.startswith('//') else foto
        #         except Exception:
        #             foto = ADDON_ICON
        #         title = PLchar(item["title"].capitalize())
        #         kd.folder(title, call(self.listCategContent, exlink='%s:%s' % (gid, slug)), image=foto)
        #     setView('movies')
        #     xbmcplugin.addSortMethod(addon_handle, sortMethod=xbmcplugin.SORT_METHOD_TITLE,
        #                              label2Mask="%R, %Y, %P")

    def schedule_schedule(self, slug, gid=None):
        # Wyswietla menu z datami z ostatnich 7 dni (gdy wybrano transmisje wg daty i godziny)
        for i in range(self.settings.days_ago + 1):
            today = datetime.combine(date.today(), datetime.min.time())
            day = today - timedelta(days=i)
            beginTimestamp = int(1000 * time.mktime(day.timetuple()))
            endTimestamp = beginTimestamp + 1000 * 24 * 3600
            # "%A" uses current locale, it's not a perfect options in all cases
            name = '%s, %s' % (day.strftime('%Y-%m-%d'), self.week_days[day.weekday()])
            add_item('%s:%s:time:%s:%s' % (gid or '', slug, beginTimestamp, endTimestamp), name,
                     ADDON_ICON, slug, folder=True, fanart=FANART)
        setView('movies')
        xbmcplugin.addSortMethod(addon_handle, sortMethod=xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, cacheToDisc=False)

    def schedule_time(self, exlink):
        def hhmm(s):
            return s.partition(' ')[2].rpartition(':')[0]

        ex = ExLink.new(exlink)
        data = self.slug_data('%s:%s' % (ex.gid, ex.slug), maxResults=0, sort='airingSince', params={
            'airingSince': str(ex.beginTimestamp),
            'airingTill': str(ex.endTimestamp)
        })
        myList = self.mylist
        xbmc.log('PLAYER.PL: ++++++ %r' % data, xbmc.LOGWARNING)
        for item in data['items']:
            if ( ( 'displaySchedules' in item ) and ( len(item['displaySchedules']) > 0 ) and ( item['displaySchedules'][0]['type'] != 'SOON' ) ):
                dod=''
                fold = False
                playk =True
                mud = 'playvid'
                if item["payable"]:
                    if item['id'] not in myList:
                        dod=' - [I][COLOR khaki](brak w pakiecie)[/COLOR][/I]'
                        playk =False
                        mud = '   '
                time_str = '[%s-%s]%s' % (hhmm(item['airingSince']), hhmm(item['airingTill']), self.hard_separator)
                name = PLchar(time_str, item['title'], dod, sep='')
                add_item(str(item['id']), name, ADDON_ICON, mud, folder=fold,isPlayable=playk,fanart=FANART)
        setView('tvshows')
        xbmcplugin.addSortMethod(addon_handle, sortMethod=xbmcplugin.SORT_METHOD_TITLE,
                                 label2Mask="%R, %Y, %P")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, cacheToDisc=False)

    def schedule_genre(self, exlink):
        EUROSPORT_CID = 24  # TODO: remove it !!!
        ex = ExLink.new(exlink)
        data = getRequests3(self.GATUNKI_KATEGORII.format(cid=EUROSPORT_CID), headers=self.HEADERS2, params=self.params())
        for genre in data:
            gid, name = genre['id'], genre['name']
            add_item('%s:%s:list' % (gid, ex.slug), PLchar(name.capitalize()), ADDON_ICON, ex.slug, folder=True,
                     fanart=FANART)
        setView('tvshows')
        xbmcplugin.addSortMethod(addon_handle, sortMethod=xbmcplugin.SORT_METHOD_TITLE,
                                 label2Mask="%R, %Y, %P")
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, cacheToDisc=False)

    def schedule_list(self, exlink):
        ex = ExLink.new(exlink)
        data = self.slug_data('%s:%s' % (ex.gid, ex.slug), maxResults=0, sort='airingSince')
        for vod in data['items']:
            times = '[%s]%s' % (vod['airingSince'].rpartition(':')[0], self.hard_separator)
            self.add_media_item('playvid', vod['id'], vod=vod, prefix=times,
                                info={'duration': vod['duration']})
        setView('tvshows')
        xbmcplugin.addSortMethod(addon_handle, sortMethod=xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, cacheToDisc=False)

    # --- XXX --- XXX ---

    def root(self):
        # with self.directory(view='tvshows', sort='unsorted|%J/%D/%Y; title|%J, %D; year; duration') as kd:
        with self.directory(view='tvshows', sort='auto|[[COLOR red]%Y[/COLOR]]/%D') as kd:
            kd.item('Poz 1', info={
                'title': 'Tytuł 2',
                'year': 2003,
                'duration': 64,
                'date': '15.05.2010',
            })
            kd.item('Poz 2', info={
                'title': 'Tytuł 3',
                'year': 2004,
                'duration': 65,
                'date': '11.05.2010',
            }, label2='ppp2')
            kd.item('Poz 3', info={
                'title': 'Tytuł 4',
                'year': 2005,
                'duration': 61,
                'date': '12.05.2010',
                'rating': 18,
            }, label2='ppp3 %L')
            kd.item('Poz 4', info={
                'title': 'Tytuł 5',
                'year': 2001,
                'duration': 62,
                'date': '13.05.2010',
                'aired': '13.05.2020',
                'rating': 12,
            })
            kd.item('Poz 5', info={
                'title': 'Tytuł 1',
                'year': 2002,
                'duration': 63,
                'aired': '2020-05-14',
                'date': '14.05.2010',
                'code': '14.05.2010',
            })
            # kd.add_sort('unsorted', label2Mask=' ')
            # kd.add_sort('unsorted', label2Mask='%P')
            # kd.add_sort('unsorted', label2Mask='%Y/%D')
            # kd.add_sort('title', labelMask='%J: %D: %Y', label2Mask='%J, %D, %Y')
            # kd.add_sort('year')
            # kd.add_sort('date')


import asyncio

async def aa(a):
    log.error(f'aaaaa = {a!r}')

asyncio.run(aa('42'))


if __name__ == '__main__':
    from kodipl.utils import parse_url  # For DEBUG only

    mode = params.get('mode', None)
    name = params.get('name')
    url = parse_url(sys.argv[0] + sys.argv[2])
    xbmc.log('PLAYER.PL: \033[93mENTER\033[0m: path=%r, args=%r, argv=%r' % (url.path, url.args, sys.argv),
             xbmc.LOGWARNING)

    if True:
        # XXX ALWAYS !!!
        playerpl = PlayerPL()
        playerpl.dispatcher()

    elif mode == "content":
        PLAYERPL().content()

    elif mode == 'search.it':
        query = exlink
        if query:
            PLAYERPL().listSearch(query)

    elif mode == 'search':
        add_item('', '[COLOR khaki][B]Nowe szukanie[/B][/COLOR]', image=None, mode='search.new',
                 folder=True)
        for entry in historyLoad():
            if entry:
                contextmenu = [
                    (u'Usuń', 'Container.Update(%s)'
                     % build_url({'mode': 'search.remove', 'url': entry})),
                    (u'Usuń całą historię', 'Container.Update(%s)'
                     % build_url({'mode': 'search.remove_all'})),
                ]
                add_item(entry, entry, image=None, mode='search.it', contextmenu=contextmenu,
                         folder=True)
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, cacheToDisc=False)

    elif mode == 'search.new':
        query = xbmcgui.Dialog().input(u'Szukaj, podaj tytuł filmu', type=xbmcgui.INPUT_ALPHANUM)
        if query:
            historyAdd(query)
            try:
                PLAYERPL().listSearch(query)
            except Exception:
                addon_data.save(indent=2)  # save new search even if exception raised
                raise
    elif mode == 'search.remove':
        historyDel(exlink)
        xbmc.executebuiltin('Container.Refresh(%s)' % build_url({'mode': 'search'}))
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, cacheToDisc=False)

    elif mode == 'search.remove_all':
        historyClear()
        xbmc.executebuiltin('Container.Refresh(%s)' % build_url({'mode': 'search'}))
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True, cacheToDisc=False)

    elif mode == 'favors':
        PLAYERPL().listFavorites()

    elif mode=='playvid':
        PLAYERPL().playvid(exlink)

addon_data.save(indent=2)


# "type":
# - BANNER
# - DEFAULT
# - EPISODE
# - LAST_BELL
# - LIVE
# - LIVE_EPG_PROGRAMME
# - NORMAL
# - SEASON
# - SECTION
# - SERIAL
# - SOON
# - VOD
#
# "type_":
# - BANNER
# - LIVE
# - SEASON
# - SECTION
# - SERIAL
# - VOD
#
# "layout":
# - ALPHABETICAL
# - BANNER
# - CALENDAR
# - COLLECTION
# - LOGO
# - ONE_LINE
# - POSTER
# - SCHEDULE
# - TWO_LINES
