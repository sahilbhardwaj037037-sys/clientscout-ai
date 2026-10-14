"""Bounded local evidence. Provider messages never become rate-limit guesses."""
import hashlib
import json
import logging
import re

logger = logging.getLogger('clientscout.discovery')


def configure_logging():
    if not logger.handlers:
        handler=logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate=False


def scrub(value, limit=1000):
    value = str(value)
    value = re.sub(r'https?://[^\s]+', '[URL redacted]', value)
    value = re.sub(r'(?i)(?:api[_-]?key|token|password|secret)\s*[=:]\s*[^\s,;<>]+', '[credential redacted]', value)
    return ''.join(c if ord(c)>=32 and ord(c)!=127 else ' ' for c in value)[:limit]


def failure_kind(status, remark):
    message=remark.casefold()
    if status==429: return 'rate_limit', 'The provider returned HTTP 429. Respect its cooldown; do not switch servers to bypass it.'
    if status==503: return 'provider_unavailable', 'The provider returned HTTP 503. Try later after the recorded cooldown.'
    if status==504: return 'provider_capacity', 'HTTP 504 indicates a provider resource/admission or gateway failure, not proof of a rate limit. Try a smaller nearby sample later.'
    if any(word in message for word in ('parse error','static error','syntax error')): return 'query_syntax', 'The provider rejected query syntax. Do not repeat unchanged requests; report the diagnostic query.'
    if any(word in message for word in ('timed out','timeout','time out')): return 'query_timeout', 'The provider reported a query timeout. Try nearby coordinates with a 500 m sample after cooldown.'
    if any(word in message for word in ('out of memory','memory limit','ran out of memory')): return 'query_memory', 'The provider reported a memory limit. Try a 500 m nearby sample after cooldown.'
    return 'provider_query_error', 'The provider reported an incomplete or failed query. Review its retained remark; use a smaller nearby sample or retry later. No partial results were accepted.'


def trace(statement,stage,response=None,failure=None):
    record={'stage':stage,'query':statement[:6000], 'query_sha256':hashlib.sha256(statement.encode()).hexdigest()}
    if response:
        record.update(http_status=response.status, response_bytes=len(response.body), response_sha256=hashlib.sha256(response.body).hexdigest(), elapsed_ms=response.elapsed_ms, fetched_at=response.fetched_at)
        if response.headers.get('retry-after'): record['retry_after']=scrub(response.headers['retry-after'],200)
        try: document=json.loads(response.body)
        except (ValueError,UnicodeError): document=None
        remark=document.get('remark') if isinstance(document,dict) else None
        if remark or response.status!=200 or not isinstance(document,dict) or not isinstance(document.get('elements'),list):
            if isinstance(remark,str): record['provider_remark']=scrub(remark)
            elif remark: record['provider_remark']='Provider returned a non-text remark.'
            # Only bounded error evidence, not complete business response bodies.
            record['body_excerpt']=scrub(json.dumps({'remark':remark},ensure_ascii=False) if remark else re.sub('<[^>]*>', ' ',response.body[:4096].decode('utf-8','replace')),1200)
            code,hint=failure_kind(response.status,str(remark or record['body_excerpt']))
            record.update(code=code,hint=hint)
        else: record['elements_returned']=len(document['elements']) if isinstance(document.get('elements'),list) else None
    else:
        record.update(http_status=None,code=getattr(failure,'code','network_error'), hint='Network request failed before a provider response was available.')
    # No query text, response body, location or credentials in routine terminal logs.
    logger.info('Overpass stage=%s status=%s code=%s query_sha256=%s bytes=%s',stage,record.get('http_status'),record.get('code','ok'),record['query_sha256'],record.get('response_bytes'))
    return record
