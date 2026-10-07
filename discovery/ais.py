import sys, os
OUTDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join('discovery', 'out')
import json,re,collections
F=json.load(open(os.path.join(OUTDIR,'features.json')))
def T(f): return open(os.path.join(OUTDIR,'text')+os.sep+f['sha'][:16]+'.txt',encoding='utf-8', errors='ignore').read()
AH=re.compile(r'AMENDMENT\s*No\.?\s*(\d+)\b(.{0,80}?)\bTO\b\s*AIS[\s\-:]*(\d{3})',re.I|re.S)
CH=re.compile(r'CORRIGENDUM\s*(?:No\.?\s*(\d+))?\b(.{0,80}?)\bTO\b\s*AIS[\s\-:]*(\d{3})',re.I|re.S)
COVER=re.compile(r'AUTOMOTIVE\s+INDUSTRY\s+STANDARD',re.I)
CODE=re.compile(r'AIS[\s\-:]*(\d{3})\s*(\(\s*Part\s*\d+\s*\))?\s*(?:\(\s*Rev\.?\s*(\d*)\s*\))?',re.I)
DRAFT=re.compile(r'\bDRAFT\b')
STATUS=re.compile(r'Status chart of the standard',re.I)
TRANS=re.compile(r'transitional provisions?',re.I)
SCOPE=re.compile(r'\n\s*1\.?0?\s*\n?\s*SCOPE',re.I)
DATEW=re.compile(r'(\d{1,2}(?:st|nd|rd|th)?\s+[A-Z][a-z]+,?\s+\d{4}|[A-Z][a-z]+,?\s+\d{4}|\d{1,2}\s*/\s*\d{4})')
res=[]
for f in F:
    t=T(f); p1=t[:8000]
    isais = f['folder'].startswith('07') or (COVER.search(p1) and CODE.search(p1))
    if not isais: continue
    ams=[(int(a),re.sub(r'\s+',' ',b).strip()[:30],c) for a,b,c in AH.findall(t)]
    cos=[(a,re.sub(r'\s+',' ',b).strip()[:30],c) for a,b,c in CH.findall(t)]
    m=CODE.search(p1)
    res.append(dict(fname=f['fname'],folder=f['folder'][:2],sha=f['sha'],pages=f['pages'],code=m.group(1) if m else None,
      part=m.group(2) if m else None,rev=m.group(3) if m else None,amend=ams,corr=cos,draft=bool(DRAFT.search(t[:3000])),
      status_chart=bool(STATUS.search(t)),transitional=bool(TRANS.search(t)),scope=bool(SCOPE.search(t)),
      cover=bool(COVER.search(p1)), eng=f['eng_pages'], scan=f['scan'], ais_refs=f['ais_refs'][:6], cats=f['cats'][:8], unr=f['unr_refs'], is_n=f['is_refs']))
json.dump(res,open(os.path.join(OUTDIR,'ais.json'),'w'))
print(len(res), collections.Counter(r['folder'] for r in res))
n_am=[r for r in res if r['amend']]; print('files with amendment headers',len(n_am))
print('amend date formats sample',[a[1] for r in n_am[:15] for a in r['amend'][:1]])
print('max amendments in one file',max(len({a[0] for a in r['amend']}) for r in n_am), [ (r['fname'],len({a[0] for a in r['amend']})) for r in sorted(n_am,key=lambda r:-len({a[0] for a in r['amend']}))[:5]])
print('corrigenda files',sum(1 for r in res if r['corr']))
print('status chart',sum(r['status_chart'] for r in res),'transitional',sum(r['transitional'] for r in res),'scope',sum(r['scope'] for r in res),'cover',sum(r['cover'] for r in res))
print('rev',collections.Counter(r['rev'] is not None for r in res),'part',sum(1 for r in res if r['part']))
codes=collections.Counter(r['code'] for r in res if r['folder']=='07'); print('distinct AIS codes in 07',len(codes), 'codes with >1 file',sum(1 for v in codes.values() if v>1))
print('draft-marked',[r['fname'] for r in res if r['draft']][:10])
print('06 AIS files',sum(1 for r in res if r['folder']=='06'),'of which sha in 07',sum(1 for r in res if r['folder']=='06' and r['sha'] in {x['sha'] for x in res if x['folder']=='07'}))
