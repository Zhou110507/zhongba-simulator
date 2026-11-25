"""Build the offline Windows x64 application using the official CPython distribution."""
import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]


def build(destination):
    if sys.platform != 'win32' or struct.calcsize('P') != 8:
        raise RuntimeError('Build with Windows x64 CPython.')
    destination.mkdir(parents=True, exist_ok=False)
    for folder in ('billiards', 'configs', 'web'):
        shutil.copytree(ROOT/folder, destination/folder, ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('启动中八3D.cmd', 'tools/windows/使用说明.txt'):
        shutil.copy2(ROOT/name, destination/Path(name).name)
    # The historical workbench links to two self-contained HTML reports.
    reports = ROOT/'artifacts'/'phase-a'
    output = destination/'artifacts'/'phase-a'
    output.mkdir(parents=True)
    for name in ('验收演示.html', '05-薄厚球专项复核.html'):
        shutil.copy2(reports/name, output/name)

    runtime = destination/'runtime'
    runtime.mkdir()
    base = Path(sys.base_prefix)
    for source in [base/'python.exe', base/'LICENSE.txt', *base.glob('*.dll')]:
        shutil.copy2(source, runtime/source.name)
    shutil.copytree(base/'DLLs', runtime/'DLLs')
    shutil.copytree(Path(sysconfig.get_path('stdlib')), runtime/'Lib',
                    ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test',
                                                  'idlelib', 'tkinter', 'ensurepip'))
    paths = ['Lib', 'DLLs', '.', '..', 'Lib/site-packages', 'import site']
    (runtime/f'python{sys.version_info.major}{sys.version_info.minor}._pth').write_text(
        '\n'.join(paths)+'\n', encoding='ascii')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
                    '--no-deps', '--no-compile', '--only-binary=:all:', '--target',
                    str(runtime/'Lib'/'site-packages'), 'numpy==2.2.6'], check=True)
    compiler = Path(os.environ['WINDIR'])/'Microsoft.NET'/'Framework64'/'v4.0.30319'/'csc.exe'
    subprocess.run([str(compiler), '/nologo', '/codepage:65001', '/target:winexe', '/optimize+',
                    '/reference:System.Windows.Forms.dll', '/out:'+str(destination/'Zhongba3D.exe'),
                    str(ROOT/'tools'/'windows'/'Launcher.cs')], check=True)
    print(f'Built {destination} with Python {sys.version.split()[0]} and NumPy 2.2.6.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output.resolve())
