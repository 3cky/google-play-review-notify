# Modified version of https://github.com/liato/android-market-api-py

import base64
import gzip
import StringIO

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
    SERVICE = "android";
    URL_LOGIN = "https://www.google.com/accounts/ClientLogin"
    HOST_API_REQUEST = "android.clients.google.com/market/api/ApiRequest"
    ACCOUNT_TYPE_GOOGLE = "GOOGLE"
    ACCOUNT_TYPE_HOSTED = "HOSTED"
    ACCOUNT_TYPE_HOSTED_OR_GOOGLE = "HOSTED_OR_GOOGLE"
    PROTOCOL_VERSION = 2
    authSubToken = None
    context = None

    def __init__(self):
        self.context = market_proto.RequestContext()
        self.context.isSecure = 0
        self.context.version = 1002012
        self.context.androidId = "0123456789123456" # change me :(
#         self.context.userLanguage = "ru"
#         self.context.userCountry = "RU"
        self.context.deviceAndSdkVersion = "crespo:10"
        self.setOperatorTMobile()

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
                    msg[fielddesc.name.lower()] = self._toDict(value)
                else:
                    msg[fielddesc.name.lower()] = value
            retlist.append(msg)
        if not iterable:
            if len(retlist) > 0:
                return retlist[0]
            else:
                return None
        return retlist

    def setOperatorSimple(self, alpha, numeric):
        self.setOperator(alpha, alpha, numeric, numeric);

    def setOperatorTMobile(self):
        self.setOperatorSimple("T-Mobile", "310260")

    def setOperatorSFR(self):
        self.setOperatorSimple("F SFR", "20810")

    def setOperatorO2(self):
        self.setOperatorSimple("o2 - de", "26207")

    def setOperatorSimyo(self):
        self.setOperator("E-Plus", "simyo", "26203", "26203")

    def setOperatorSunrise(self):
        self.setOperatorSimple("sunrise", "22802")

    def setOperator(self, alpha, simAlpha, numeric, simNumeric):
        self.context.operatorAlpha = alpha
        self.context.simOperatorAlpha = simAlpha
        self.context.operatorNumeric = numeric
        self.context.simOperatorNumeric = simNumeric

    def setAuthSubToken(self, authSubToken):
        self.context.authSubToken = authSubToken
        self.authSubToken = authSubToken

    @defer.inlineCallbacks
    def login(self, email, password, accountType = ACCOUNT_TYPE_HOSTED_OR_GOOGLE):
        params = {"Email": email, "Passwd": password, "service": self.SERVICE,
                  "accountType": accountType}
        resp = yield treq.get(self.URL_LOGIN, params=params)
        if resp.code == http.OK:
            data = yield treq.content(resp)
            data = data.split()
            params = {}
            for d in data:
                k, v = d.split("=")
                params[k.strip().lower()] = v.strip()
            if "auth" in params:
                self.setAuthSubToken(params["auth"])
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
                        params[k.strip().lower()] = v.strip()
                if "error" in params:
                    raise LoginError(params["error"])
                else:
                    raise LoginError("Login failed.")
            else:
                data = yield treq.content(resp)
                raise LoginError("Login failed: error %d <%s>" % (resp.code, data.rstrip(),))

    @defer.inlineCallbacks
    def execute(self, request):
        request.context.CopyFrom(self.context)
        try:
            headers = {"Cookie": "ANDROID="+self.authSubToken,
                       "User-Agent": "Android-Market/2 (sapphire PLAT-RC33); gzip",
                       "Content-Type": "application/x-www-form-urlencoded",
                       "Accept-Charset": "ISO-8859-1,utf-8;q=0.7,*;q=0.7"}
            data = request.SerializeToString()
            params = {"version": self.PROTOCOL_VERSION, "request": base64.urlsafe_b64encode(data)}

            if self.context.isSecure == 1 or self.context.isSecure == True:
                http_method = "https"
            else:
                http_method = "http"

            resp = yield treq.get(http_method + "://" + self.HOST_API_REQUEST,
                                  params=params, headers=headers)
            if resp.code == http.OK:
                data = yield treq.content(resp)
                data = StringIO.StringIO(data)
                gzipper = gzip.GzipFile(fileobj=data)
                data = gzipper.read()
                response = market_proto.Response()
                response.ParseFromString(data)
                defer.returnValue(response)
            else:
                raise RequestError("Error %d" % resp.code)
        except Exception, e:
            raise RequestError(e)

    @defer.inlineCallbacks
    def getReviews(self, appid, startIndex = 0, entriesCount = 10):
        request = market_proto.Request()
        commentsRequest = request.requestgroup.add()
        req = commentsRequest.commentsRequest
        req.appId = appid
        req.startIndex = startIndex
        req.entriesCount = entriesCount
        response = yield self.execute(request)
        retlist = []
        for rg in response.responsegroup:
            if rg.HasField("commentsResponse"):
                for comment in rg.commentsResponse.comments:
                    retlist.append(self._toDict(comment))
        defer.returnValue(retlist)
