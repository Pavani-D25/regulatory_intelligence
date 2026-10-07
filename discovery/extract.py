import os, sys, json, hashlib, re, zipfile
from multiprocessing import Pool
import pymupdf

# usage: python discovery/extract.py <corpus_dir> [out_dir]
BASE = sys.argv[1] if len(sys.argv) > 1 else r'D:\Regulatory_Documents'
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join('discovery', 'out')
TXT = os.path.join(OUT, 'text')
os.makedirs(TXT, exist_ok=True)
DEV = re.compile(r'[ऀ-ॿ]')
LAT = re.compile(r'[A-Za-z]')
WORD = re.compile(r'\b(the|of|and|shall|to|in|vehicle|rules?|notification)\b', re.I)

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()

def docx_text(p):
    try:
        with zipfile.ZipFile(p) as z:
            x = z.read('word/document.xml').decode('utf8', 'ignore')
        x = re.sub(r'</w:p>', '\n', x)
        return re.sub(r'<[^>]+>', '', x)
    except Exception as e:
        return ''

def one(p):
    rel = os.path.relpath(p, BASE)
    r = {'rel': rel.replace('\\', '/'), 'folder': rel.replace('\\', '/').split('/')[0], 'ext': p.rsplit('.', 1)[-1].lower(),
         'bytes': os.path.getsize(p)}
    try:
        r['sha256'] = sha(p)
    except Exception as e:
        r['err'] = str(e); return r
    pages = []
    if r['ext'] == 'pdf':
        try:
            d = pymupdf.open(p)
            r['pages'] = d.page_count
            r['meta'] = {k: v for k, v in (d.metadata or {}).items() if v and k in ('title', 'producer', 'creator', 'creationDate')}
            for i, pg in enumerate(d):
                t = pg.get_text()
                pages.append(t)
                if i == 0:
                    r['img_p1'] = len(pg.get_images())
        except Exception as e:
            r['err'] = 'pdf:' + str(e)[:100]
    elif r['ext'] in ('docx',):
        pages = [docx_text(p)]
    elif r['ext'] in ('csv', 'md', 'htm', 'txt'):
        pages = [open(p, encoding='utf8', errors='ignore').read()]
    # per page stats
    st = []
    for t in pages:
        n = len(t.strip()); dv = len(DEV.findall(t)); la = len(LAT.findall(t)); ew = len(WORD.findall(t))
        st.append((n, dv, la, ew))
    r['chars'] = sum(s[0] for s in st)
    r['empty_pages'] = sum(1 for s in st if s[0] < 40)
    r['dev_chars'] = sum(s[1] for s in st)
    r['lat_chars'] = sum(s[2] for s in st)
    r['eng_words'] = sum(s[3] for s in st)
    # english pages: latin-heavy with real english words
    r['english_pages'] = [i + 1 for i, s in enumerate(st) if s[3] >= 5]
    r['n_english_pages'] = len(r['english_pages'])
    r['english_pages'] = r['english_pages'][:3] + (['…', r['english_pages'][-1]] if len(r['english_pages']) > 3 else [])
    fid = r['sha256'][:16]
    with open(os.path.join(TXT, fid + '.txt'), 'w', encoding='utf-8') as f:
        for i, t in enumerate(pages):
            f.write(f'\n<<<PAGE {i+1}>>>\n'); f.write(t)
    r['txt'] = fid
    return r

if __name__ == '__main__':
    files = []
    for dp, dn, fn in os.walk(BASE):
        if '_logs' in dp: continue
        for f in fn:
            files.append(os.path.join(dp, f))
    files.sort()
    done = set()
    if os.path.exists(os.path.join(OUT, 'files.jsonl')):
        done = {json.loads(l)['rel'] for l in open(os.path.join(OUT, 'files.jsonl'))}
    todo = [f for f in files if os.path.relpath(f, BASE).replace('\\', '/') not in done]
    print(len(files), 'files,', len(todo), 'todo', flush=True)
    with Pool(2) as pool, open(os.path.join(OUT, 'files.jsonl'), 'a') as out:
        for i, r in enumerate(pool.imap_unordered(one, todo, chunksize=4)):
            out.write(json.dumps(r) + '\n'); out.flush()
            if i % 100 == 0: print(i, flush=True)
    print('done')
