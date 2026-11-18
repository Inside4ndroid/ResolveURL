"""
    Plugin for ResolveURL
    Copyright (C) 2026 gujal

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import json
from six.moves import urllib_error
from resolveurl.lib import helpers
from resolveurl import common
from resolveurl.resolver import ResolveUrl, ResolverError


class GoFileResolver(ResolveUrl):
    name = 'GoFile'
    domains = ['gofile.io']
    pattern = r'(?://|\.)(gofile\.io)/(?:\?c=|d/)([0-9a-zA-Z]+)'
    api_url = 'https://api.gofile.io'
    # Secret baked into https://gofile.io/js/wt.obf.js. Gofile rotates it
    # periodically, so if the API starts returning error-notPremium this is
    # the first thing to check.
    website_secret = '12af056dacea0b'
    language = 'en-US'
    _token = None

    def get_media_url(self, host, media_id):
        headers = {
            'User-Agent': common.RAND_UA,
            'Origin': 'https://gofile.io',
            'Referer': 'https://gofile.io/'
        }
        data = None
        token = self._token
        if token:
            try:
                data = self.__get_contents(media_id, token, headers)
            except urllib_error.HTTPError as e:
                if e.code not in (401, 403):
                    raise ResolverError(self.__error_message(e))
                self._token = None
            except ValueError:
                raise ResolverError('Unable to parse GoFile response.')

        if data is None or data.get('status') in ('error-token', 'error-accountId'):
            token = self.__create_account(headers)
            try:
                data = self.__get_contents(media_id, token, headers)
            except urllib_error.HTTPError as e:
                raise ResolverError(self.__error_message(e))
            except ValueError:
                raise ResolverError('Unable to parse GoFile response.')

        status = data.get('status')
        if status != 'ok':
            raise ResolverError(self.__status_message(status))

        content = data.get('data') or {}
        if content.get('type') == 'file':
            children = [content]
        else:
            children = list((content.get('children') or {}).values())

        sources = [(child.get('size'), child.get('link')) for child in children
                   if child.get('type') == 'file' and child.get('link')]
        if not sources:
            raise ResolverError('File does not exist.')

        headers = {
            'User-Agent': common.RAND_UA,
            'Referer': 'https://gofile.io/',
            'Cookie': 'accountToken={0}'.format(token)
        }
        return helpers.pick_source(sources, False) + helpers.append_headers(headers)

    def __get_contents(self, media_id, token, headers):
        headers = dict(headers)
        headers.update({
            'Authorization': 'Bearer ' + token,
            'X-Website-Token': self.__generateWT(token),
            'X-BL': self.language
        })
        page = 1
        children = {}
        while True:
            content_url = ('{0}/contents/{1}?page={2}&pageSize=100&sortField=name&sortDirection=1'
                           .format(self.api_url, media_id, page))
            data = json.loads(self.net.http_GET(content_url, headers=headers).content)
            content = data.get('data') or {}
            if data.get('status') != 'ok' or content.get('type') == 'file':
                return data

            children.update(content.get('children') or {})
            if not (data.get('metadata') or {}).get('hasNextPage') or page >= 50:
                break
            page += 1

        data.setdefault('data', {})['children'] = children
        return data

    def __create_account(self, headers):
        headers = dict(headers)
        headers['Content-Type'] = 'application/json'
        try:
            r = self.net.http_POST('{0}/accounts'.format(self.api_url), form_data={},
                                   headers=headers, jdata=True)
            data = json.loads(r.content)
        except urllib_error.HTTPError as e:
            raise ResolverError(self.__error_message(e))
        except ValueError:
            raise ResolverError('Unable to parse account response.')

        token = (data.get('data') or {}).get('token')
        if not token:
            raise ResolverError('Unable to retrieve token!')

        self._token = token
        return token

    def __status_message(self, status):
        if status == 'error-notPremium':
            return ('GoFile: website token rejected, Gofile has probably rotated '
                    'its website secret.')
        if status == 'error-rateLimit':
            return 'GoFile: rate limit reached, try again later.'
        return 'GoFile: API error ({0}).'.format(status or 'unknown')

    def __error_message(self, error):
        try:
            data = json.loads(error.read())
            return self.__status_message(data.get('status'))
        except Exception:
            return 'GoFile: HTTP error {0}.'.format(error.code)

    @staticmethod
    def __generateWT(tok):
        import math
        import time
        import hashlib
        rtime = math.floor(time.time() / 14400)
        wtok = '{0}::{1}::{2}::{3}::{4}'.format(
            common.RAND_UA, GoFileResolver.language, tok, rtime, GoFileResolver.website_secret)
        return hashlib.sha256(wtok.encode('latin-1')).hexdigest()
