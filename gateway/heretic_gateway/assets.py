"""Cached UI files with build-time compression, separate from private API responses."""

from mimetypes import guess_type
from pathlib import Path
from stat import S_ISREG

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import NotModifiedResponse, StaticFiles


def encoding_preferences(value: str) -> dict[str, float]:
    preferences = {}
    for item in value.lower().split(','):
        encoding, *parameters = item.strip().split(';')
        quality = 1.0
        for parameter in parameters:
            name, separator, weight = parameter.strip().partition('=')
            if name == 'q':
                try:
                    quality = float(weight) if separator else 0.0
                except ValueError:
                    quality = 0.0
        if encoding:
            preferences[encoding] = quality if 0 <= quality <= 1 else 0.0
    return preferences


class StaticAssets(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or '.' in path or path.startswith('_app/'):
                raise
            return await super().get_response('index.html', scope)

    def file_response(self, full_path, stat_result, scope, status_code=200):
        original = Path(full_path)
        relative = original.relative_to(Path(self.directory).resolve())
        immutable = relative.parts[:2] == ('_app', 'immutable')
        headers = {'Cache-Control': 'public, max-age=31536000, immutable' if immutable
                   else 'no-cache', 'Vary': 'Accept-Encoding'}
        request_headers = Headers(scope=scope)
        preferences = encoding_preferences(','.join(request_headers.getlist('accept-encoding')))
        identity = preferences.get('identity', 0.0 if preferences.get('*') == 0 else 1.0)
        selected = None
        # Build plugins rewrite HTML and service workers after precompression.
        # Only content-hashed assets have trustworthy compressed siblings.
        if immutable:
            encodings = sorted(('br', 'gzip'),
                key=lambda name: preferences.get(name, preferences.get('*', 0.0)), reverse=True)
            for encoding in encodings:
                quality = preferences.get(encoding, preferences.get('*', 0.0))
                if quality <= 0 or ('identity' in preferences and identity > quality):
                    continue
                suffix = '.br' if encoding == 'br' else '.gz'
                compressed, compressed_stat = self.lookup_path(str(relative) + suffix)
                if compressed_stat is not None and S_ISREG(compressed_stat.st_mode):
                    full_path, stat_result, selected = compressed, compressed_stat, encoding
                    headers['Content-Encoding'] = encoding
                    break
        if selected is None and identity <= 0:
            raise HTTPException(406, 'No acceptable asset encoding.')
        # Infer MIME type from the original name, and validators from the served bytes.
        response = FileResponse(full_path, status_code=status_code, headers=headers,
            media_type=guess_type(str(original))[0] or 'application/octet-stream',
            stat_result=stat_result)
        response.headers['etag'] = response.headers['etag'].removesuffix('"') + (
            f'-{selected or "identity"}"')
        if self.is_not_modified(response.headers, request_headers):
            return NotModifiedResponse(response.headers)
        return response
