"""Pure exact-base UTF-8 byte patches; no filesystem or authority changes."""
import hashlib
import re
from .storage import LoopError, digest


def bytes_pin(content, executable=False):
    return digest({'content': hashlib.sha256(content).hexdigest(), 'executable': bool(executable)})


def materialize_patch(change, original_bytes, executable=False):
    if (not isinstance(change, dict) or set(change) != {'path', 'operation', 'base_hash', 'result_hash', 'edits'}
            or change['operation'] != 'patch' or not isinstance(change['path'], str)
            or not isinstance(original_bytes, bytes) or type(executable) is not bool):
        raise LoopError('Patch needs exact documented fields and original bytes')
    for key in ('base_hash', 'result_hash'):
        if not isinstance(change[key], str) or not re.fullmatch('[0-9a-f]{64}', change[key]):
            raise LoopError('Patch pins must be mode-aware lowercase SHA256 fingerprints')
    if bytes_pin(original_bytes, executable) != change['base_hash']:
        raise LoopError('Patch base fingerprint changed')
    edits = change['edits']
    if not isinstance(edits, list) or not 1 <= len(edits) <= 1000:
        raise LoopError('Patch needs one to one thousand exact edits')
    try:
        original_bytes.decode('utf-8')
        normalized = []
        for edit in edits:
            if (not isinstance(edit, dict) or set(edit) != {'start', 'end', 'content'}
                    or type(edit['start']) is not int or type(edit['end']) is not int
                    or not 0 <= edit['start'] <= edit['end'] <= len(original_bytes)
                    or not isinstance(edit['content'], str)):
                raise LoopError('Invalid patch byte edit')
            original_bytes[:edit['start']].decode('utf-8')
            original_bytes[:edit['end']].decode('utf-8')
            normalized.append((edit['start'], edit['end'], edit['content'].encode('utf-8')))
        normalized.sort(key=lambda row: (row[0], row[1]))
        for previous, following in zip(normalized, normalized[1:]):
            if following[0] < previous[1] or following[0] == previous[0]:
                raise LoopError('Patch edits overlap or have ambiguous duplicate offsets')
        chunks, cursor = [], 0
        for start, end, content in normalized:
            chunks.extend((original_bytes[cursor:start], content)); cursor = end
        chunks.append(original_bytes[cursor:]); result = b''.join(chunks)
        if bytes_pin(result, executable) != change['result_hash']:
            raise LoopError('Patch result fingerprint does not match')
        return result.decode('utf-8')
    except UnicodeError as exc:
        raise LoopError('Patch must preserve exact UTF-8 byte boundaries') from exc
