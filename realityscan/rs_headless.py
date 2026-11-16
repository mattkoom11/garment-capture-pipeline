#!/usr/bin/env python3
"""Run RealityScan (CrossOver/Wine install) headless, safely.

Every job: refuses to start while a RealityScan window is open (headless runs
stall when one is), passes arguments to Wine as a list (no shell quoting),
appends a sentinel command so completion is detectable (-quit does not exit
under CrossOver), then kills only the headless instance and deletes the
autosave it leaves behind.

Jobs
  align        PROJECT --save-as OUT.rsproj --export-dir DIR
  import-cps   PROJECT CSV --export-dir DIR        (import, save, re-align, save)
  ai-masks     PROJECT                              (generateAIMasks, save)
  white-masks  PROJECT --frames 04803,04836 ...     (keep whole frame for these)
  components   PROJECT --export-dir DIR             (export every component)

PROJECT is a Linux path to an .rsproj. Exported components are .rsalign files;
read them with components.py.
"""
import argparse, os, re, shutil, signal, subprocess, sys, time
from pathlib import Path

WINE = '/opt/realityscan/bin/wine'
EXE = r'C:\Program Files\Epic Games\RealityScan\RealityScan.exe'
EXE_RE = re.compile(r'^C:.Program Files.Epic Games.RealityScan.RealityScan\.exe')


def win(p):
    """Linux path -> Wine Z: path."""
    return 'Z:' + str(Path(p).resolve()).replace('/', '\\')


def rs_pids(headless):
    out = []
    for d in Path('/proc').iterdir():
        if not d.name.isdigit():
            continue
        try:
            cmd = (d / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='ignore').strip()
        except OSError:
            continue
        if EXE_RE.match(cmd) and (('-headless' in cmd) == headless):
            out.append(int(d.name))
    return out


def remove_autosave(project):
    project = Path(project)
    for p in project.parent.glob(project.stem + '*.autosave'):
        shutil.rmtree(p) if p.is_dir() else p.unlink()


def run(project, commands, sentinel, timeout):
    if rs_pids(headless=False):
        sys.exit('RealityScan window is open; close it first (headless runs stall otherwise).')
    if rs_pids(headless=True):
        sys.exit('Another headless RealityScan run is active.')
    sentinel = Path(sentinel)
    sentinel.unlink(missing_ok=True)
    argv = [WINE, '--wait-children', '--bottle=default', EXE, '-headless'] + commands + \
           ['-listControlPoints', win(sentinel)]
    print('running:', ' '.join(commands[:6]), '...' if len(commands) > 6 else '', flush=True)
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    ok = False
    try:
        while time.time() - t0 < timeout:
            if sentinel.exists():
                ok = True
                break
            if proc.poll() is not None and not rs_pids(headless=True):
                break
            time.sleep(3)
        time.sleep(3)
    finally:
        for pid in rs_pids(headless=True):
            os.kill(pid, signal.SIGTERM)
        time.sleep(3)
        remove_autosave(project)
    print(f'{"done" if ok else "FAILED"} in {time.time() - t0:.0f}s')
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('job', choices=['align', 'import-cps', 'ai-masks', 'white-masks', 'components'])
    ap.add_argument('project')
    ap.add_argument('csv', nargs='?')
    ap.add_argument('--save-as')
    ap.add_argument('--export-dir')
    ap.add_argument('--frames', help='comma-separated DSC numbers, e.g. 04803,04836')
    ap.add_argument('--timeout', type=int, default=3600)
    a = ap.parse_args()

    proj = Path(a.project).resolve()
    out = Path(a.save_as).resolve() if a.save_as else proj
    exp = Path(a.export_dir).resolve() if a.export_dir else proj.parent / '_rs_export'
    exp.mkdir(parents=True, exist_ok=True)
    sentinel = exp / 'done.txt'
    cmds = ['-load', win(proj)]

    if a.job == 'align':
        cmds += ['-save', win(out), '-align', '-save', win(out), '-exportLatestComponents', win(exp)]
    elif a.job == 'import-cps':
        if not a.csv:
            sys.exit('import-cps needs the CSV path')
        cmds += ['-importControlPointsMeasurements', win(a.csv), '-save', win(out),
                 '-align', '-save', win(out), '-exportLatestComponents', win(exp)]
    elif a.job == 'ai-masks':
        cmds += ['-generateAIMasks', '-save', win(out)]
    elif a.job == 'white-masks':
        if not a.frames:
            sys.exit('white-masks needs --frames')
        text = proj.read_text(errors='ignore')
        inputs = re.findall(r'<input fileName="[^"]*?(DSC\d+)\.\w+"\s+width="(\d+)"\s+height="(\d+)"', text)
        names = [n for n, _, _ in inputs]
        w, h = inputs[0][1], inputs[0][2]
        white = proj.parent.parent / '_masks' / f'white_{w}x{h}.png'
        if not white.exists():
            import numpy as np, cv2
            white.parent.mkdir(exist_ok=True)
            cv2.imwrite(str(white), np.full((int(h), int(w)), 255, np.uint8))
        for f in a.frames.split(','):
            cmds += ['-setImageLayer', str(names.index('DSC' + f.strip())), win(white), 'mask']
        cmds += ['-save', win(out)]
        print(f'project now depends on {white} (do not move it)')
    elif a.job == 'components':
        names = re.findall(r'<component name="([^"]+)"', proj.read_text(errors='ignore'))
        for i, n in enumerate(names):
            cmds += ['-selectComponent', n, '-exportSelectedComponentFile', win(exp / f'c{i:02d}.rsalign')]
        (exp / 'component_names.txt').write_text(
            ''.join(f'c{i:02d}|{n}\n' for i, n in enumerate(names)))

    ok = run(proj, cmds, sentinel, a.timeout)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
