import urllib2
import urllib
import time
import base64
from urlparse import urlparse, urlunparse

from urllib2 import HTTPError, URLError
from httplib import BadStatusLine
import socket

from StringIO import StringIO
import gzip

import events

def log_request(f):
    def _wrapper(*args, **kwargs):
        name = kwargs.get('name', args[1]) or args[1]
        try:
            start = time.time()
            retval = f(*args, **kwargs)
            response_time = int((time.time() - start) * 1000)
            events.request_success.fire(name, response_time, retval)
            return retval
        except HTTPError, e:
            response_time = int((time.time() - start) * 1000)
            events.request_failure.fire(name, response_time, e, response=e.locust_http_response)
        except (URLError, BadStatusLine, socket.error), e:
            response_time = int((time.time() - start) * 1000)
            events.request_failure.fire(name, response_time, e, None)
            
    return _wrapper

class HTTPClient(object):
    def __init__(self, base_url):
        self.base_url = base_url

    @log_request
    def get(self, url, name=None):
        return urllib2.urlopen(self.base_url + url).read()

class HttpBasicAuthHandler(urllib2.BaseHandler):
    def __init__(self, username, password):
        self.username = username
        self.password = password

    def http_request(self, request):
        base64string = base64.encodestring('%s:%s' % (self.username, self.password)).replace('\n', '')
        request.add_header("Authorization", "Basic %s" % base64string)
        return request

class HttpResponse(object):
    """
    An instance of HttpResponse is returned by HttpBrowser's get and post functions.
    It contains response data for the request that was made.
    """
    
    url = None
    """URL that was requested"""
    
    code = None
    """HTTP response code"""
    
    data = None
    """Response data"""
    
    def __init__(self, url, name, code, data, info, gzip):
        self.url = url
        self._name = name
        self.code = code
        self.data = data
        self._info = info
        self._gzip = gzip
        self._decoded = False
    
    @property
    def info(self):
        """
        urllib2 info object containing info about the response
        """
        return self._info()
    
    def _get_data(self):
        if self._gzip and not self._decoded and self._info().get("Content-Encoding") == "gzip":
            self._data = gzip.GzipFile(fileobj=StringIO(self._data)).read()
            self._decoded = True
        return self._data
    
    def _set_data(self, data):
        self._data = data
    
    data = property(_get_data, _set_data)

class HttpBrowser(object):
    """
    Class for performing web requests and holding session cookie between requests (in order
    to be able to log in to websites). 
    
    Logs each request so that locust can display statistics.
    """

    def __init__(self, base_url, gzip=False):
        self.base_url = base_url
        self.gzip = gzip
        handlers = [urllib2.HTTPCookieProcessor()]

        # Check for basic authentication
        parsed_url = urlparse(self.base_url)
        if parsed_url.username and parsed_url.password:

            netloc = parsed_url.hostname
            if parsed_url.port:
                netloc += ":%d" % parsed_url.port

            # remove username and password from the base_url
            self.base_url = urlunparse((parsed_url.scheme, netloc, parsed_url.path, parsed_url.params, parsed_url.query, parsed_url.fragment))
        
            auth_handler = HttpBasicAuthHandler(parsed_url.username, parsed_url.password)
            handlers.append(auth_handler)

        self.opener = urllib2.build_opener(*handlers)
        urllib2.install_opener(self.opener)
    
    def get(self, path, headers={}, name=None):
        """
        Make an HTTP GET request.
        
        Arguments:
        
        * *path* is the relative path to request.
        * *headers* is an optional dict with HTTP request headers
        * *name* is an optional argument that can be specified to use as label in the statistics instead of the path
        
        Returns an HttpResponse instance, or None if the request failed.
        """
        return self._request(path, None, headers=headers, name=name)
    
    def post(self, path, data, headers={}, name=None):
        """
        Make an HTTP POST request.
        
        Arguments:
        
        * *path* is the relative path to request.
        * *data* dict with the data that will be sent in the body of the POST request
        * *headers* is an optional dict with HTTP request headers
        * *name* Optional is an argument that can be specified to use as label in the statistics instead of the path
        
        Returns an HttpResponse instance, or None if the request failed.
        
        Example::
        
            client = HttpBrowser("http://example.com")
            response = client.post("/post", {"user":"joe_hill"})
        """
        return self._request(path, data, headers=headers, name=name)
    
    @log_request
    def _request(self, path, data=None, headers={}, name=None):
        if self.gzip:
            headers["Accept-Encoding"] = "gzip"
        
        if data is not None:
            data = urllib.urlencode(data)
        
        url = self.base_url + path
        request = urllib2.Request(url, data, headers)
        try:
            f = self.opener.open(request)
            data = f.read()
            f.close()
        except HTTPError, e:
            data = e.read()
            e.locust_http_response = HttpResponse(url, name, e.code, data, e.info, self.gzip)
            e.close()
            raise e
        
        return HttpResponse(url, name, f.code, data, f.info, self.gzip)
