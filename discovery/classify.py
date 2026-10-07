import sys, os
OUTDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join('discovery', 'out')
import json, re, collections
F = json.load(open(os.path.join(OUTDIR, 'features.json')))

def cls(f):
    fn = f['fname'].lower(); fo = f['folder']
    if fo.startswith('28'): return 'FORM_TEMPLATE'
    if fo.startswith('11'): return 'TAP_CHAPTER' if 'amendment_record' not in fn else 'TAP_AMENDMENT_RECORD'
    if fo.startswith('17'): return 'APPROVAL_LIST'
    if fo.startswith('21'): return 'BIS_REGULATION'
    if fo.startswith('27'): return 'REPORT'
    if fo.startswith('12'): return 'GUIDANCE_BOOKLET'
    isais = fo.startswith('07') or (re.search(r'\bais[\s\-_]*\d{3}', fn) and not f['ids_head'])
    if isais:
        if 'draft' in fn: return 'AIS_DRAFT'
        if f['ais_amend_hdrs'] or 'amend' in fn: return 'AIS_CONSOLIDATED' if f['pages'] > 15 else 'AIS_AMENDMENT'
        if 'corrigendum' in fn: return 'AIS_CORRIGENDUM'
        return 'AIS_STANDARD'
    if f['scan'] and not f['ids_head']: return 'SCANNED_UNKNOWN'
    if f['corrigendum'] and f['pages'] <= 4 and f['ids_head']: return 'CORRIGENDUM'
    if f['ids_head'] or f['gazette_hdr'] >= 2:
        if f['draft'] and not f['cites_draft']: return 'NOTIFICATION_DRAFT'
        return 'NOTIFICATION_FINAL'
    if re.search(r'\b(act|ordinance)\b', fn) and f['pages'] > 20: return 'ACT'
    if f['pages'] > 60 and f['cmvr'] > 20 and re.search(r'rules', fn): return 'CONSOLIDATED_RULES'
    if f['om'] or 'circular' in fn or 'advisory' in fn or 'order' in fn: return 'CIRCULAR_OM'
    if 'guideline' in fn or 'policy' in fn or 'sop' in fn: return 'GUIDELINE_POLICY'
    if 'report' in fn: return 'REPORT'
    return 'OTHER'

for f in F: f['class'] = cls(f)
json.dump(F, open(os.path.join(OUTDIR, 'features.json'), 'w'))
c = collections.Counter((f['folder'][:2], f['class']) for f in F)
for k, v in sorted(c.items()): print(k, v)
print(collections.Counter(f['class'] for f in F).most_common())
