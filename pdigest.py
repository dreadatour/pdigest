# coding: utf-8
import datetime
import re
import time

import requests
from flask import Flask, render_template, request


app = Flask(__name__)
app.config.from_object('config')


url_re = re.compile(
    r'(\bhttps?:\/\/[a-z0-9-+&@#\/%?=~_|!:,.;]*[a-z0-9-+&@#\/%=~_|])',
    re.UNICODE | re.I
)
youtube_re = re.compile(
    r'^https?:\/\/www\.youtube\.com\/watch\?v=(.*?)(&.*)?$',
    re.UNICODE | re.I
)
youtube_link = (
    '<iframe width="560" height="315" src="//www.youtube.com/embed/{0}"'
    ' frameborder="0" allowfullscreen class="video"></iframe>'
)
vimeo_re = re.compile(
    r'^https?:\/\/vimeo\.com\/(\d+)(?:\?.*)?$', re.UNICODE | re.I
)
vimeo_link = (
    '<iframe src="//player.vimeo.com/video/{0}" width="500" height="281"'
    ' frameborder="0" webkitallowfullscreen mozallowfullscreen allowfullscreen'
    ' class="video"></iframe>'
)
slideshare_re = re.compile(
    r'^https?:\/\/(?:www\.)?slideshare\.net\/', re.UNICODE | re.I
)
slideshare_link = 'http://www.slideshare.net/api/oembed/2?url={0}&format=json'


def linkify(text):
    """
    Search for url in text and return link tag with this url.
    """
    match = url_re.findall(text)
    if len(match) != 1:
        return

    link = match[0]
    link_re = re.compile(
        ur'\s*[\-\:\-\—\—\―]?\s*' + re.escape(link), re.UNICODE
    )
    text = link_re.sub('', text)
    text = re.sub(r'</?p>', '', text)
    text = re.sub(r'\n+', '<br><br>', text)
    return u'<a href="{0}">{1}</a>'.format(link, text)


def get_embed(text):
    """
    Get embed links from text.
    """
    result = []

    matches = url_re.findall(text)
    if matches:
        for url in matches:
            match = youtube_re.match(url)
            if match:
                result.append(youtube_link.format(match.group(1)))
                continue

            match = vimeo_re.match(url)
            if match:
                result.append(vimeo_link.format(match.group(1)))

            match = slideshare_re.match(url)
            if match:
                response = requests.get(slideshare_link.format(url))
                if not response or response.status_code != 200:
                    continue
                slideshare_data = response.json()
                if not slideshare_data or 'html' not in slideshare_data:
                    continue
                result.append(
                    re.sub(r'>\s*</iframe>.*', ' class="slides"></iframe>',
                           slideshare_data['html'])
                )

    return result


def str2date(text):
    """
    Convert facebook date from string to date object.
    """
    text_date = re.sub(r'T.*', '', text)
    return datetime.datetime.strptime(text_date, '%Y-%m-%d').date()


class FacebookError(Exception):
    pass


class Facebook(object):
    """
    Work with Facebook API.
    """
    app_id = None
    app_secret = None
    group_id = None
    access_token = None
    data = None

    def __init__(self, app_id, app_secret, group_id):
        self.app_id = app_id
        self.app_secret = app_secret
        self.group_id = group_id
        self.access_token = None

    def get_access_token(self):
        """
        Get Facebook access token.
        """
        access_token_url = 'https://graph.facebook.com/oauth/access_token'
        params = {
            'client_id': self.app_id,
            'client_secret': self.app_secret,
            'grant_type': 'client_credentials',
        }
        response = requests.get(access_token_url, params=params)

        if response.status_code != 200:
            raise FacebookError('Wrong auth response status code: {0}'.format(
                response.status_code
            ))

        if not response.text.startswith('access_token='):
            raise FacebookError('Wrong auth respoce: {0}'.format(
                response.text
            ))

        self.access_token = response.text

    def get_posts(self, since, until):
        """
        Get group posts.
        """
        # import ipdb; ipdb.set_trace()  # Achtung!
        since_timestamp = int(time.mktime(since.timetuple()))
        until_timestamp = int(time.mktime(until.timetuple()))

        if self.access_token is None:
            self.get_access_token()

        feed_url = (
            'https://graph.facebook.com/v2.2/{0}?fields=feed'
            '.since({1}).until({2}).limit(9999).fields('
            'id,attachments,full_picture,from,message,picture,link,name,'
            'caption,description,created_time,updated_time,'
            'comments.limit(9999).fields(created_time,message))&{3}'
        ).format(
            self.group_id,
            since_timestamp,
            until_timestamp,
            self.access_token
        )

        result = []

        counter = 0
        while True:
            counter += 1
            if counter > 100:
                raise FacebookError('Too many requests')

            response = requests.get(feed_url)

            if response.status_code != 200:
                raise FacebookError(
                    'Wrong feed response status code: {0}'.format(
                        response.status_code
                    )
                )

            try:
                data_json = response.json()
            except Exception:
                raise FacebookError('Wrong feed response: {0}'.format(
                    response.text
                ))
            else:
                if 'feed' in data_json:
                    data = data_json['feed']
                else:
                    data = data_json

            if 'data' not in data or not data['data']:
                if result:
                    break
                raise FacebookError('Empty feed response: {0}'.format(
                    response.text
                ))

            is_enough = False

            if 'paging' in data and 'next' in data['paging']:
                feed_url = data['paging']['next']
            else:
                is_enough = True

            for post in data['data']:
                if 'updated_time' not in post or not post['updated_time']:
                    continue

                if str2date(post['updated_time']) > until:
                    continue

                if str2date(post['updated_time']) < since:
                    is_enough = True
                    break

                result.append(post)

            if is_enough:
                break

        return result


def get_digest(since, until):
    """
    Get digest page.
    """
    facebook_api = Facebook(
        app_id=app.config['FACEBOOK_APP_ID'],
        app_secret=app.config['FACEBOOK_APP_SECRET'],
        group_id=app.config['FEED_ID']
    )

    try:
        posts = facebook_api.get_posts(since=since, until=until)
    except FacebookError:
        return

    result = []
    for post in posts:
        name = post.get('name')
        link = post.get('link')
        message = post.get('message')

        if name:
            name = re.sub(r'\n+', ' ', name)

        if not link and message:
            match = url_re.findall(message)
            if len(match) > 0:
                link = match[0]

        if message:
            message = re.sub(r'</?p>', '', message)
            message = re.sub(r'\n+', '<br><br>', message)
            message = re.sub(r'<', '&lt;', message)
            message = re.sub(r'>', '&gt;', message)
            if link:
                link_re = re.compile(
                    ur'\s*[\-\:\-\—\—\―]?\s*' + re.escape(link), re.UNICODE
                )
                message = link_re.sub('', message)

        embeds = []
        if link:
            embeds.extend(get_embed(link))
        if message:
            embeds.extend(get_embed(message))

        post_comments = post.get('comments')
        if post_comments and 'data' in post_comments:
            post_comments = post_comments['data']
        else:
            post_comments = []

        comments = []
        for comment in post_comments:
            comment_time = comment.get('created_time')
            if not comment_time:
                continue
            comment_time = re.sub(r'T.*', '', comment_time)
            comment_time = datetime.datetime.strptime(comment_time, '%Y-%m-%d')
            if comment_time.date() < since:
                continue
            # if comment_time.date() > until:
            #     continue

            comment_text = comment.get('message', '')

            comment_embed = get_embed(comment_text)
            if comment_embed:
                embeds.extend(comment_embed)
                continue

            comment_link = linkify(comment_text)
            if comment_link:
                comments.append(comment_link)

        data = {
            'name': name,
            'link': link,
            'message': message,
            'comments': comments,
            'embeds': list(set(embeds)),
            'is_old': bool(str2date(post['created_time']) < since),
        }

        result.append(data)

    return result


@app.errorhandler(404)
def error_not_found(e):
    """
    View '404 Page not found' error.
    """
    return render_template('error.html', code=404), 404


@app.errorhandler(500)
def error_server(e):
    """
    View '500 Server error' error.
    """
    return render_template('error.html', code=500), 500


@app.route('/', methods=['GET'])
def index():
    """
    Get index page.
    """
    since = request.args.get('since', None)
    until = request.args.get('until', None)
    pdigest = None

    if since:
        if until:
            try:
                until = datetime.datetime.strptime(until, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                until = None

        try:
            since = datetime.datetime.strptime(since, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            since = None
        else:
            pdigest = get_digest(since, until)

    return render_template(
        'index.html',
        since=since,
        until=until,
        pdigest=pdigest
    )


if __name__ == '__main__':
    app.run()
