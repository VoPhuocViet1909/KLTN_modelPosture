"""Check shared KLTN design rules, colors and labels using only Python's stdlib."""
import argparse
import json
from pathlib import Path
import re


def check(web, desktop):
    skill = Path('.agents/skills/design-system')
    for name in ('SKILL.md', 'scripts/check_sync.py'):
        assert (web / skill / name).read_bytes() == (desktop / skill / name).read_bytes(), f'Skill differs: {name}'
    css = (web / 'src/index.css').read_text(encoding='utf-8')
    colors = dict(re.findall(r'--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})', css))
    ui = desktop / 'posture_model/ui'
    tokens = json.loads((ui / 'design_tokens.json').read_text(encoding='utf-8'))
    for key, value in tokens['colors'].items():
        assert colors.get(key, '').lower() == value.lower(), f'Color differs: {key}'
    for key, value in tokens['status'].items():
        assert colors.get('status-' + key.lower(), '').lower() == value.lower(), f'Status color differs: {key}'
    font = re.search(r'''--font-sans:\s*['"]([^'"]+)['"]''', css)
    assert font and font[1] == tokens['font']['family'], 'Font family differs'
    ts = (web / 'src/lib/labels.ts').read_text(encoding='utf-8')
    labels = json.loads((ui / 'labels.json').read_text(encoding='utf-8'))
    alerts = dict(re.findall(r"^\s+([A-Z_]+): '([^']+)',?$", ts.split('SEVERITY_LABEL')[0], re.M))
    assert alerts and alerts == {key: item['label'] for key, item in labels['alert'].items()}, 'Alert labels differ'
    states = dict(re.findall(r"^\s+(GOOD|BAD|AWAY|OFFLINE): \{ label: '([^']+)'", ts, re.M))
    assert set(states) == {'GOOD', 'BAD', 'AWAY', 'OFFLINE'}, 'Missing web state labels'
    for key, value in states.items():
        assert value == labels['state'][key]['label'], f'State label differs: {key}'
    severities = dict(re.findall(r"^\s+(LOW|MEDIUM|HIGH): '([^']+)'", ts, re.M))
    assert severities == labels['severity'], 'Severity labels differ'
    print('OK: shared skill, colors, font, state/alert/severity labels match.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web', type=Path, required=True)
    parser.add_argument('--desktop', type=Path, required=True)
    args = parser.parse_args()
    check(args.web, args.desktop)
