# Pylint doesn't play well with fixtures and dependency injection from pytest
# pylint: disable=redefined-outer-name

import os
import stat
import pytest

from buildstream._exceptions import ErrorDomain
from buildstream import _yaml
from buildstream.plugintestutils import cli
from tests.testutils.file_server import create_file_server

DATA_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    'remote',
)


def generate_project(project_dir, tmpdir):
    project_file = os.path.join(project_dir, "project.conf")
    _yaml.dump({
        'name': 'foo',
        'aliases': {
            'tmpdir': "file:///" + str(tmpdir)
        }
    }, project_file)


def generate_project_file_server(server, project_dir):
    project_file = os.path.join(project_dir, "project.conf")
    _yaml.dump({
        'name': 'foo',
        'aliases': {
            'tmpdir': server.base_url()
        }
    }, project_file)


# Test that without ref, consistency is set appropriately.
@pytest.mark.datafiles(os.path.join(DATA_DIR, 'no-ref'))
def test_no_ref(cli, tmpdir, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    generate_project(project, tmpdir)
    assert cli.get_element_state(project, 'target.bst') == 'no reference'


# Here we are doing a fetch on a file that doesn't exist. target.bst
# refers to 'file' but that file is not present.
@pytest.mark.datafiles(os.path.join(DATA_DIR, 'missing-file'))
def test_missing_file(cli, tmpdir, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    generate_project(project, tmpdir)

    # Try to fetch it
    result = cli.run(project=project, args=[
        'source', 'fetch', 'target.bst'
    ])

    result.assert_main_error(ErrorDomain.STREAM, None)
    result.assert_task_error(ErrorDomain.SOURCE, None)


@pytest.mark.datafiles(os.path.join(DATA_DIR, 'path-in-filename'))
def test_path_in_filename(cli, tmpdir, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    generate_project(project, tmpdir)

    # Try to fetch it
    result = cli.run(project=project, args=[
        'source', 'fetch', 'target.bst'
    ])

    # The bst file has a / in the filename param
    result.assert_main_error(ErrorDomain.SOURCE, "filename-contains-directory")


@pytest.mark.datafiles(os.path.join(DATA_DIR, 'single-file'))
def test_simple_file_build(cli, tmpdir, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    generate_project(project, tmpdir)
    checkoutdir = os.path.join(str(tmpdir), "checkout")

    # Try to fetch it
    result = cli.run(project=project, args=[
        'source', 'fetch', 'target.bst'
    ])
    result.assert_success()

    result = cli.run(project=project, args=[
        'build', 'target.bst'
    ])
    result.assert_success()

    result = cli.run(project=project, args=[
        'artifact', 'checkout', 'target.bst', '--directory', checkoutdir
    ])
    result.assert_success()
    # Note that the url of the file in target.bst is actually /dir/file
    # but this tests confirms we take the basename
    checkout_file = os.path.join(checkoutdir, 'file')
    assert os.path.exists(checkout_file)

    mode = os.stat(checkout_file).st_mode
    # Assert not executable by anyone
    assert not mode & (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    # Assert not writeable by anyone other than me
    assert not mode & (stat.S_IWGRP | stat.S_IWOTH)


@pytest.mark.datafiles(os.path.join(DATA_DIR, 'single-file-custom-name'))
def test_simple_file_custom_name_build(cli, tmpdir, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    generate_project(project, tmpdir)
    checkoutdir = os.path.join(str(tmpdir), "checkout")

    # Try to fetch it
    result = cli.run(project=project, args=[
        'source', 'fetch', 'target.bst'
    ])
    result.assert_success()

    result = cli.run(project=project, args=[
        'build', 'target.bst'
    ])
    result.assert_success()

    result = cli.run(project=project, args=[
        'artifact', 'checkout', 'target.bst', '--directory', checkoutdir
    ])
    result.assert_success()
    assert not os.path.exists(os.path.join(checkoutdir, 'file'))
    assert os.path.exists(os.path.join(checkoutdir, 'custom-file'))


@pytest.mark.datafiles(os.path.join(DATA_DIR, 'unique-keys'))
def test_unique_key(cli, tmpdir, datafiles):
    '''This test confirms that the 'filename' parameter is honoured when it comes
    to generating a cache key for the source.
    '''
    project = os.path.join(datafiles.dirname, datafiles.basename)
    generate_project(project, tmpdir)
    states = cli.get_element_states(project, [
        'target.bst', 'target-custom.bst', 'target-custom-executable.bst'
    ])
    assert states['target.bst'] == "fetch needed"
    assert states['target-custom.bst'] == "fetch needed"
    assert states['target-custom-executable.bst'] == "fetch needed"

    # Try to fetch it
    cli.run(project=project, args=[
        'source', 'fetch', 'target.bst'
    ])

    # We should download the file only once
    states = cli.get_element_states(project, [
        'target.bst', 'target-custom.bst', 'target-custom-executable.bst'
    ])
    assert states['target.bst'] == 'buildable'
    assert states['target-custom.bst'] == 'buildable'
    assert states['target-custom-executable.bst'] == 'buildable'

    # But the cache key is different because the 'filename' is different.
    assert cli.get_element_key(project, 'target.bst') != \
        cli.get_element_key(project, 'target-custom.bst') != \
        cli.get_element_key(project, 'target-custom-executable.bst')


@pytest.mark.datafiles(os.path.join(DATA_DIR, 'unique-keys'))
def test_executable(cli, tmpdir, datafiles):
    '''This test confirms that the 'ecxecutable' parameter is honoured.
    '''
    project = os.path.join(datafiles.dirname, datafiles.basename)
    generate_project(project, tmpdir)
    checkoutdir = os.path.join(str(tmpdir), "checkout")
    assert cli.get_element_state(project, 'target-custom-executable.bst') == "fetch needed"
    # Try to fetch it
    cli.run(project=project, args=[
        'build', 'target-custom-executable.bst'
    ])

    cli.run(project=project, args=[
        'artifact', 'checkout', 'target-custom-executable.bst', '--directory', checkoutdir
    ])
    mode = os.stat(os.path.join(checkoutdir, 'some-custom-file')).st_mode
    assert mode & stat.S_IEXEC
    # Assert executable by anyone
    assert mode & (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.mark.parametrize('server_type', ('FTP', 'HTTP'))
@pytest.mark.datafiles(os.path.join(DATA_DIR, 'single-file'))
def test_use_netrc(cli, datafiles, server_type, tmpdir):
    fake_home = os.path.join(str(tmpdir), 'fake_home')
    os.makedirs(fake_home, exist_ok=True)
    project = str(datafiles)
    checkoutdir = os.path.join(str(tmpdir), 'checkout')

    os.environ['HOME'] = fake_home
    with open(os.path.join(fake_home, '.netrc'), 'wb') as f:
        os.fchmod(f.fileno(), 0o700)
        f.write(b'machine 127.0.0.1\n')
        f.write(b'login testuser\n')
        f.write(b'password 12345\n')

    with create_file_server(server_type) as server:
        server.add_user('testuser', '12345', project)
        generate_project_file_server(server, project)

        server.start()

        result = cli.run(project=project, args=['source', 'fetch', 'target.bst'])
        result.assert_success()
        result = cli.run(project=project, args=['build', 'target.bst'])
        result.assert_success()
        result = cli.run(project=project, args=['artifact', 'checkout', 'target.bst', '--directory', checkoutdir])
        result.assert_success()

        checkout_file = os.path.join(checkoutdir, 'file')
        assert os.path.exists(checkout_file)
