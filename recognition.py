"""Extract rows from the supplied Korean disposal form using OCR coordinates."""
import re


def compact(s):
    return re.sub(r'\s+', '', s)


def center(line, dim):
    return line[dim] + line[{'x': 'w', 'y': 'h'}[dim]] / 2


def identifiers(text):
    text = compact(text)
    matches = set(re.findall(r'(?<!\d)(?:\d{15}|\d{10})(?!\d)', text))
    matches.update(m.replace('-', '') for m in re.findall(r'(?<!\d)\d-\d{8}-\d{6}(?!\d)', text))
    return matches


def parse_form(scan):
    lines = scan['lines']
    notes = []
    fields = {}
    for key, label in [('department', '신청부서'), ('application', '신청번호'), ('applicant', '신청자')]:
        hits = [t for t in lines if compact(t['text']).startswith(label)]
        val = ''
        if hits:
            t = min(hits, key=lambda t: t['y'])
            val = re.sub(r'^' + r'\s*'.join(label) + r'\s*[:：.]?\s*', '', t['text']).strip()
            if not val:
                nearby = [l for l in lines if 0 <= l['x'] - (t['x']+t['w']) < .08 and
                          abs(center(l,'y')-center(t,'y')) < .02]
                if nearby:
                    val = min(nearby, key=lambda l:l['x'])['text'].strip()
        if key == 'application':
            val = compact(val).upper()
            if re.fullmatch(r'24\d{8}', val):
                val = '2A' + val[2:]
                notes.append('신청번호의 두 번째 글자가 4로 인식되어 양식의 2A 패턴을 적용했습니다. 원본을 확인하세요.')
        if not val:
            notes.append(label + '를 읽지 못했습니다.')
        fields[key] = val

    def find(label, after=0):
        return min((t for t in lines if t['y'] > after and compact(t['text']) == label),
                   key=lambda t:t['y'], default=None)

    a = find('자산번호')
    c = find('구분')
    n = find('품명')
    q = find('수량', a['y']-.13) if a else None
    if not all((a,c,n,q)) or abs(q['y']-a['y']) > .15:
        return fields, [], notes + ['표의 구분·품명·자산번호·수량 머리글을 읽지 못했습니다. 사진을 다시 찍거나 행을 직접 추가하세요.']
    ax, cx, nx, qx = (center(t,'x') for t in (a,c,n,q))
    mx = center(m,'x') if (m := find('규격/모델', a['y']-.15)) else (ax+qx)/2
    slope = (center(q,'y')-center(c,'y')) / (qx-cx)
    def y(t):
        return center(t,'y') - (center(t,'x')-ax)*slope
    stop = find('회수확인자', a['y'])
    asset_l, asset_r = (nx+ax)/2, (ax+mx)/2
    body = [t for t in lines if y(t) > y(a)+.018 and (not stop or y(t) < y(stop)-.02)]
    anchors = sorted((t for t in body if asset_l < center(t,'x') < asset_r and
                      re.match(r'^\d{10}(?!\d)',compact(t['text']))), key=y)
    rows = []
    for i,t in enumerate(anchors):
        ya = y(t)
        low = (y(anchors[i-1])+ya)/2 if i else ya-.12
        high = (ya+y(anchors[i+1]))/2 if i+1<len(anchors) else ya+.075
        row = [l for l in body if low < y(l) <= high]
        def closest(test):
            return min((l for l in row if test(l)), key=lambda l: abs(y(l)-ya), default=None)
        asset = compact(t['text'])[:10]
        old = next((s for s in sorted(identifiers(t['text'])) if len(s)==15), '')
        prev = closest(lambda l: asset_l < center(l,'x') < asset_r and y(l) > ya and
                       any(len(s)==15 for s in identifiers(l['text'])))
        if not old and prev:
            old = next(s for s in sorted(identifiers(prev['text'])) if len(s)==15)
        names, category = [], ''
        for l in sorted(row,key=y):
            x = center(l,'x')
            s = l['text'].strip()
            if (cx-.045) < x < asset_l and (m := re.match(r'^(불\s*용|반\s*납)\s*[/|]?\s*(.*)$',s)):
                category = compact(m[1])
                if m[2]:
                    names.append(m[2])
            elif (cx+nx)/2 < x < asset_l and re.search(r'[가-힣A-Za-z]',s):
                names.append(s)
        qty = closest(lambda l: (mx+qx)/2 < center(l,'x') < qx+(qx-mx)*.43 and
                      re.fullmatch(r'[1-9]\d{0,3}',compact(l['text'])))
        rows.append(dict(order=i+1, category=category, name=' '.join(names), asset=asset, old=old,
                         quantity=int(compact(qty['text'])) if qty else None))
    total = next((int(m[1]) for l in lines if (m := re.search(r'\((\d+)\)개중', compact(l['text'])))), None)
    if total is not None and total != sum(r['quantity'] or 0 for r in rows):
        notes.append(f'신청서의 총수량({total})과 인식한 수량 합계가 다릅니다. 빠진 품목이나 수량을 확인하세요.')
    if not rows:
        notes.append('자산번호가 적힌 행을 찾지 못했습니다. 사진을 다시 찍거나 행을 직접 추가하세요.')
    elif any(not r['name'] or not r['category'] or r['quantity'] is None for r in rows):
        notes.append('일부 품명·구분·수량을 읽지 못했습니다.')
    return fields, rows, notes


def matching_stickers(row, stickers):
    keys = {row.get('asset'),row.get('old')} - {'',None}
    ranked = []
    for picture in stickers:
        score = max((3 + 6*b['w'] - abs(center(b,'y')-.40)
                     for b in picture['scan']['codes'] if keys & identifiers(b['text'])),default=0)
        if not score:
            score = max((1 + l['confidence']/2 - abs(center(l,'y')-.40)
                         for l in picture['scan']['lines'] if keys & identifiers(l['text'])),default=0)
        if score:
            ranked.append((score,picture['id']))
    return [p for _,p in sorted(ranked,reverse=True)]
