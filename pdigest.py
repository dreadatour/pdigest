# coding: utf-8
import datetime
import re
import time

import requests
from facepy import GraphAPI, utils
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


def get_digest(since):
    """
    Get digest page.
    """
    since_timestamp = int(time.mktime(since.timetuple()))
    facebook_request = (
        '/173955382668026?fields=feed.since({0}).limit(9999).fields('
        'id,attachments,full_picture,from,message,picture,link,name,caption,'
        'description,comments.limit(9999).fields(created_time,message))'
    ).format(since_timestamp)

    app_id = int(app.config['FACEBOOK_APP_ID'])
    app_secret = app.config['FACEBOOK_APP_SECRET']
    access_token = utils.get_application_access_token(app_id, app_secret)

    graph = GraphAPI(access_token)
    posts = graph.get(facebook_request)

    if not posts or'feed' not in posts or 'data' not in posts['feed']:
        return

    result = []
    for post in posts['feed']['data']:
        name = post.get('name')
        if name:
            name = re.sub(r'\n+', ' ', name)

        link = post.get('link')

        message = post.get('message')
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
    pdigest = None

    if since:
        try:
            since = datetime.datetime.strptime(since, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            since = None
        else:
            pdigest = get_digest(since)

    return render_template('index.html', since=since, pdigest=pdigest)


if __name__ == '__main__':
    app.run()
