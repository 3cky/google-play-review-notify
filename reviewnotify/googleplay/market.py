# Based on:
# https://github.com/liato/android-market-api-py
# https://github.com/Akdeniz/google-play-crawler

import treq

from twisted.internet import defer
from twisted.web import http

from google.protobuf import descriptor
from google.protobuf.internal.containers import RepeatedCompositeFieldContainer

import reviewnotify.googleplay.market_pb2 as market_proto

class LoginError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class RequestError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class MarketSession(object):
    URL_LOGIN = "https://android.clients.google.com/auth"
    HOST_API_REQUEST = "https://android.clients.google.com/fdfe/"
    URL_REVIEWS = HOST_API_REQUEST + "rev";
    SERVICE = "androidmarket";
    ACCOUNT_TYPE_HOSTED_OR_GOOGLE = "HOSTED_OR_GOOGLE"
    authSubToken = None

    def __init__(self, androidId):
        self.androidId = androidId.encode("ascii")

    def _toDict(self, protoObj):
        iterable = False
        if isinstance(protoObj, RepeatedCompositeFieldContainer):
            iterable = True
        else:
            protoObj = [protoObj]
        retlist = []
        for po in protoObj:
            msg = dict()
            for fielddesc, value in po.ListFields():
                #print value, type(value), getattr(value, '__iter__', False)
                if fielddesc.type == descriptor.FieldDescriptor.TYPE_GROUP or isinstance(value, RepeatedCompositeFieldContainer):
                    msg[fielddesc.name] = self._toDict(value)
                else:
                    msg[fielddesc.name] = value
            retlist.append(msg)
        if not iterable:
            if len(retlist) > 0:
                return retlist[0]
            else:
                return None
        return retlist

    def setAuthSubToken(self, authSubToken):
        self.authSubToken = authSubToken

    @defer.inlineCallbacks
    def login(self, email, password, accountType = ACCOUNT_TYPE_HOSTED_OR_GOOGLE):
        params = {"Email": email, "Passwd": password, "service": self.SERVICE,
                  "accountType": accountType, "has_permission": "1",
                  "source": "android", "androidId": self.androidId,
                  "app": "com.android.vending", "sdk_version": "16" }
        resp = yield treq.post(self.URL_LOGIN, params)
        if resp.code == http.OK:
            data = yield treq.content(resp)
            data = data.split()
            params = {}
            for d in data:
                k, v = d.split("=")
                params[k.strip()] = v.strip()
            if "Auth" in params:
                self.setAuthSubToken(params["Auth"])
            else:
                raise LoginError("Auth token not found.")
        else:
            if resp.code == http.FORBIDDEN:
                data = yield treq.content(resp)
                params = {}
                for d in data.split('\n'):
                    d = d.strip()
                    if d:
                        k, v = d.split("=", 1)
                        params[k.strip()] = v.strip()
                if "error" in params:
                    raise LoginError(params["error"])
                else:
                    raise LoginError("Login failed.")
            else:
                data = yield treq.content(resp)
                raise LoginError("Login failed: error %d <%s>" % (resp.code, data.rstrip(),))

    @defer.inlineCallbacks
    def execute(self, url, params, lang):
        try:
            headers = {"Authorization": "GoogleLogin auth=" + self.authSubToken,
                       "Accept-Language": lang.encode("ascii"),
                       "User-Agent": "Android-Market/2 (sapphire PLAT-RC33); gzip",
                       "X-DFE-Device-Id": self.androidId,
                       "X-DFE-Client-Id": "am-android-google",
                       "X-DFE-Enabled-Experiments": "cl:billing.select_add_instrument_by_default",
                       "X-DFE-SmallestScreenWidthDp": "320", "X-DFE-Filter-Level": "3",
                       "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
            resp = yield treq.get(url, params=params, headers=headers)
            if resp.code == http.OK:
                data = yield treq.content(resp)
                response = market_proto.ResponseWrapper()
                response.ParseFromString(data)
                defer.returnValue(response)
            else:
                raise RequestError("Error %d" % resp.code)
        except Exception, e:
            raise RequestError(e)

    @defer.inlineCallbacks
    def getReviews(self, appid, startIndex = 0, entriesCount = 10, lang = 'en'):
        response = yield self.execute(self.URL_REVIEWS,
                                      {"doc": appid, "o": startIndex, "n": entriesCount, "sort": 0},
                                      lang)
        result = []
        rp = response.payload
        if rp.HasField("reviewResponse"):
            for review in rp.reviewResponse.getResponse.review:
                result.append(self._toDict(review))
        defer.returnValue(result)
