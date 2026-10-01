"""Apply pinned browser compatibility changes to the build copy, never a submodule."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
def prepare(source):
    source = pathlib.Path(source).resolve()
    if source != (ROOT / 'build/desktop-windows/obs-source').resolve():
        raise ValueError('headless patches only apply to the isolated OBS build copy')
    browser = source / 'plugins/obs-browser'
    client = browser / 'browser-client.cpp'
    text = client.read_text(encoding='utf-8')
    old = '''\tstd::string str_text = text;
\tQMetaObject::invokeMethod(QCoreApplication::instance()->thread(),
\t\t\t\t  [str_text]() { QToolTip::showText(QCursor::pos(), str_text.c_str()); });'''
    new = '''\t// A browser source has no native Qt tooltip window in the headless host.
\t(void)text;'''
    if old in text: text = text.replace(old, new, 1)
    elif new not in text: raise ValueError('pinned browser tooltip implementation changed')
    for header in ('QApplication', 'QThread', 'QToolTip'):
        text = text.replace(f'#include <{header}>\n', '')
    client.write_text(text, encoding='utf-8')
    source_file = browser / 'obs-browser-source.cpp'
    text = source_file.read_text(encoding='utf-8')
    text = text.replace('#include <QApplication>\n', '')
    source_file.write_text(text, encoding='utf-8')

if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(2)
    prepare(sys.argv[1])
