# google-play-review-notify

*google-play-review-notify* is Google Play new applications review notification XMPP/Jabber bot
written in Python using [Twisted](https://twistedmatrix.com/trac/) framework.

## Installation

*google-play-review-notify* runs on Python 2.7. Clone the repo in the directory of your choice using git:

`git clone https://github.com/3cky/google-play-review-notify`

Next, install all needed Python requirements using [pip](https://pip.pypa.io/en/latest/) package manager:

`cd google-play-review-notify`
`sudo pip install -r ./requirements.txt`

Then install *google-play-review-notify* itself:

`sudo python setup.py install`

## Configuration

Before run this bot, you will have to create a configuration file. You could use
provided `doc/google-play-review-notify.cfg` as example. Minimal configuration includes specifying
Google account information needed for accessing Google API, XMPP/Jabber server login and password,
list of application package names to monitor reviews and mapping of these applications to
notification chats.

## Run

Run *google-play-review-notify* by command `twistd -n google-play-review-notify -c /path/to/config/file.cfg`

## Customising notification message

*google-play-review-notify* uses [Jinja2](http://jinja.pocoo.org/) template engine to compose notifications.
You could override internal template by your own file using `template` variable in `[notification]`
section of configuration file.

## Details

It's strange but Google still have no official API for accessing applications reviews, so this bot
using unofficial reverse-engineered Protobuf-based internal Google Market API
(https://github.com/liato/android-market-api-py). This API is outdated, limited by functions and
could break at all at any moment, but it's still better than nothing.

