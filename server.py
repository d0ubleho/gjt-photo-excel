#!/usr/bin/env python3
"""Local Mac uploader and workbook generator. Python 3.10+."""
import argparse
import json
import re
import secrets
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit
from zipfile import ZipFile

from recognition import matching_stickers, parse_form
from workbook import make_workbook

BASE = Path(__file__).resolve().parent
MAX_IMAGE = 24 * 1024 * 1024
MAX_FORMS = 20
MAX_ITEMS = 50


def read_photo_layout():
    try:
        config = json.loads((BASE/'사진크기.json').read_text(encoding='utf-8'))
        width, height = config['photoColumnPx'], config['itemRowPt']
        if type(width) is not int or type(height) is not int or not (140 <= width <= 600 and 80 <= height <= 350):
            raise ValueError
    except (OSError,ValueError,KeyError,TypeError):
        raise ValueError('사진크기.json을 확인하세요. photoColumnPx는 140~600, itemRowPt는 80~350 사이의 정수입니다.') from None
    return {'photoColumnPx':width,'itemRowPt':height}


def export_batch(forms, photos, directory):
    if not isinstance(forms,list) or not 1 <= len(forms) <= MAX_FORMS:
        raise ValueError(f'신청서는 한 번에 1~{MAX_FORMS}장까지 저장할 수 있습니다.')
    data = []
    for i,form in enumerate(forms,1):
        try:
            data.append(validated(form,photos,directory))
        except ValueError as e:
            raise ValueError(f'신청서 {i}번: {e}') from e
    result = BytesIO()
    counts = {}
    layout = read_photo_layout()
    with ZipFile(result,'w') as archive:
        for form in data:
            number = form['header']['application']
            key = number.casefold()
            counts[key] = counts.get(key,0) + 1
            suffix = f' ({counts[key]})' if counts[key]>1 else ''
            archive.writestr(f'{number} 회수 완료 사진{suffix}.xlsx',make_workbook(form,layout))
    return result.getvalue()


def validated(payload, photos, directory):
    header = {k: str(payload['header'].get(k, '')).strip() for k in ('department','application','applicant')}
    if any(not v or len(v)>60 for v in header.values()):
        raise ValueError('신청부서, 신청번호, 신청자를 확인하세요.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}', header['application']):
        raise ValueError('신청번호는 영문자, 숫자, 하이픈 또는 밑줄로 입력하세요.')
    raw = payload['items']
    if not 1 <= len(raw) <= MAX_ITEMS:
        raise ValueError(f'엑셀 파일 하나에 품목을 1~{MAX_ITEMS}개 넣을 수 있습니다.')
    result, seen = [], set()
    for i,r in enumerate(raw,1):
        name, asset, old = (str(r.get(k,'')).strip() for k in ('name','asset','old'))
        category = r.get('category')
        try:
            quantity = int(str(r.get('quantity')))
        except ValueError:
            quantity = 0
        if not name or len(name)>80 or category not in ('불용','반납') or not 1<=quantity<=9999:
            raise ValueError(f'{i}행의 구분, 품명, 수량을 확인하세요.')
        if not re.fullmatch(r'\d{10}', asset) or (old and not re.fullmatch(r'\d{15}',old)):
            raise ValueError(f'{i}행의 자산번호(10자리)와 구번호(있으면 15자리)를 확인하세요.')
        if asset in seen:
            raise ValueError(f'{i}행에 중복 자산번호가 있습니다.')
        seen.add(asset)
        out = dict(order=i, name=name, asset=asset, old=old, quantity=quantity, category=category)
        for k in ('photo','sticker'):
            if not r.get(k):
                continue
            picture = photos.get(r[k])
            if not picture or picture['kind'] != k:
                raise ValueError(f'{i}행에 선택한 사진을 찾지 못했습니다. 다시 올려 주세요.')
            out[k] = {field:picture[field] for field in ('id','width','height')}
        result.append(out)
    return dict(header=header, items=result, directory=str(directory))


def serve(args, directory):
    photos = {}
    scan_lock = threading.Lock()
    prefix = '/' + (args.token or secrets.token_urlsafe(24)) + '/'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def send_body(self, status, body, mime, attachment=None):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',
                             "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            if attachment:
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(attachment))
            self.end_headers()
            self.wfile.write(body)

        def reply(self, status, value):
            self.send_body(status,json.dumps(value,ensure_ascii=False).encode(),'application/json; charset=utf-8')

        def read_body(self, limit):
            size = int(self.headers.get('Content-Length',0))
            if not 0 < size <= limit:
                raise ValueError('파일이 비어 있거나 너무 큽니다. 사진은 한 장당 24MB까지 가능합니다.')
            return self.rfile.read(size)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == prefix:
                self.send_body(200,(BASE/'index.html').read_bytes(),'text/html; charset=utf-8')
            elif path == prefix + 'app.js':
                self.send_body(200,(BASE/'app.js').read_bytes(),'text/javascript; charset=utf-8')
            elif path.startswith(prefix+'image/') and (pid := path.removeprefix(prefix+'image/')) in photos:
                self.send_body(200,(directory/(pid+'.jpg')).read_bytes(),'image/jpeg')
            else:
                self.reply(404,{'error':'터미널에 표시된 주소 전체로 접속하세요.'})

        def do_POST(self):
            route = urlsplit(self.path)
            try:
                if route.path == prefix+'scan':
                    kind = parse_qs(route.query).get('kind',[''])[0]
                    if kind not in ('form','photo','sticker'):
                        raise ValueError('사진 종류를 선택하세요.')
                    body = self.read_body(MAX_IMAGE)
                    with scan_lock:
                        if len(photos)>=150:
                            raise ValueError('사진이 150장 쌓였습니다. 프로그램을 재시작하세요.')
                        pid = secrets.token_hex(12)
                        source = directory/(pid+'.input')
                        result = directory/(pid+'.json')
                        target = directory/(pid+'.jpg')
                        source.write_bytes(body)
                        try:
                            subprocess.run([BASE/'vision-ocr',kind,source,target,result],timeout=40,check=True,
                                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                            scan = json.loads(result.read_bytes())
                        except (subprocess.SubprocessError,OSError) as e:
                            target.unlink(missing_ok=True)
                            if isinstance(e,subprocess.CalledProcessError):
                                print(e.stderr.decode(errors='replace').strip(),flush=True)
                            raise ValueError('사진을 읽지 못했습니다. JPEG·PNG·HEIC 사진을 다시 선택하세요.') from e
                        finally:
                            source.unlink(missing_ok=True)
                            result.unlink(missing_ok=True)
                        picture = dict(id=pid, kind=kind, scan=scan,
                                       name=unquote(self.headers.get('X-Photo-Name','사진'))[:200],
                                       width=scan['width'],height=scan['height'])
                        photos[pid] = picture
                    public = {k:picture[k] for k in ('id','kind','name')}
                    if kind=='form':
                        public['header'],public['items'],public['notes'] = parse_form(scan)
                    self.reply(200,public)
                elif route.path == prefix+'match':
                    body = json.loads(self.read_body(96_000))
                    stickers = [photos[k] for k in body['stickers'] if k in photos and photos[k]['kind']=='sticker']
                    self.reply(200,{'matches':[matching_stickers(row,stickers) for row in body['items']]})
                elif route.path == prefix+'export':
                    data = validated(json.loads(self.read_body(96_000)),photos,directory)
                    body = make_workbook(data,read_photo_layout())
                    self.send_body(200,body,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                   data['header']['application']+' 회수 완료 사진.xlsx')
                elif route.path == prefix+'export-batch':
                    payload = json.loads(self.read_body(800_000))
                    body = export_batch(payload['forms'],photos,directory)
                    self.send_body(200,body,'application/zip','회수 완료 사진 모음.zip')
                else:
                    self.reply(404,{'error':'주소를 확인하세요.'})
            except (ValueError,KeyError,TypeError) as e:
                self.reply(400,{'error':str(e) if isinstance(e,ValueError) else '요청을 읽지 못했습니다.'})
            except (OSError,subprocess.SubprocessError):
                self.reply(500,{'error':'엑셀 파일을 만들지 못했습니다. Mac 터미널을 확인하세요.'})

    with ThreadingHTTPServer((args.bind,args.port),Handler) as server:
        print(f'이 Mac: http://127.0.0.1:{args.port}{prefix}',flush=True)
        if args.bind != '127.0.0.1':
            for dev in ('en0','en1'):
                addr = subprocess.run(['/usr/sbin/ipconfig','getifaddr',dev],capture_output=True,text=True).stdout.strip()
                if re.fullmatch(r'[\d.]+',addr):
                    print(f'아이폰 Safari: http://{addr}:{args.port}{prefix}',flush=True)
        print('종료: Control+C',flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--bind',default='127.0.0.1')
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--token',help=argparse.SUPPRESS)
    args = p.parse_args()
    if not (BASE/'vision-ocr').is_file():
        p.exit(1,'OCR 실행 파일이 없습니다. 시작.command를 실행하세요.\n')
    with tempfile.TemporaryDirectory(prefix='asset-ocr-') as temp:
        serve(args,Path(temp))
