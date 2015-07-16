# -*- coding: utf-8 -*-
'''
Created on 10-Jul-2015

@author: 3cky
'''

from twisted.python import log
from wokkel.muc import MUCClient

from fnmatch import fnmatch

class MUCNotifier(MUCClient):
    """
    Multi-user chat notifier.
    """
    def __init__(self, chatJID, nick, appIdPatterns):
        MUCClient.__init__(self)
        self.chatJID = chatJID
        self.nick = nick
        self.appIdPatterns = appIdPatterns

    def connectionInitialized(self):
        """
        Join to the chat with given JID.
        """
        def joinedChat(chat):
            if chat.locked:
                # Just accept the default configuration.
                return self.configure(chat.chatJID, {})
        MUCClient.connectionInitialized(self)
        d = self.join(self.chatJID, self.nick)
        d.addCallback(joinedChat)
        d.addCallback(lambda _: log.msg("Joined chat:", self.chatJID.full()))
        d.addErrback(log.err, "Join chat failed:", self.chatJID.full())

    def isNotifierForApp(self, appId):
        """
        Test whether this notifier is interested in given app reviews
        """
        for appIdPattern in self.appIdPatterns:
            if fnmatch(appId, appIdPattern):
                return True
        return False


    def notify(self, message):
        """
        Send message to chat.
        """
        self.groupChat(self.chatJID, message)

