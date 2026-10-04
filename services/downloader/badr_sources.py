"""Selected BADR download adapters, vendored on 2026-09-19.
No dependency on the BADR installation. TLS verification is enabled.
Callers download into an isolated staging directory and validate before publishing.
"""
import os, re, time, asyncio, json, mmap, struct, hashlib, logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, quote, urlparse
from pypdf import PdfReader
import httpx
from bs4 import BeautifulSoup
SCIHUB_BLOOM_MAGIC = b"OPDRBF1\n"
logger = logging.getLogger(__name__)
def normalize_pmcid(pmcid: Optional[str]) -> Optional[str]:
    """Normalize a PMCID to the canonical PMC12345 form."""
    clean_pmcid = str(pmcid or "").strip()
    if not clean_pmcid:
        return None
    if clean_pmcid.lower().startswith("pmc"):
        return f"PMC{clean_pmcid[3:]}"
    return f"PMC{clean_pmcid}"

def stringify_repo_version(version: Any) -> str:
    """Convert the repository version to the compact string expected by EuropePMC."""
    if isinstance(version, float) and version.is_integer():
        return str(int(version))
    if isinstance(version, int):
        return str(version)
    if isinstance(version, str):
        return version.strip() or "1"
    return "1"

def score_europepmc_repo_pdf_file(item: Dict[str, Any]) -> int:
    """Prefer likely article PDFs over proof, supplementary, or review artifacts."""
    filename = str(item.get("filename") or item.get("fileName") or "").strip().lower()
    stem = filename[:-4] if filename.endswith(".pdf") else filename
    tokens = {token for token in re.split(r"[^a-z0-9]+", stem) if token}

    score = 0
    if filename == "main.pdf":
        score += 100
    if "main" in tokens:
        score += 40
    if "article" in tokens or "manuscript" in tokens:
        score += 15
    if "nihms" in tokens or stem.startswith("nihms"):
        score += 8

    penalties = {
        "supp": 60,
        "supplement": 80,
        "supplementary": 80,
        "appendix": 60,
        "table": 40,
        "tables": 40,
        "figure": 40,
        "figures": 40,
        "proof": 50,
        "prf": 50,
        "coif": 45,
        "rc": 35,
        "author": 20,
        "authors": 20,
        "response": 30,
        "reply": 30,
        "rebuttal": 30,
        "checklist": 30,
        "reporting": 25,
        "cover": 20,
    }
    for token, penalty in penalties.items():
        if token in tokens:
            score -= penalty

    if item.get("url"):
        score += 3
    return score

def extract_ranked_europepmc_repo_pdf_files(fulltext_repo_metadata: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return PDF file metadata sorted so the main article is tried before supplements/proofs."""
    if not fulltext_repo_metadata:
        return []

    files = fulltext_repo_metadata.get("files") or []
    if isinstance(files, dict):
        files = [files]

    ranked_files = []
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or item.get("fileName") or "").strip()
        mime_type = str(item.get("mimeType") or "").strip()
        file_type = str(item.get("type") or "").strip().lower()
        if file_type != "pdf" and "pdf" not in mime_type.lower() and not filename.lower().endswith(".pdf"):
            continue
        if score_europepmc_repo_pdf_file(item) >= 0:
            ranked_files.append((score_europepmc_repo_pdf_file(item), len(filename), index, item))

    ranked_files.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    return [item for _, _, _, item in ranked_files]

def append_unique_url(candidates: List[str], seen: set, url: Optional[str]):
    if not url:
        return
    clean_url = str(url).strip()
    if not clean_url or clean_url in seen:
        return
    seen.add(clean_url)
    candidates.append(clean_url)

def europepmc_endpoint_label(url: Optional[str]) -> str:
    url = str(url or "").lower()
    if "api/getpdf" in url:
        return "render_getPdf"
    if "fulltextrepo" in url:
        return "fulltextRepo"
    if "api/epmc/files" in url:
        return "ncbi_epmc_files"
    if "ptpmcrender.fcgi" in url:
        return "backend_render"
    if "pdf=render" in url:
        return "render_page"
    return "other"

def new_pmc_attempt_profile() -> Dict[str, Any]:
    return {
        "status_events": [],
        "error_events": [],
        "metadata_events": [],
    }

def record_pmc_status_event(profile: Optional[Dict[str, Any]], url: str, status_code: int) -> None:
    if profile is None:
        return
    profile.setdefault("status_events", []).append({
        "endpoint": europepmc_endpoint_label(url),
        "status": int(status_code),
    })

def record_pmc_error_event(profile: Optional[Dict[str, Any]], url: str, error_type: str) -> None:
    if profile is None:
        return
    profile.setdefault("error_events", []).append({
        "endpoint": europepmc_endpoint_label(url),
        "error_type": str(error_type or "unknown"),
    })

def record_pmc_metadata_event(profile: Optional[Dict[str, Any]], record: Optional[Dict[str, Any]]) -> None:
    if profile is None or not record:
        return
    profile.setdefault("metadata_events", []).append({
        "pmcid": record.get("pmcid"),
        "hasPDF": record.get("hasPDF"),
        "inPMC": record.get("inPMC"),
    })

def summarize_pmc_attempt_profile(profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    profile = profile or {}
    status_counts: Dict[str, int] = {}
    error_counts: Dict[str, int] = {}
    for event in profile.get("status_events", []):
        key = f"{event.get('endpoint', 'other')}:{event.get('status')}"
        status_counts[key] = status_counts.get(key, 0) + 1
    for event in profile.get("error_events", []):
        key = f"{event.get('endpoint', 'other')}:{event.get('error_type', 'unknown')}"
        error_counts[key] = error_counts.get(key, 0) + 1
    return {
        "status_counts": status_counts,
        "error_counts": error_counts,
        "metadata_events": profile.get("metadata_events", []),
        "has_render_getpdf_429": status_counts.get("render_getPdf:429", 0) > 0,
    }

def is_slow_rescue_retryable_profile(
    record: Optional[Dict[str, Any]],
    profile_summary: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
    if not record:
        return False, "missing_europepmc_metadata"
    has_pdf = str(record.get("hasPDF") or "").upper() == "Y"
    in_pmc = str(record.get("inPMC") or "").upper() == "Y"
    if not has_pdf or not in_pmc:
        return False, (
            f"requires_hasPDF_Y_inPMC_Y_got_hasPDF_{record.get('hasPDF', 'N/A')}"
            f"_inPMC_{record.get('inPMC', 'N/A')}"
        )
    if not profile_summary:
        return False, "missing_previous_pmc_failure_profile"
    if not profile_summary.get("has_render_getpdf_429"):
        return False, "requires_previous_render_getPdf_429"
    return True, "hasPDF_Y_inPMC_Y_with_previous_render_getPdf_429"

def build_europepmc_repo_pdf_candidates(
    pmcid: Optional[str], fulltext_repo_metadata: Optional[Dict[str, Any]]
) -> List[str]:
    """Build only the repository-backed PDF candidates used by the browser Open PDF flow."""
    normalized_pmcid = normalize_pmcid(pmcid)
    candidates: List[str] = []
    seen = set()
    repo_version = stringify_repo_version((fulltext_repo_metadata or {}).get("version", 1))

    for item in extract_ranked_europepmc_repo_pdf_files(fulltext_repo_metadata):
        filename = str(item.get("filename") or item.get("fileName") or "").strip()
        mime_type = str(item.get("mimeType") or "").strip()
        direct_url = item.get("url")
        if normalized_pmcid and filename:
            append_unique_url(
                candidates,
                seen,
                "https://europepmc.org/api/fulltextRepo?"
                + urlencode(
                    {
                        "pmcId": normalized_pmcid,
                        "type": "FILE",
                        "fileName": filename,
                        "mimeType": mime_type or "application/pdf",
                        "version": repo_version,
                        "pmc_pageType": "pdf",
                        "pmc_domain": "null",
                    }
                ),
            )
        append_unique_url(candidates, seen, direct_url)

    return candidates

async def fetch_europepmc_record(
    pmid: Optional[str],
    pmcid: Optional[str],
    log_callback=None,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[Dict[str, Any]]:
    """通过 EuropePMC REST 获取文章元数据，用于解析更稳妥的 PDF 下载地址。"""
    queries = []
    if pmid:
        queries.append(f"EXT_ID:{pmid} AND SRC:MED")
    normalized_pmcid = normalize_pmcid(pmcid)
    if normalized_pmcid:
        queries.append(f"PMCID:{normalized_pmcid}")

    if not queries:
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    owned_client = client is None
    if owned_client:
        client = httpx.AsyncClient(timeout=20.0, verify=True, follow_redirects=True)

    try:
        for query in queries:
            try:
                if log_callback:
                    log_callback(f"PMID {pmid or 'N/A'}: EuropePMC metadata query -> {query}")
                resp = await client.get(
                    "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                    params={"query": query, "format": "json", "resultType": "core", "pageSize": 1},
                    headers=headers,
                    timeout=20.0,
                )
                resp.raise_for_status()
                results = resp.json().get("resultList", {}).get("result", [])
                if results:
                    record = results[0]
                    if log_callback:
                        log_callback(
                            f"PMID {pmid or record.get('pmid', 'N/A')}: EuropePMC resolved "
                            f"pmcid={record.get('pmcid', 'N/A')} hasPDF={record.get('hasPDF', 'N/A')} "
                            f"inPMC={record.get('inPMC', 'N/A')}"
                        )
                    return record
                if log_callback:
                    log_callback(f"PMID {pmid or 'N/A'}: EuropePMC metadata query returned no results")
            except Exception as e:
                if log_callback:
                    log_callback(f"PMID {pmid or 'N/A'}: EuropePMC metadata query failed - {type(e).__name__}: {e}")
        return None
    finally:
        if owned_client and client is not None:
            await client.aclose()

async def fetch_europepmc_fulltext_repo_metadata(
    pmcid: Optional[str],
    pmid: Optional[str] = None,
    log_callback=None,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[Dict[str, Any]]:
    """Query the EuropePMC fulltext repository metadata used by the browser Open PDF flow."""
    normalized_pmcid = normalize_pmcid(pmcid)
    if not normalized_pmcid:
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    owned_client = client is None
    if owned_client:
        client = httpx.AsyncClient(timeout=20.0, verify=True, follow_redirects=True)

    try:
        if log_callback:
            log_callback(f"PMID {pmid or 'N/A'}: EuropePMC fulltextRepo metadata query -> {normalized_pmcid}")

        resp = await client.get(
            "https://europepmc.org/api/fulltextRepo",
            params={"pmcId": normalized_pmcid, "type": "METADATA"},
            headers=headers,
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success", True):
            if log_callback:
                log_callback(f"PMID {pmid or 'N/A'}: EuropePMC fulltextRepo metadata returned success=false")
            return None

        pdf_names = [
            str(item.get("filename") or item.get("fileName") or "").strip()
            for item in extract_ranked_europepmc_repo_pdf_files(data)
        ]

        if log_callback:
            if pdf_names:
                preview = ", ".join(pdf_names[:3])
                suffix = " ..." if len(pdf_names) > 3 else ""
                log_callback(
                    f"PMID {pmid or data.get('pmid', 'N/A')}: EuropePMC fulltextRepo found "
                    f"{len(pdf_names)} PDF file(s): {preview}{suffix}"
                )
            else:
                log_callback(f"PMID {pmid or data.get('pmid', 'N/A')}: EuropePMC fulltextRepo found no PDF files")

        return data
    except Exception as e:
        if log_callback:
            log_callback(f"PMID {pmid or 'N/A'}: EuropePMC fulltextRepo metadata query failed - {type(e).__name__}: {e}")
        return None
    finally:
        if owned_client and client is not None:
            await client.aclose()

def build_europepmc_pdf_candidates(
    paper: Dict,
    epmc_record: Optional[Dict[str, Any]],
    fulltext_repo_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], List[str]]:
    """构造 EuropePMC PDF 候选链接，优先使用真实浏览器走的 fulltextRepo 链路。"""
    pmcid = normalize_pmcid(paper.get("pmcid"))
    if epmc_record and epmc_record.get("pmcid"):
        pmcid = normalize_pmcid(epmc_record["pmcid"])

    candidates: List[str] = []
    seen = set()

    for url in build_europepmc_repo_pdf_candidates(pmcid, fulltext_repo_metadata):
        append_unique_url(candidates, seen, url)

    fulltext_urls = []
    if epmc_record:
        fulltext_urls = epmc_record.get("fullTextUrlList", {}).get("fullTextUrl", [])
        if isinstance(fulltext_urls, dict):
            fulltext_urls = [fulltext_urls]

    europepmc_pdf_urls = []
    external_pdf_urls = []
    for item in fulltext_urls:
        if not isinstance(item, dict):
            continue
        if item.get("availabilityCode") != "OA" or item.get("documentStyle") != "pdf":
            continue
        if item.get("site") == "Europe_PMC":
            europepmc_pdf_urls.append(item.get("url"))
        else:
            external_pdf_urls.append(item.get("url"))

    for url in europepmc_pdf_urls:
        append_unique_url(candidates, seen, url)
    for url in external_pdf_urls:
        append_unique_url(candidates, seen, url)
    if pmcid:
        append_unique_url(candidates, seen, f"https://europepmc.org/articles/{pmcid}?pdf=render")
        append_unique_url(candidates, seen, f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf")

    return pmcid or None, candidates

async def try_europepmc_candidate_urls(
    pmid: str,
    candidate_urls: List[str],
    pdf_path: str,
    md_path: str,
    client: httpx.AsyncClient,
    log_callback,
    tried_urls: Optional[set] = None,
    attempt_profile: Optional[Dict[str, Any]] = None,
) -> bool:
    """Attempt candidate URLs in order and stop on the first valid PDF."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    max_attempts = 2
    tried_urls = tried_urls if tried_urls is not None else set()
    pending_urls = [url for url in candidate_urls if url not in tried_urls]

    for url_index, url in enumerate(pending_urls, start=1):
        tried_urls.add(url)
        for attempt in range(1, max_attempts + 1):
            if log_callback:
                log_callback(
                    f"PMID {pmid}: EuropePMC try {url_index}/{len(pending_urls)} "
                    f"(attempt {attempt}/{max_attempts}) -> {url}"
                )

            total_bytes = 0
            first_bytes = b""
            start_time = time.time()

            try:
                async with client.stream("GET", url, headers=headers, timeout=60.0, follow_redirects=True) as response:
                    final_url = str(response.url)
                    content_type = response.headers.get("content-type", "")
                    content_length = response.headers.get("content-length", "unknown")
                    if log_callback:
                        log_callback(
                            f"PMID {pmid}: response status={response.status_code} "
                            f"type={content_type or 'N/A'} len={content_length} final={final_url}"
                        )
                    record_pmc_status_event(attempt_profile, final_url, response.status_code)

                    if response.status_code != 200:
                        continue

                    with open(pdf_path, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            if not first_bytes and chunk:
                                first_bytes = chunk[:16]
                            f.write(chunk)
                            total_bytes += len(chunk)
                            if total_bytes > 250 * 1024 * 1024:
                                raise ValueError("PDF 超过 250 MB")

                elapsed = time.time() - start_time
                pdf_signature = b"%PDF" in first_bytes[:16]
                looks_like_pdf = (
                    "pdf" in content_type.lower()
                    or pdf_signature
                    or final_url.lower().endswith(".pdf")
                    or "pdf=render" in final_url.lower()
                    or "fulltextrepo" in final_url.lower()
                )

                if total_bytes < 1000:
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)
                    if log_callback:
                        log_callback(f"PMID {pmid}: downloaded file too small ({total_bytes} bytes), retrying next URL")
                    continue

                if not pdf_signature:
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)
                    if log_callback:
                        prefix = first_bytes[:16].hex() if first_bytes else "empty"
                        log_callback(
                            f"PMID {pmid}: response does not look like PDF "
                            f"(type={content_type or 'N/A'}, first16={prefix}), retrying next URL"
                        )
                    continue

                reader = PdfReader(pdf_path, strict=False)
                if reader.is_encrypted or not len(reader.pages):
                    raise ValueError("PDF 无法读取")
                if attempt_profile is not None:
                    attempt_profile["download_url"] = final_url
                kb_size = total_bytes / 1024
                speed = kb_size / elapsed if elapsed > 0 else 0
                if os.path.exists(md_path):
                    try:
                        os.remove(md_path)
                        if log_callback:
                            log_callback(f"PMID {pmid}: removed stale fallback MD after successful PMC download")
                    except Exception:
                        pass
                if log_callback:
                    log_callback(
                        f"PMID {pmid}: PDF (PMC) | {kb_size:.0f}KB | {speed:.0f}KB/s | {elapsed:.1f}s | {final_url}"
                    )
                return True

            except Exception as e:
                if os.path.exists(pdf_path):
                    try:
                        os.remove(pdf_path)
                    except Exception:
                        pass
                if log_callback:
                    log_callback(
                        f"PMID {pmid}: EuropePMC request failed on attempt {attempt}/{max_attempts} "
                        f"- {type(e).__name__}: {e}"
                    )
                record_pmc_error_event(attempt_profile, url, type(e).__name__)

    return False

async def download_from_europepmc(
    paper: Dict,
    save_dir: str,
    log_callback,
    attempt_profile: Optional[Dict[str, Any]] = None,
) -> bool:
    """从 EuropePMC 下载 PMC 文献 PDF，优先走 REST 解析到的官方 PDF 地址。"""
    pmid = paper["pmid"]
    pdf_path = os.path.join(save_dir, f"{pmid}.pdf")
    md_path = os.path.join(save_dir, f"{pmid}.md")

    if os.path.exists(pdf_path):
        if log_callback:
            log_callback(f"PMID {pmid}: PMC download skipped, existing PDF found")
        return True

    source_pmcid = normalize_pmcid(paper.get("pmcid"))
    if log_callback:
        log_callback(f"PMID {pmid}: starting EuropePMC download (xml_pmcid={source_pmcid or 'N/A'})")

    fulltext_repo_metadata = None
    epmc_record = None
    resolved_pmcid = source_pmcid
    tried_urls = set()

    async with httpx.AsyncClient(timeout=60.0, verify=True, follow_redirects=True) as client:
        if source_pmcid:
            fulltext_repo_metadata = await fetch_europepmc_fulltext_repo_metadata(
                source_pmcid, pmid, log_callback, client=client
            )
            fast_candidates = build_europepmc_repo_pdf_candidates(source_pmcid, fulltext_repo_metadata)
            if log_callback:
                log_callback(f"PMID {pmid}: resolved EuropePMC pmcid={source_pmcid}")
            if fast_candidates:
                if await try_europepmc_candidate_urls(
                    pmid,
                    fast_candidates,
                    pdf_path,
                    md_path,
                    client,
                    log_callback,
                    tried_urls=tried_urls,
                    attempt_profile=attempt_profile,
                ):
                    return True
                if log_callback:
                    log_callback(f"PMID {pmid}: fulltextRepo fast path exhausted, loading REST fallback")
            elif log_callback:
                log_callback(f"PMID {pmid}: no fast PMC candidates from fulltextRepo, loading REST fallback")

        epmc_record = await fetch_europepmc_record(pmid, source_pmcid, log_callback, client=client)
        record_pmc_metadata_event(attempt_profile, epmc_record)
        resolved_pmcid = normalize_pmcid((epmc_record or {}).get("pmcid")) or source_pmcid
        if resolved_pmcid and (fulltext_repo_metadata is None or resolved_pmcid != source_pmcid):
            fulltext_repo_metadata = await fetch_europepmc_fulltext_repo_metadata(
                resolved_pmcid, pmid, log_callback, client=client
            )

        resolved_pmcid, candidate_urls = build_europepmc_pdf_candidates(paper, epmc_record, fulltext_repo_metadata)

        if log_callback:
            log_callback(f"PMID {pmid}: resolved EuropePMC pmcid={resolved_pmcid or 'N/A'}")

        if not candidate_urls:
            if log_callback:
                log_callback(f"PMID {pmid}: no EuropePMC PDF candidates found")
            return False

        if await try_europepmc_candidate_urls(
            pmid,
            candidate_urls,
            pdf_path,
            md_path,
            client,
            log_callback,
            tried_urls=tried_urls,
            attempt_profile=attempt_profile,
        ):
            return True

    if log_callback:
        log_callback(f"PMID {pmid}: all EuropePMC candidates failed")
    return False

def normalize_doi_for_scihub(doi: str) -> str:
    doi = (doi or "").strip().lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi.org/",
        "dx.doi.org/",
        "doi:",
    ):
        if doi.startswith(prefix):
            return doi[len(prefix):].strip()
    return doi

def scihub_bloom_hash_positions(doi: bytes, bit_count: int, hash_count: int):
    digest = hashlib.blake2b(doi, digest_size=16, person=b"OPDRSciHubDOI").digest()
    h1, h2 = struct.unpack("<QQ", digest)
    h2 |= 1
    for i in range(hash_count):
        yield (h1 + i * h2) % bit_count

class SciHubBloomFilter:
    def __init__(self, path: str):
        self.path = path
        self._file = open(path, "rb")
        magic = self._file.read(len(SCIHUB_BLOOM_MAGIC))
        if magic != SCIHUB_BLOOM_MAGIC:
            self._file.close()
            raise ValueError("not an OPDR Sci-Hub Bloom filter file")
        header_len = struct.unpack(">I", self._file.read(4))[0]
        self.header = json.loads(self._file.read(header_len).decode("utf-8"))
        self.offset = len(SCIHUB_BLOOM_MAGIC) + 4 + header_len
        self.mm = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)

    def contains(self, doi: str) -> bool:
        normalized = normalize_doi_for_scihub(doi).encode("utf-8")
        if not normalized:
            return False
        bit_count = int(self.header["bit_count"])
        hash_count = int(self.header["hash_count"])
        for pos in scihub_bloom_hash_positions(normalized, bit_count, hash_count):
            if not (self.mm[self.offset + (pos >> 3)] & (1 << (pos & 7))):
                return False
        return True

    def close(self) -> None:
        self.mm.close()
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

def mirror_label(mirror: str) -> str:
    host = re.sub(r"^https?://", "", mirror).split("/")[0]
    parts = host.split(".")
    return parts[-1] if parts else host

async def download_scihub_with_locked_mirrors(doi, save_path, mirrors, mirror_locks, log_callback):
    """Legacy callable retained; delegates to the production browser implementation."""
    from pathlib import Path
    import scihub_retry
    from engine import validate_pdf
    health=scihub_retry.MirrorHealth()
    # Reuse callers' existing in-process entry locks; normal app calls additionally
    # supply its cross-project lock directory through source_scihub.
    original_lock=health.lock
    health.lock=lambda role,url:mirror_locks.setdefault(url,asyncio.Lock()) if role=='entry' else original_lock(role,url)
    info,timings,_=await scihub_retry.download(normalize_doi_for_scihub(doi),Path(save_path),mirrors,health,
        lambda message,**extra:log_callback(message) if log_callback else None,validate_pdf,
        budget={'network':0.,'wait':0.,'networkLimit':75.,'waitLimit':30.})
    if not info:return None,0,0,None
    elapsed=timings['lookupSeconds']+timings['downloadSeconds'];size=Path(save_path).stat().st_size/1024
    return f"PDF ({info['source']}) | Playwright Chromium",size,size/max(.001,elapsed),mirror_label(info['mirror']),info['url']
