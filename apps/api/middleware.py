"""Reject oversized multipart requests before unbounded parser spooling."""
import re

from fastapi import HTTPException
from starlette.responses import JSONResponse


class RequestBoundary:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        origin = headers.get(b'origin', b'').decode('latin1')
        if scope['method'] not in {'GET', 'HEAD', 'OPTIONS'} and origin:
            local = re.fullmatch(r'https?://(localhost|127\.0\.0\.1)(:\d+)?', origin)
            if not local and origin not in self.settings.cors_origins:
                response = JSONResponse({'detail': {'code': 'ORIGIN_DENIED', 'message': 'This browser origin is not allowed'}}, status_code=403)
                return await response(scope, receive, send)
        # One file per request plus a bounded allowance for multipart metadata.
        limit = self.settings.max_upload_bytes + 1024 * 1024
        try:
            declared = int(headers.get(b'content-length', b'0'))
        except ValueError:
            declared = 0
        if declared > limit:
            response = JSONResponse({'detail': {'code': 'UPLOAD_TOO_LARGE', 'message': 'Request exceeds the upload limit'}}, status_code=413)
            return await response(scope, receive, send)
        consumed = 0
        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get('body', b''))
            if consumed > limit:
                raise HTTPException(413, detail={'code': 'UPLOAD_TOO_LARGE', 'message': 'Request exceeds the upload limit'})
            return message
        await self.app(scope, bounded_receive, send)
