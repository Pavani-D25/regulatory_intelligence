import sys, os
OUTDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join('discovery', 'out')
import json, re, collections, os
TXT = os.path.join(OUTDIR, 'text') + os.sep
R = [json.loads(l) for l in open(os.path.join(OUTDIR, 'files.jsonl'))]

def text(r, maxc=None):
    t = open(TXT + r['txt'] + '.txt', encoding='utf-8', errors='ignore').read()
    return t[:maxc] if maxc else t

NUM = r'(G\.?\s?S\.?\s?R\.?|S\.?\s?O\.?)\s*(?:No\.?\s*)?(\d{1,5})\s*\(\s*E\s*\)'
P = {
 'gsr_so': re.compile(NUM, re.I),
 'gazette_hdr': re.compile(r'(EXTRAORDINARY|असाधारण|Gazette of India|PART\s+II\s*[-—–]?\s*Sec(?:tion)?\.?\s*3)', re.I),
 'part_sec': re.compile(r'PART\s+II\s*[-—–]?\s*Sec(?:tion)?\.?\s*3\s*[-—–]?\s*(?:Sub[-\s]?Sec(?:tion)?\.?\s*)?\(?\s*(i{1,3})\s*\)?', re.I),
 'draft': re.compile(r'(draft (?:of )?(?:certain )?(?:rules|notification|amendment)|objections? (?:and|or) suggestions?|after the expiry of (?:a )?period of (?:thirty|forty[- ]five|\d+) days)', re.I),
 'final_of_draft': re.compile(r'(?:draft rules|draft notification).{0,200}?(?:published|vide).{0,120}?' + NUM, re.I | re.S),
 'short_title': re.compile(r'Central Motor Vehicles\s*\(\s*([A-Za-z\- ]+?)\s+Amendment\s*\)\s*Rules,?\s*(\d{4})', re.I),
 'file_no': re.compile(r'\[?\s*F(?:ile)?\.?\s*No\.?\s*([A-Z][A-Z0-9\-/\.\(\) ]{4,40}?\d{2,4})', re.I),
 'om': re.compile(r'Office Memorandum|O\.\s?M\.', re.I),
 'circular': re.compile(r'\b(circular|advisory|guidelines|order)\b', re.I),
 'corrigendum': re.compile(r'\bcorrigendum\b', re.I),
 'so1365': re.compile(r'S\.?\s?O\.?\s*1365\s*\(\s*E\s*\)', re.I),
 'rule124': re.compile(r'rule\s*124', re.I),
 'cmvr': re.compile(r'Central Motor Vehicles? Rules', re.I),
 'mv_act': re.compile(r'Motor Vehicles Act', re.I),
 'ais_ref': re.compile(r'\bAIS[\s\-:]*(\d{3})', re.I),
 'is_ref': re.compile(r'\bIS[\s:]*(\d{2,5})(?:\s*[:\-]\s*(\d{4}))?\b'),
 'unr_ref': re.compile(r'\b(?:UN\s*R|ECE\s*R(?:egulation)?|UN\s*Regulation\s*No\.?)\s*(\d{1,3})', re.I),
 'rule_ref': re.compile(r'\brule\s+(\d{1,3}[A-Z]{0,2})', re.I),
 'cat': re.compile(r'\b(L[1-7](?:-?[A-Z])?|M[1-3]|N[1-3]|T[1-5]|O[1-4]|E-?rickshaw|E-?cart|quadricycle|two[\s-]wheelers?|three[\s-]wheelers?|four[\s-]wheelers?|motor ?cycles?|scooters?|mopeds?|cars?|buses?|trucks?|agricultural tractors?|trailers?|ambulances?|caravans?)\b', re.I),
 'powertrain': re.compile(r'\b(battery operated|electric vehicles?|BEV|HEV|hybrid|CNG|LPG|diesel|petrol|gasoline|flex[\s-]?fuel|ethanol|E\d{2,3}\b|bio[\s-]?diesel|hydrogen|fuel cell|methanol|LNG)\b', re.I),
 'cond_cc': re.compile(r'(\d{2,4})\s*(?:cc|cubic centimet)', re.I),
 'cond_kw': re.compile(r'(\d+(?:\.\d+)?)\s*kW', re.I),
 'cond_gvw': re.compile(r'(?:GVW|gross vehicle weight)[^.]{0,60}?(\d[\d,\.]*)\s*(kg|tonnes?|t)\b', re.I),
 'cond_seat': re.compile(r'(?:more than|not more than|exceeding|upto|up to)\s+(\w+)\s+(?:seats|passengers)', re.I),
 'cond_speed': re.compile(r'(\d{2,3})\s*km\s*/?\s*h', re.I),
 'date_words': re.compile(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:day of\s+)?(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})', re.I),
 'impl_phrase': re.compile(r'(on and (?:from|after)|with effect from|shall come into force|come into force on|manufactured on or after|new models?|existing models?)', re.I),
 'ais_amend_hdr': re.compile(r'Amendment\s*No\.?\s*(\d+)\s*\(?\s*(\d{1,2})\s*/\s*(\d{4})\s*\)?\s*\n?\s*To\s+AIS', re.I),
 'ais_code_cover': re.compile(r'AIS[\s\-]*(\d{3})\s*(\(Part\s*\d+\))?\s*(\(Rev\.?\s*\d*\))?', re.I),
 'ais_rev_impl': re.compile(r'(re-?approval|type approval .{0,40}(?:invalid|shall not be valid))', re.I),
 'hindi_legacy': re.compile(r'(Hkkjr|vlk/kkj\.k|jkti=k|ea=ky;|vf/klwpuk|izkf/kdkj)'),  # Kruti Dev mojibake
 'english_hdr': re.compile(r'MINISTRY OF ROAD TRANSPORT|MINISTRY OF SHIPPING, ROAD TRANSPORT|Ministry of Road Transport', re.I),
 'ministry': re.compile(r'MINISTRY OF ([A-Z ,&]{4,60})', re.I),
 'tap_chapter': re.compile(r'MoRTH\s*/\s*CMVR\s*/\s*TAP[\s\-]*115\s*/\s*116', re.I),
 'form': re.compile(r'\bFORM\s*(?:No\.?\s*)?(\d{1,2}[A-Z]?)\b'),
}
AUTO = re.compile(r'motor vehicle|automotive|vehicle|AIS|CMVR|road transport', re.I)

out = []
for r in R:
    if r['ext'] not in ('pdf', 'docx', 'doc', 'htm'):
        continue
    t = text(r)
    head = t[:6000]
    f = {'rel': r['rel'], 'folder': r['folder'], 'sha': r['sha256'], 'pages': r.get('pages', 1),
         'chars': r['chars'], 'eng_pages': r['n_english_pages'],
         'scan': bool(r.get('pages')) and r['chars'] / max(r['pages'], 1) < 100}
    for k in ('gsr_so',):
        f['ids_head'] = list(dict.fromkeys(f"{'GSR' if 'G' in m.group(1).upper() else 'SO'} {m.group(2)}(E)" for m in P['gsr_so'].finditer(head)))[:6]
        f['ids_all_n'] = len(set(m.group(2) for m in P['gsr_so'].finditer(t)))
    for k in ('gazette_hdr', 'draft', 'om', 'corrigendum', 'so1365', 'rule124', 'cmvr', 'mv_act', 'tap_chapter', 'hindi_legacy', 'english_hdr', 'ais_rev_impl', 'impl_phrase'):
        f[k] = len(P[k].findall(t))
    m = P['part_sec'].search(t); f['part_sec'] = m.group(1).lower() if m else None
    f['short_titles'] = list(dict.fromkeys(f"{a.strip()} {b}" for a, b in P['short_title'].findall(t)))[:4]
    f['file_no'] = list(dict.fromkeys(x.strip() for x in P['file_no'].findall(t)))[:3]
    fd = P['final_of_draft'].search(t); f['cites_draft'] = fd.group(0)[-40:] if fd else None
    f['ais_refs'] = collections.Counter('AIS-' + x for x in P['ais_ref'].findall(t)).most_common(15)
    f['is_refs'] = len(set(P['is_ref'].findall(t)))
    f['unr_refs'] = sorted(set(P['unr_ref'].findall(t)))[:20]
    f['rule_refs'] = collections.Counter(P['rule_ref'].findall(t)).most_common(10)
    f['cats'] = collections.Counter(x.upper().replace(' ', '-').rstrip('S') for x in P['cat'].findall(t)).most_common(15)
    f['powertrain'] = collections.Counter(x.lower() for x in P['powertrain'].findall(t)).most_common(8)
    f['cond'] = {k: P['cond_' + k].findall(t)[:5] for k in ('cc', 'kw', 'gvw', 'seat', 'speed')}
    f['dates_head'] = [' '.join(d) for d in P['date_words'].findall(head)][:5]
    f['n_dates'] = len(P['date_words'].findall(t))
    f['ais_amend_hdrs'] = [f"{a}({b}/{c})" for a, b, c in P['ais_amend_hdr'].findall(t)]
    f['ministry'] = list(dict.fromkeys(x.strip().upper() for x in P['ministry'].findall(head)))[:3]
    f['forms'] = len(set(P['form'].findall(t)))
    f['auto_hits'] = len(AUTO.findall(t[:20000]))
    f['fname'] = os.path.basename(r['rel'])
    out.append(f)
json.dump(out, open(os.path.join(OUTDIR, 'features.json'), 'w'))
print(len(out))
