"""Build native air/sea comparison page assets and deployment mirrors."""
from __future__ import annotations
import json
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def build_air_sea_assets(package_root=PACKAGE_ROOT):
    root = Path(package_root)
    source = root / 'page/air_sea_cost_comparison'
    mirror = root / 'overseas_costing/page/air_sea_cost_comparison'
    parts = source / 'parts'
    content = '(function (globalThis) {\n"use strict";\n'
    for path in sorted(parts.glob('*.js')):
        if path.name >= '40':
            continue
        content += f'\n// Source: {path.name}\n' + path.read_text().rstrip() + '\n'
    content += '\nconst PAGE_TEMPLATE = ' + json.dumps((parts / '40-template.html').read_text(), ensure_ascii=False) + ';\n'
    for path in sorted(parts.glob('*.js')):
        if path.name >= '40':
            content += f'\n// Source: {path.name}\n' + path.read_text().rstrip() + '\n'
    content += '\n})(typeof globalThis !== "undefined" ? globalThis : window);\n'
    css = '\n'.join(path.read_text().rstrip() for path in sorted(parts.glob('*.css'))) + '\n'
    changed = []
    for path, text in [(source/'air_sea_cost_comparison.js', content), (source/'air_sea_cost_comparison.css', css)]:
        if not path.exists() or path.read_text()!=text:
            path.write_text(text); changed.append(str(path))
    mirror.mkdir(parents=True, exist_ok=True)
    for name in ['air_sea_cost_comparison.js','air_sea_cost_comparison.css','air_sea_cost_comparison.json','air_sea_cost_comparison.py','__init__.py']:
        path=mirror/name;data=(source/name).read_bytes()
        if not path.exists() or path.read_bytes()!=data:
            path.write_bytes(data);changed.append(str(path))
    return {'changed':changed}

if __name__=='__main__':
    print(json.dumps(build_air_sea_assets(),ensure_ascii=False,indent=2))
