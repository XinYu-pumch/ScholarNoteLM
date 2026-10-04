"""Conservative PDF identity evidence; text extraction runs in a killable child.

No OCR or model calls. A missing DOI is not a mismatch. Results describe evidence,
not a guarantee of scientific identity. Unknown files are kept outside pdf/.
"""
import asyncio
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata

POLICY = 'scihub-identity-v1'

def fingerprint(path):
    stat = Path(path).stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]

def norm(text):
    text = html.unescape(text or '').casefold().replace('æ', 'ae').replace('œ', 'oe')
    text = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in text if c.isalnum() and not unicodedata.combining(c))

def classify(text, doi, title='', declared_title=''):
    # Avoid matching a target DOI/title merely cited in the bibliography.
    text = re.split(r'(?im)^\s*(?:references|bibliography|literature cited)\s*$', text)[0]
    body, target = norm(text), norm(title)
    # Preserve DOI punctuation; do not collapse distinct DOIs to one fingerprint.
    doi_text = unicodedata.normalize('NFKC', text).replace('\u00ad', '').casefold()
    wanted = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', doi.strip(), flags=re.I).casefold()
    # Permit line breaks inside a DOI without removing its boundary before the
    # following word (global whitespace removal would reject many valid DOIs).
    pattern = r'(?<![a-z0-9])' + r'\s*'.join(re.escape(c) for c in wanted) + r'(?![a-z0-9/])'
    found = bool(wanted and re.search(pattern, doi_text))
    if found:return {'status': 'match', 'reason': 'doi_in_frontmatter'}
    score = 0.
    if len(target) >= 25:
        grams = {target[n:n+5] for n in range(len(target)-4)}
        score = sum(g in body for g in grams)/len(grams)
        if target in body or score >= .75:
            return {'status': 'match', 'reason': 'title_in_frontmatter', 'titleScore': round(score, 3)}
    if len(body) < 200:return {'status': 'unverifiable', 'reason': 'insufficient_text'}
    # Absence alone is not proof of a wrong article. Require a conflicting
    # front-matter DOI or a usable PDF title as well as very low title overlap.
    other_dois = re.findall(r'10\.\d{4,9}/[^\s<>]+', text[:1200].casefold())
    declared = norm(declared_title)
    declared_conflict = False
    if 12 <= len(declared) <= 300 and not re.search(r'microsoft|untitled|document|acrobat|template', declared):
        declared_grams = {declared[n:n+5] for n in range(len(declared)-4)}
        declared_conflict = sum(g in target for g in declared_grams)/len(declared_grams) < .15
    if len(target) >= 40 and len(body) >= 800 and score < .15 and (other_dois or declared_conflict):
        return {'status': 'mismatch', 'reason': 'conflicting_content', 'titleScore': round(score, 3)}
    return {'status': 'unverifiable', 'reason': 'insufficient_identity_evidence', 'titleScore': round(score, 3)}

def inspect(path, doi, title):
    from pypdf import PdfReader
    from engine import validate_pdf
    before = fingerprint(path)
    try:
        validation = validate_pdf(path)
    except Exception:
        return {'status': 'mismatch', 'reason': 'invalid_pdf', 'fileValid': False, 'policy': POLICY}
    try:
        reader = PdfReader(path, strict=False)
        # Front matter only; a later reference mentioning the target is weak evidence.
        text = '\n'.join((page.extract_text() or '')[:60000] for page in reader.pages[:2])
        result = classify(text, doi, title, str((reader.metadata or {}).get('/Title') or ''))
    except Exception:
        result = {'status': 'unverifiable', 'reason': 'text_extraction_failed'}
    if fingerprint(path) != before:
        return {'status':'unverifiable', 'reason':'staging_changed', 'policy':POLICY}
    result.update(policy=POLICY, fileValid=True, sha256=validation['sha256'], validation=validation, fingerprint=before,
                  identityKey=hashlib.sha256(json.dumps([doi, title], ensure_ascii=False).encode()).hexdigest())
    return result

async def verify(path, doi, title='', timeout=4):
    child = None
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(sys.executable, str(Path(__file__)),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {})))
    try:
        async with asyncio.timeout(timeout):
            child = await asyncio.shield(spawn)
            stdout, _ = await child.communicate(json.dumps([str(path), doi, title, os.getpid()]).encode())
            if child.returncode:return {'status': 'unverifiable', 'reason': 'identity_worker_failed', 'policy': POLICY}
            return json.loads(stdout)
    except TimeoutError:
        return {'status': 'unverifiable', 'reason': 'identity_timeout', 'policy': POLICY}
    except (ValueError, BrokenPipeError, ConnectionResetError):
        return {'status': 'unverifiable', 'reason': 'identity_worker_failed', 'policy': POLICY}
    finally:
        if child is None:child = await spawn
        if child.returncode is None:
            try:child.kill()
            except ProcessLookupError:pass
            await child.wait()

if __name__ == '__main__':
    import threading
    path, doi, title, owner = json.load(sys.stdin)
    def watch_owner():
        from engine import process_alive
        while True:
            if not process_alive(owner):os._exit(1)
            time.sleep(.2)
    threading.Thread(target=watch_owner, daemon=True).start()
    print(json.dumps(inspect(path, doi, title)))
