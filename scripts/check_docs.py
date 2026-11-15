"""Check local documentation links, without network calls or modifying originals."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    names = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root).decode('utf-8').split('\0')
    errors, count = [], 0
    for name in sorted(set(names)):
        if not name.endswith('.md') or name.startswith('release/licenses/'):
            continue  # Third-party originals must remain unchanged.
        source = root / name
        if not source.is_file():
            continue
        count += 1
        content = re.sub(r'```.*?```', '', source.read_text(encoding='utf-8'), flags=re.S)
        links = [match.group(1).strip('<>') for match in re.finditer(r'!?\[[^\]]*\]\((<?[^\s)]+>?)(?:\s+"[^"]*")?\)', content)]
        links += [match.group(1) for match in re.finditer(r'(?:href|src|srcset)=[\"\']([^\"\']+)[\"\']', content)]
        for value in links:
            if value.startswith('#') or urlsplit(value).scheme:
                continue
            path = unquote(value.split('#', 1)[0].split('?', 1)[0])
            target = (root / path.lstrip('/') if path.startswith('/') else source.parent / path).resolve()
            if not target.is_relative_to(root.resolve()) or not target.exists():
                errors.append(f'{name}: missing local target {value}')
    return count, errors


if __name__ == '__main__':
    count, errors = check()
    for error in errors:
        print(error)
    print(f'Checked {count} Markdown files; {len(errors)} broken local links.')
    raise SystemExit(bool(errors))
