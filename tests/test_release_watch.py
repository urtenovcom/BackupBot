from unittest.mock import Mock
import pytest
from backupbot.release_watch import check_releases

ITEMS = [{'repo': 'owner/project', 'name': 'Project'}]


def release(tag='v1.2.0', **kw):
    return {'tag_name': tag, 'html_url': 'https://github.com/owner/project/releases/tag/'+tag, **kw}


def test_first_observation_sets_baseline_without_spam():
    state = {}
    notify = Mock()
    check_releases(ITEMS, state, lambda _: release(), notify)
    assert state['owner/project']['tag'] == 'v1.2.0'
    notify.assert_not_called()


def test_new_release_sent_once():
    state = {'owner/project': {'tag': 'v1.1.0'}}
    notify = Mock()
    for _ in range(2):
        check_releases(ITEMS, state, lambda _: release(), notify)
    assert notify.call_count == 1
    assert 'v1.2.0' in notify.call_args.args[0]


def test_failed_delivery_does_not_mark_as_notified():
    state = {'owner/project': {'tag': 'v1.1.0'}}
    with pytest.raises(RuntimeError):
        check_releases(ITEMS, state, lambda _: release(), Mock(side_effect=RuntimeError('offline')))
    assert state['owner/project']['tag'] == 'v1.1.0'


@pytest.mark.parametrize('value', [release(prerelease=True), release(draft=True), release('v1.0.0')])
def test_skip_prerelease_draft_and_older_versions(value):
    state = {'owner/project': {'tag': 'v1.1.0'}}
    notify = Mock()
    check_releases(ITEMS, state, lambda _: value, notify)
    assert state['owner/project']['tag'] == 'v1.1.0'
    notify.assert_not_called()
