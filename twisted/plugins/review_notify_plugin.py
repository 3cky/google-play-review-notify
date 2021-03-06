# -*- coding: utf-8 -*-
'''
Created on 10-Jul-2015

@author: 3cky
'''

import os

from zope.interface import implements

from twisted.python import usage
from twisted.plugin import IPlugin
from twisted.application.service import IServiceMaker
from twisted.application import service
from twisted.words.protocols.jabber.jid import JID
from twisted.internet import reactor
from twisted.internet import defer
from twisted.python import log
from twisted.enterprise import adbapi

from wokkel.client import XMPPClient
from ConfigParser import ConfigParser
from jinja2 import Environment, PackageLoader, FileSystemLoader

from datetime import datetime

import pkg_resources

import babel.dates
import babel.support

import codecs

import humanfriendly

from reviewnotify.notifiers import MUCNotifier
from reviewnotify.googleplay.market import MarketSession, RequestError

TAP_NAME = "google-play-review-notify"

REVIEW_URL = 'https://play.google.com/apps/publish/?dev_acc={devId}#ReviewDetailsPlace:p={appId}&reviewid={reviewId}'

DEFAULT_DB_FILENAME = 'reviews_db.sqlite'

DEFAULT_NICKNAME = TAP_NAME
DEFAULT_TEMPLATE_NAME = 'reviews.txt'

RELOGIN_TIMEOUT = 60 # 1m

DEFAULT_POLL_PERIOD = 600 # 10m
DEFAULT_POLL_DELAY = 5
DEFAULT_LANG = 'en'

class ConfigurationError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)


class Options(usage.Options):
    optParameters = [["config", "c", None, 'Configuration file name']]


class Application(object):
    def __init__(self, appId, appName):
        self.identifier = appId
        self.name = appName
    def __str__(self):
        return repr(self.identifier)


class ServiceManager(object):
    implements(IServiceMaker, IPlugin)
    tapname = TAP_NAME
    description = "XMPP notifications about Google Play apps reviews."
    options = Options
    mucNotifiers = []
    apps = []
    langs = []

    def makeService(self, options):
        # create Twisted application
        application = service.Application(TAP_NAME)
        serviceCollection = service.IServiceCollection(application)

        # check confguration file is specified and exists
        if not options["config"]:
            raise ValueError('Configuration file not specified (try to check --help option)')
        cfgFileName = options["config"];
        if not os.path.isfile(cfgFileName):
            raise ConfigurationError('Configuration file not found:', cfgFileName)

        # read configuration file
        cfg = ConfigParser()
        with codecs.open(cfgFileName, 'r', encoding='utf-8') as f:
            cfg.readfp(f)

        # get Google login and password from configuration
        if not cfg.has_option('account', 'login') or not cfg.has_option('account', 'password'):
            raise ConfigurationError('Google account login and password must be specified '
                                     'in configuration file [account] section')
        self.googleLogin = cfg.get('account', 'login')
        self.googlePassword = cfg.get('account', 'password')
        self.googleDeveloperId = cfg.get('account', 'developer_id') \
            if cfg.has_option('account', 'developer_id') else None
        # get ANDROID_ID from configuration
        if not cfg.has_option('account', 'android_id'):
            raise ConfigurationError('ANDROID_ID must be specified in configuration file [account] section')
        self.androidId = cfg.get('account', 'android_id')

        # get apps to monitor reviews
        apps = cfg.items('apps')
        if not apps:
            raise ConfigurationError('No apps to monitor reviews defined '
                                     'in configuration file [apps] section')
        for appId, appName in apps:
            self.apps.append(Application(appId, appName))

        # open database
        dbFilename = cfg.get('db', 'filename') if cfg.has_option('db', 'filename') else DEFAULT_DB_FILENAME
        self.dbpool = adbapi.ConnectionPool("sqlite3", dbFilename, check_same_thread=False)

        # create XMPP client
        client = XMPPClient(JID(cfg.get('xmpp', 'jid')), cfg.get('xmpp', 'password'))
#         client.logTraffic = True
        client.setServiceParent(application)
        # join to all MUC rooms
        nickname = cfg.get('xmpp', 'nickname') if cfg.has_option('xmpp', 'nickname') else DEFAULT_NICKNAME
        notifications = cfg.items('chats')
        for chat, appIdPatterns in notifications:
            mucNotifier = MUCNotifier(JID(chat), nickname, appIdPatterns.split(','))
            mucNotifier.setHandlerParent(client)
            self.mucNotifiers.append(mucNotifier)

        self.pollPeriod = humanfriendly.parse_timespan(cfg.get('poll', 'period')) \
                if cfg.has_option('poll', 'period') else DEFAULT_POLL_PERIOD
        self.pollDelay = humanfriendly.parse_timespan(cfg.get('poll', 'delay')) \
                if cfg.has_option('poll', 'delay') else DEFAULT_POLL_DELAY
        self.langs = [lang.strip() for lang in cfg.get('poll', 'lang').split(',')] \
                if cfg.has_option('poll', 'lang') else [ DEFAULT_LANG ]
        templateLoader = None
        if cfg.has_option('notification', 'template'):
            templateFullName = cfg.get('notification', 'template')
            templatePath, self.templateName = os.path.split(templateFullName)
            templateLoader = FileSystemLoader(templatePath)
        else:
            self.templateName = DEFAULT_TEMPLATE_NAME
            templateLoader = PackageLoader('reviewnotify', 'templates')
        self.templateEnvironment = Environment(loader=templateLoader, extensions=['jinja2.ext.i18n'])
        localeDir = pkg_resources.resource_filename('reviewnotify', 'locales')
        locale = None
        if cfg.has_option('i18n', 'locale'):
            locale = cfg.get('i18n', 'locale')
        translations = babel.support.Translations.load(dirname=localeDir, locales=locale)
        self.templateEnvironment.install_gettext_translations(translations)
        self.templateEnvironment.filters['datetime'] = format_datetime
        self.templateEnvironment.filters['review_url'] = review_url

        reactor.callLater(3.0, self.run) # TODO make initial delay configurable

        return serviceCollection

    @defer.inlineCallbacks
    def run(self):
        template = self.templateEnvironment.get_template(self.templateName)
        yield self.dbCreateTables()
        # poll cycle loop
        session = MarketSession(self.androidId)
        while reactor.running:
            if not session.loggedIn:
                log.msg('Authorizing Google Play session...')
                try:
                    yield session.login(self.googleLogin, self.googlePassword)
                except Exception, e:
                    log.err(e, 'Can\'t authorize Google Play session')
                    # delay before next login try
                    yield sleep(RELOGIN_TIMEOUT)
                    continue
            log.msg('Checking for new reviews...')
            for app in self.apps:
                try:
                    # get last reviews for an application
                    notifyReviews = []
                    for lang in self.langs:
                        reviews = yield session.getReviews(appid=app.identifier, lang=lang)
                        for review in reviews:
                            reviewAuthorId = review.get('commentId')
                            reviewAuthorName = review.get('authorName')
                            reviewCreationTime = review.get('timestampMsec')
                            reviewRating = review.get('starRating')
                            reviewComment = review.get('comment')
                            # check for review with same author id
                            dbReviews = yield self.dbGetReviews(app.identifier, reviewAuthorId)
                            if not dbReviews:
                                # new review found, will add to database and notify
                                log.msg('Found new review for %s from author: %s' % (app, reviewAuthorId,))
                                notifyReviews.append(review)
                                yield self.dbAddReview(app.identifier, reviewAuthorId, reviewAuthorName,
                                                       reviewCreationTime, reviewRating, reviewComment)
                            else:
                                # review with given author ID already seen, check for changes
                                _appid, _authorId, _authorName, _timestamp, rating, comment = dbReviews[0]
                                if (reviewRating <> rating) or (reviewComment <> comment):
                                    # review changed, will update database and notify
                                    log.msg('Found changed review for %s from author: %s' % \
                                            (app.identifier, reviewAuthorId,))
                                    notifyReviews.append(review)
                                    yield self.dbUpdateReview(app.identifier, reviewAuthorId,
                                                              reviewRating, reviewComment)
                        if lang <> self.langs[-1]:
                            # delay before check next lang
                            yield sleep(self.pollDelay)
                    # notify about new reviews all related chats
                    if notifyReviews:
                        # sort reviews by creation time before notification
                        notifyReviews.sort(key = lambda k: k.get('timestampMsec'))
                        # notify all related chats
                        for mucNotifier in self.mucNotifiers:
                            if mucNotifier.isNotifierForApp(app.identifier):
                                mucNotifier.notify(template.render(devId=self.googleDeveloperId,
                                                                   app=app, reviews=notifyReviews))
                except RequestError, re:
                    if re.err_code == 401:
                        log.err(re, 'Access denied while checking for new reviews for an application %s' % app)
                        session.loggedIn = False
                        yield sleep(RELOGIN_TIMEOUT)
                        break
                    log.err(re, 'Can\'t request new reviews for an application %s' % app)
                except Exception, e:
                    log.err(e, 'Error while checking for new reviews for an application %s' % app)
                if app <> self.apps[-1]:
                    # delay before check next application
                    yield sleep(self.pollDelay)
            # delay before next applications poll cycle
            yield sleep(self.pollPeriod)

    def dbCreateTables(self):
        '''
        Create tables of database for reviews data storage (asynchronously)
        '''
        return self.dbpool.runQuery('CREATE TABLE IF NOT EXISTS reviews \
            (appid TEXT, authorid TEXT, authorname TEXT, \
                timestamp INTEGER, rating INTEGER, comment TEXT)')

    def dbGetReviews(self, appId, authorId):
        '''
        Get reviews for an application by author id from database (asynchronously)
        '''
        return self.dbpool.runQuery('SELECT * FROM reviews WHERE appid = ? AND authorid = ?', \
                                                              (appId, authorId,))

    def dbAddReview(self, appId, authorId, authorName, timestamp, rating, comment):
        '''
        Add new review of an application to database (asynchronously)
        '''
        return self.dbpool.runQuery('INSERT INTO reviews (appid, authorid, authorname, \
                timestamp, rating, comment) VALUES (?, ?, ?, ?, ?, ?)', \
            (appId, authorId, authorName, timestamp, rating, comment,))

    def dbUpdateReview(self, appId, authorId, rating, comment):
        '''
        Update an application review data in database (asynchronously)
        '''
        return self.dbpool.runQuery('UPDATE reviews SET rating = ?, comment = ? \
                WHERE appid = ? AND authorid = ?', (rating, comment, appId, authorId,))

def sleep(secs):
    '''
    Create deferred for pause to given timespan (in seconds)
    '''
    d = defer.Deferred()
    reactor.callLater(secs, d.callback, None)
    return d

def format_datetime(timestamp_msec):
    '''
    Convert given Unix timestamp (in milliseconds) to localized date string
    '''
    date = datetime.fromtimestamp(timestamp_msec / 1000.0)
    return babel.dates.format_datetime(date)

def review_url(reviewId, devId, app):
    '''
    Get Google Play developer console URL of application review
    '''
    return REVIEW_URL.format(devId=devId, appId=app.identifier, reviewId=reviewId)

serviceManager = ServiceManager()