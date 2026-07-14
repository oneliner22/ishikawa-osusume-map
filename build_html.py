# -*- coding: utf-8 -*-
"""data/spots.json + data/videos.json + data/config.json -> index.html
YouTube出典版: replies の代わりに videos(動画ID→タイトル/チャンネル)を埋め込む。
使い方: python build_html.py  (カレントはプロジェクトルート想定)
"""
import json, io

spots  = json.load(io.open('data/spots.json', encoding='utf-8'))
videos = json.load(io.open('data/videos.json', encoding='utf-8'))
cfg    = json.load(io.open('data/config.json', encoding='utf-8'))

used = set()
for s in spots['spots']:
    used.update(s['videos'])
slim = {k: {'title': videos[k].get('title', ''), 'channel': videos[k].get('channel', '')}
        for k in used if k in videos}

payload = {'config': cfg, 'areas': spots['areas'], 'spots': spots['spots'], 'videos': slim}
js = 'window.__SPOTMAP__ = ' + json.dumps(payload, ensure_ascii=False) + ';'

tpl = io.open('template.html', encoding='utf-8').read()
repl = {
  '__TITLE__':   cfg.get('title', ''),
  '__DESC__':    cfg.get('description', ''),
  '__FAVICON__': cfg.get('favicon', '📍'),
  '__H1__':      cfg.get('h1', cfg.get('title', '')),
  '__LEAD__':    cfg.get('lead', ''),
  '__META__':    cfg.get('meta', ''),
  '__FOOTER__':  cfg.get('footer', ''),
}
for k, v in repl.items():
    tpl = tpl.replace(k, v)
tpl = tpl.replace('/*__DATA__*/', js)
io.open('index.html', 'w', encoding='utf-8').write(tpl)
print('wrote index.html (', len(tpl), 'bytes ) spots:', len(spots['spots']),
      'areas:', len(spots['areas']), 'videos embedded:', len(slim))
