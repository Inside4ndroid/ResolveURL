"""
    ResolveURL
    Copyright (C) 2023 gujal

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

import re
import json
from resolveurl import common
from resolveurl.resolver import ResolveUrl, ResolverError

# Custom alphabet used by VidNest for encoding
VIDNEST_ALPHABET = "RB0fpH8ZEyVLkv7c2i6MAJ5u3IKFDxlS1NTsnGaqmXYdUrtzjwObCgQP94hoeW+/="

# Backend configurations
BACKENDS = [
    {'name': 'MoviesAPI', 'path': 'moviesapi'},
    {'name': 'HollyMovieHD', 'path': 'hollymoviehd'},
    {'name': 'AllMovies', 'path': 'allmovies'},
    {'name': 'VidLink', 'path': 'vidlink'},
    {'name': 'KlikXXI', 'path': 'klikxxi'},
    {'name': 'Movies4F', 'path': 'movies4f'},
    {'name': 'MovieBox', 'path': 'moviebox'},
    {'name': 'Videasy', 'path': 'videasy'},
    {'name': 'Movies5F', 'path': 'movies5f'},
]


class VidNestResolver(ResolveUrl):
    name = "vidnest"
    domains = ["vidnest.fun", "new.vidnest.fun"]
    pattern = r'(?://|\.)(vidnest\.fun)/(?:embed/|movie/|tv/)?([0-9a-zA-Z]+)'

    def get_media_url(self, host, media_id):
        """
        Main method to get media URL from vidnest
        """
        web_url = self.get_url(host, media_id)
        
        # Common headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Origin': 'https://vidnest.fun',
            'Referer': 'https://vidnest.fun/',
            'Accept': 'application/json, */*',
        }

        try:
            # First try to get the webpage to find available servers
            html = self.net.http_GET(web_url, headers=headers).content
            html = html.decode('utf-8', errors='ignore')
            
            # Check if it's a TV show or movie
            is_tv = '/tv/' in web_url
            
            # Extract TMDB ID
            tmdb_id = self._extract_tmdb_id(html, media_id)
            if not tmdb_id:
                raise ResolverError('Could not extract TMDB ID')

            # Try each backend in sequence
            for backend in BACKENDS:
                try:
                    stream_url = self._try_backend(tmdb_id, backend, is_tv)
                    if stream_url:
                        # Verify the stream is accessible
                        if self._verify_stream(stream_url):
                            # Return the stream URL with any necessary headers
                            return stream_url + '|User-Agent=' + headers['User-Agent'] + '&Referer=' + headers['Referer']
                except Exception as e:
                    common.logger.log('VidNest backend %s failed: %s' % (backend['name'], str(e)), common.LOGWARNING)
                    continue

            raise ResolverError('No working streams found')
            
        except Exception as e:
            common.logger.log('VidNest error: %s' % str(e), common.LOGERROR)
            raise ResolverError('Failed to resolve VidNest URL')

    def _extract_tmdb_id(self, html, media_id):
        """
        Extract TMDB ID from the page or use the provided ID
        """
        # Try to find TMDB ID in the page
        tmdb_match = re.search(r'data-tmdbid=["\']?(\d+)["\']?', html, re.I)
        if tmdb_match:
            return tmdb_match.group(1)
        
        # If media_id looks like a TMDB ID, use it directly
        if media_id.isdigit():
            return media_id
            
        # Try to find it in a data attribute
        data_match = re.search(r'data-id=["\']?(\d+)["\']?', html, re.I)
        if data_match:
            return data_match.group(1)
            
        # Try to find it in a JSON blob
        json_match = re.search(r'{"tmdb":(\d+)}', html, re.I)
        if json_match:
            return json_match.group(1)
            
        raise ResolverError('Could not extract TMDB ID')

    def _try_backend(self, tmdb_id, backend, is_tv=False):
        """
        Try to get stream from a specific backend
        """
        # Build API URL
        if is_tv:
            # For TV shows, we need season/episode - using default 1/1 for now
            api_url = 'https://new.vidnest.fun/%s/tv/%s/1/1' % (backend['path'], tmdb_id)
        else:
            api_url = 'https://new.vidnest.fun/%s/movie/%s' % (backend['path'], tmdb_id)

        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Accept': 'application/json, */*',
            'Origin': 'https://vidnest.fun',
            'Referer': 'https://vidnest.fun/',
        }

        try:
            response = self.net.http_GET(api_url, headers=headers)
            response_data = json.loads(response.content)
            
            # Check if data is encrypted
            if response_data.get('encrypted', False):
                decrypted_data = self._decrypt_vidnest(response_data.get('data', ''))
                if decrypted_data:
                    return self._parse_stream_data(decrypted_data)
            else:
                # Direct data
                return self._parse_stream_data(response_data)
                
        except Exception as e:
            common.logger.log('VidNest backend %s error: %s' % (backend['name'], str(e)), common.LOGWARNING)
            return None
            
        return None

    def _decrypt_vidnest(self, data):
        """
        Decrypt VidNest's custom base64 encoding
        """
        if not data:
            return None

        try:
            # Build lookup table
            lookup = {char: idx for idx, char in enumerate(VIDNEST_ALPHABET)}
            
            result = bytearray()
            i = 0
            while i < len(data):
                chunk = data[i:i+4]
                # Pad chunk if necessary
                while len(chunk) < 4:
                    chunk += '='
                
                vals = []
                for char in chunk:
                    if char in lookup:
                        vals.append(lookup[char])
                    else:
                        vals.append(64)
                
                # Decode 4 chars into 3 bytes
                result.append((vals[0] << 2) | (vals[1] >> 4))
                if vals[2] != 64:
                    result.append(((vals[1] & 15) << 4) | (vals[2] >> 2))
                if vals[3] != 64:
                    result.append(((vals[2] & 3) << 6) | vals[3])
                
                i += 4
            
            # Try to parse as JSON
            try:
                return json.loads(result.decode('utf-8'))
            except:
                # If not valid JSON, try to parse as string
                result_str = result.decode('utf-8', errors='ignore')
                try:
                    return json.loads(result_str)
                except:
                    # Try to extract JSON from the string
                    json_match = re.search(r'\{.*\}', result_str, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group(0))
                    return result_str
                
        except Exception as e:
            common.logger.log('VidNest decryption error: %s' % str(e), common.LOGWARNING)
            return None

    def _parse_stream_data(self, data):
        """
        Parse the decrypted stream data
        """
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except:
                # Try to extract JSON from the string
                json_match = re.search(r'\{.*\}', data, re.DOTALL)
                if json_match:
                    try:
                        data = json.loads(json_match.group(0))
                    except:
                        return None
                else:
                    return None

        if not isinstance(data, dict):
            return None

        # Try sources format (moviesapi, hollymoviehd, vidlink, klikxxi)
        if 'sources' in data and data['sources']:
            # Sort by quality if available
            sources = data['sources']
            if isinstance(sources, list) and sources:
                # Prefer higher quality
                for source in sources:
                    if isinstance(source, dict) and source.get('url'):
                        url = source['url']
                        if url.startswith('//'):
                            url = 'https:' + url
                        return url

        # Try streams format (allmovies)
        if 'streams' in data and data['streams']:
            streams = data['streams']
            if isinstance(streams, list) and streams:
                for stream in streams:
                    if isinstance(stream, dict) and stream.get('url'):
                        url = stream['url']
                        if url.startswith('//'):
                            url = 'https:' + url
                        return url

        # Try downloads format (movies4f)
        if 'data' in data and isinstance(data['data'], dict):
            if 'downloads' in data['data']:
                downloads = data['data']['downloads']
                if isinstance(downloads, list) and downloads:
                    # Pick highest resolution
                    best = None
                    best_res = 0
                    for dl in downloads:
                        if isinstance(dl, dict) and dl.get('url'):
                            res = dl.get('resolution', 0)
                            if res > best_res:
                                best_res = res
                                best = dl
                    if best and best.get('url'):
                        url = best['url']
                        if url.startswith('//'):
                            url = 'https:' + url
                        return url

        # Try direct URL
        if 'url' in data and data['url']:
            url = data['url']
            if url.startswith('//'):
                url = 'https:' + url
            return url

        # Try to find any URL in the data
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and (value.startswith('http') or value.startswith('//')):
                    if '.m3u8' in value or '.mp4' in value or '.mkv' in value:
                        if value.startswith('//'):
                            value = 'https:' + value
                        return value

        return None

    def _verify_stream(self, url):
        """
        Verify that the stream URL is accessible
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://vidnest.fun/',
                'Range': 'bytes=0-1024'
            }
            response = self.net.http_HEAD(url, headers=headers)
            return response.status_code < 400
        except:
            # If we can't verify, assume it's working
            return True

    def get_url(self, host, media_id):
        """
        Get the full URL for the media
        """
        return 'https://%s/movie/%s' % (host, media_id)

    def get_host_and_id(self, url):
        """
        Extract host and media ID from URL
        """
        r = re.search(self.pattern, url, re.I)
        if r:
            return r.groups()
        else:
            return False

    def valid_url(self, url, host):
        """
        Check if the URL is valid for this resolver
        """
        return re.search(self.pattern, url, re.I) is not None