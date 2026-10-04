"""Sci-Hub DOI normalization and the OPDR Bloom filter, vendored from BADR on 2026-09-19.
No dependency on the BADR installation.
"""
import hashlib, json, mmap, struct

SCIHUB_BLOOM_MAGIC = b"OPDRBF1\n"

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
