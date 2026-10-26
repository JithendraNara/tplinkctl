#!/usr/bin/env python3
"""Verify release archives contain the public runtime and source-test contract."""
import argparse
from email.parser import BytesParser
import json
from pathlib import Path
import tarfile
import zipfile


def check(directory):
    wheels = list(directory.glob('*.whl'))
    sources = list(directory.glob('*.tar.gz'))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError('Expected exactly one wheel and one source archive')
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        required = {'tplink_admin/' + name + '.py' for name in
                    ('__init__', '__main__', 'cli', 'mcp', 'api', 'registry', 'openapi', 'clidoc')}
        if not required <= names:
            raise ValueError('Wheel is missing runtime modules')
        profiles = {'tplink_admin/profiles/' + name + '.json' for name in
                    ('read-only', 'device-admin', 'network-admin', 'dangerous')}
        if not profiles <= names:
            raise ValueError('Wheel is missing packaged safety profiles')
        metadata = BytesParser().parsebytes(wheel.read(next(n for n in names if n.endswith('/METADATA'))))
        version = metadata['Version']
        entries = wheel.read(next(n for n in names if n.endswith('/entry_points.txt'))).decode()
        for name in ('tplinkctl', 'tpadmin', 'tplinkctl-mcp', 'tplinkctl-api'):
            if not any(line.startswith(name + ' = ') for line in entries.splitlines()):
                raise ValueError('Wheel is missing a console entry point')
    with tarfile.open(sources[0]) as source:
        members = {m.name.split('/', 1)[1]: m for m in source.getmembers() if '/' in m.name}
        required = {'tests/http_router.py', 'tests/test_http.py', 'Makefile', 'tpadmin.py',
                    'docs/openapi.json', 'docs/commands.md', 'docs/HTTP_API.md', 'docs/forge.md',
                    'scripts/forge_generate.py', 'scripts/forge_test.py',
                    'tooling/forge/pins.json', 'tooling/forge/smoke.mjs',
                    'tooling/forge/tsconfig.json', 'examples/bundles/index-BOBVatjl.js',
                    'CHANGELOG.md', 'requirements.txt', 'MANIFEST.in'}
        if not required <= members.keys():
            raise ValueError('Source archive is missing documented validation files')
        spec_file = source.extractfile(members['docs/openapi.json'])
        metadata_file = source.extractfile(members['PKG-INFO'])
        if spec_file is None or metadata_file is None:
            raise ValueError('Source archive metadata must be regular files')
        spec = json.load(spec_file)
        if spec['info']['version'] != version:
            raise ValueError('OpenAPI and distribution versions differ')
        source_meta = BytesParser().parsebytes(metadata_file.read())
        if source_meta['Version'] != version:
            raise ValueError('Source and wheel versions differ')
    return {'version': version, 'wheel_contract': 'passed', 'source_contract': 'passed'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.directory), sort_keys=True))
