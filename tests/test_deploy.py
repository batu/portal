import plistlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_launch_agent_targets_headless_background_session():
    launch_agent = plistlib.loads((ROOT / "deploy/com.appletolye.gallery.plist").read_bytes())
    install_script = (ROOT / "deploy/install.sh").read_text()

    assert launch_agent["LimitLoadToSessionType"] == "Background"
    assert 'DOMAIN="user/$UID_NUM"' in install_script
    assert 'DOMAIN="gui/$UID_NUM"' not in install_script
