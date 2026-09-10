"""Select Python tests through transitive imports, with conservative resource fallbacks."""
import ast
from pathlib import Path
import subprocess
import sys


def select_tests(root, changed):
    root=Path(root);files=list((root/'overseas_costing').rglob('*.py'))
    modules={'.'.join(p.relative_to(root).with_suffix('').parts).removesuffix('.__init__'):p.relative_to(root).as_posix() for p in files}
    tests={p for p in modules.values() if '/tests/test_' in p}
    reverse={};texts={};known=set(modules.values());selected=set();seeds=set()
    for mod,path in modules.items():
        text=(root/path).read_text();texts[path]=text
        try:tree=ast.parse(text)
        except SyntaxError:return sorted(tests),'Python parsing requires broad checks'
        package=mod if path.endswith('/__init__.py') else mod.rpartition('.')[0]
        for node in ast.walk(tree):
            names=[]
            if isinstance(node,ast.Import):names=[a.name for a in node.names]
            elif isinstance(node,ast.ImportFrom):
                base=node.module or ''
                if node.level:
                    parts=package.split('.');base='.'.join(parts[:len(parts)-node.level+1]+([base] if base else []))
                names=[base,*[base+'.'+a.name for a in node.names]]
            for name in names:
                while name and name not in modules:name=name.rpartition('.')[0]
                if name:reverse.setdefault(modules[name],set()).add(path)
    frontend=False
    for path in changed:
        if path.endswith(('.md','.png','.jpg')):continue
        if path in {'.github/workflows/deploy-overseas-costing.yml','overseas_costing/scripts/run_affected_tests.py'}:
            selected.update(p for p in tests if p.endswith('/test_affected_tests.py'));continue
        if 'overseas_cost_workbench/' in path:
            frontend=True;continue
        if path in known:
            seeds.add(path)
            # Include tests using import_module, monkeypatch paths or resource reads.
            module=path.removesuffix('.py').replace('/','.')
            for test in tests:
                if module in texts[test] or Path(path).stem in texts[test]:selected.add(test)
        else:return sorted(tests),'Unmapped runtime or schema change requires broad checks'
    pending=list(seeds);affected=set(seeds)
    while pending:
        for caller in reverse.get(pending.pop(),set()):
            if caller not in affected:affected.add(caller);pending.append(caller)
    selected.update(affected & tests)
    if frontend:selected.update(p for p in tests if any(x in p for x in ('frontend','workbench','_ui.py','build_assets')))
    if seeds and not selected:return sorted(tests),'No known test dependency; broad checks required'
    return sorted(selected),'Changed modules, their callers and affected workbench behavior'


def main():
    root=Path(__file__).resolve().parents[2];base=sys.argv[1] if len(sys.argv)>1 else ''
    if not base or set(base)=={'0'}:
        paths=['requirements.txt']
    else:
        paths=subprocess.check_output(['git','diff','--name-only',base,'HEAD'],cwd=root,text=True).splitlines()
    selected,reason=select_tests(root,paths)
    print(f'{reason}: {len(selected)} test files',flush=True)
    if selected:return subprocess.call([sys.executable,'-m','pytest','-q',*selected],cwd=root)
    return 0


if __name__=='__main__':raise SystemExit(main())
