"""Local accident prevention; server rules remain the authoritative enforcement."""
import sys


def blocked_updates(lines):
    blocked = []
    for line in lines:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError('Invalid Git pre-push input')
        target = fields[2]
        if target in ('refs/heads/main', 'refs/heads/integration') or target.startswith('refs/tags/v'):
            blocked.append(target)
    return blocked


if __name__ == '__main__':
    blocked = blocked_updates(sys.stdin)
    if blocked:
        print('Push rejected: main/integration require reviewed pull requests; release tags belong to the Release workflow.\nTargets: ' + ', '.join(blocked), file=sys.stderr)
        raise SystemExit(1)
