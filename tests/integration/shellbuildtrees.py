# Pylint doesn't play well with fixtures and dependency injection from pytest
# pylint: disable=redefined-outer-name

import os
import shutil

import pytest

from buildstream.testing import cli, cli_integration  # pylint: disable=unused-import
from buildstream.exceptions import ErrorDomain
from buildstream.testing._utils.site import HAVE_SANDBOX

from tests.testutils import create_artifact_share


pytestmark = pytest.mark.integration


DATA_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "project")


#
# Ensure that we didn't get a build tree if we didn't ask for one
#
@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.skipif(not HAVE_SANDBOX, reason="Only available with a functioning sandbox")
def test_buildtree_unused(cli_integration, datafiles):
    # We can only test the non interacitve case
    # The non interactive case defaults to not using buildtrees
    # for `bst shell --build`
    project = str(datafiles)
    element_name = "build-shell/buildtree.bst"

    res = cli_integration.run(project=project, args=["--cache-buildtrees", "always", "build", element_name])
    res.assert_success()

    res = cli_integration.run(project=project, args=["shell", "--build", element_name, "--", "cat", "test"])
    res.assert_shell_error()


#
# Ensure we can use a buildtree from a successful build
#
@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.skipif(not HAVE_SANDBOX, reason="Only available with a functioning sandbox")
def test_buildtree_from_success(cli_integration, datafiles):
    # Test that if we ask for a build tree it is there.
    project = str(datafiles)
    element_name = "build-shell/buildtree.bst"

    res = cli_integration.run(project=project, args=["--cache-buildtrees", "always", "build", element_name])
    res.assert_success()

    res = cli_integration.run(
        project=project, args=["shell", "--build", "--use-buildtree", element_name, "--", "cat", "test"]
    )
    res.assert_success()
    assert "Hi" in res.output


#
# Ensure we can use a buildtree from a failed build
#
@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.skipif(not HAVE_SANDBOX, reason="Only available with a functioning sandbox")
def test_buildtree_from_failure(cli_integration, datafiles):
    # Test that we can use a build tree after a failure
    project = str(datafiles)
    element_name = "build-shell/buildtree-fail.bst"

    res = cli_integration.run(project=project, args=["build", element_name])
    res.assert_main_error(ErrorDomain.STREAM, None)

    # Assert that file has expected contents
    res = cli_integration.run(
        project=project, args=["shell", "--build", element_name, "--use-buildtree", "--", "cat", "test"]
    )
    res.assert_success()
    assert "WARNING using a buildtree from a failed build" in res.stderr
    assert "Hi" in res.output


#
# Test behavior of launching a shell and requesting to use a buildtree, with
# various states of local cache (ranging from nothing cached to everything cached)
#
@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.skipif(not HAVE_SANDBOX, reason="Only available with a functioning sandbox")
@pytest.mark.parametrize(
    "pull,pull_deps,pull_buildtree,cache_buildtree",
    [
        # Don't pull at all
        (False, "build", False, False),
        # Pull only dependencies
        (True, "build", False, True),
        # Pull all elements including the shell element, but without the buildtree
        (True, "all", False, True),
        # Pull all elements including the shell element, and pull buildtrees
        (True, "all", True, True),
        # Pull all elements including the shell element, and pull buildtrees, but buildtree was never cached
        (True, "all", True, False),
    ],
    ids=["no-pull", "pull-only-deps", "pull-without-buildtree", "pull-with-buildtree", "created-without-buildtree"],
)
def test_shell_use_pulled_buildtree(cli, tmpdir, datafiles, pull, pull_deps, pull_buildtree, cache_buildtree):
    project = str(datafiles)
    element_name = "build-shell/buildtree.bst"

    with create_artifact_share(os.path.join(str(tmpdir), "artifactshare")) as share:
        # Build the element to push it to cache
        cli.configure({"artifacts": {"url": share.repo, "push": True}})

        # Build it, optionally caching the build tree
        args = []
        if cache_buildtree:
            args += ["--cache-buildtrees", "always"]
        args += ["--on-error", "continue", "build", element_name]
        result = cli.run(project=project, args=args)
        result.assert_success()

        assert cli.get_element_state(project, element_name) == "cached"
        assert share.get_artifact(cli.get_artifact_name(project, "test", element_name))

        # Discard the local cache
        shutil.rmtree(str(os.path.join(str(tmpdir), "cache", "cas")))
        shutil.rmtree(str(os.path.join(str(tmpdir), "cache", "artifacts")))
        assert cli.get_element_state(project, element_name) != "cached"

        # Optionally pull the buildtree along with `bst artifact pull`
        if pull:
            args = []
            if pull_buildtree:
                args += ["--pull-buildtrees"]
            args += ["artifact", "pull", "--deps", pull_deps, element_name]

            # Pull from cache
            result = cli.run(project=project, args=args)
            result.assert_success()

        # Run the shell without asking it to pull any buildtree, just asking to use a buildtree
        result = cli.run(
            project=project, args=["shell", "--build", element_name, "--use-buildtree", "--", "cat", "test"]
        )

        # If we did pull the buildtree, expect success, otherwise fail
        if pull:
            if pull_deps == "all":
                if pull_buildtree:

                    if cache_buildtree:
                        result.assert_success()
                        assert "Hi" in result.output
                    else:
                        # Sorry, a buildtree was never cached for this element
                        result.assert_main_error(
                            ErrorDomain.APP, "missing-buildtree-artifact-created-without-buildtree"
                        )
                else:
                    # We just didn't pull the buildtree
                    result.assert_main_error(ErrorDomain.APP, "missing-buildtree-artifact-buildtree-not-cached")
            else:
                # The artifact we're shelling into is missing
                result.assert_main_error(ErrorDomain.APP, "missing-buildtree-artifact-not-cached")
        else:
            # The dependencies are missing, cannot stage anything even
            result.assert_main_error(ErrorDomain.APP, "shell-missing-deps")


#
# Test behavior of launching a shell and requesting to use and pull a buildtree, with
# various states of local cache (ranging from nothing cached to everything cached)
#
@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.skipif(not HAVE_SANDBOX, reason="Only available with a functioning sandbox")
@pytest.mark.parametrize(
    "pull,pull_deps,pull_buildtree,cache_buildtree",
    [
        # Don't pull at all
        (False, "build", False, True),
        # Pull only dependencies
        (True, "build", False, True),
        # Pull all elements including the shell element, but without the buildtree
        (True, "all", False, True),
        # Pull all elements including the shell element, and pull buildtrees
        (True, "all", True, True),
        # Pull all elements including the shell element, and pull buildtrees, but buildtree was never cached
        (True, "all", True, False),
    ],
    ids=["no-pull", "pull-only-deps", "pull-without-buildtree", "pull-with-buildtree", "created-without-buildtree"],
)
def test_shell_pull_buildtree(cli, tmpdir, datafiles, pull, pull_deps, pull_buildtree, cache_buildtree):
    project = str(datafiles)
    element_name = "build-shell/buildtree.bst"

    with create_artifact_share(os.path.join(str(tmpdir), "artifactshare")) as share:
        # Build the element to push it to cache
        cli.configure({"artifacts": {"url": share.repo, "push": True}})

        # Build it, optionally caching the build tree
        args = []
        if cache_buildtree:
            args += ["--cache-buildtrees", "always"]
        args += ["build", element_name]
        result = cli.run(project=project, args=args)
        result.assert_success()

        assert cli.get_element_state(project, element_name) == "cached"
        assert share.get_artifact(cli.get_artifact_name(project, "test", element_name))

        # Discard the local cache
        shutil.rmtree(str(os.path.join(str(tmpdir), "cache", "cas")))
        shutil.rmtree(str(os.path.join(str(tmpdir), "cache", "artifacts")))
        assert cli.get_element_state(project, element_name) != "cached"

        # Optionally pull the buildtree along with `bst artifact pull`
        if pull:
            args = []
            if pull_buildtree:
                args += ["--pull-buildtrees"]
            args += ["artifact", "pull", "--deps", pull_deps, element_name]

            # Pull from cache
            result = cli.run(project=project, args=args)
            result.assert_success()

        # Run the shell without asking it to pull any buildtree, just asking to use a buildtree
        result = cli.run(
            project=project,
            args=[
                "--pull-buildtrees",
                "shell",
                "--build",
                element_name,
                "--pull",
                "--use-buildtree",
                "--",
                "cat",
                "test",
            ],
        )

        if cache_buildtree:
            result.assert_success()
            assert "Hi" in result.output
        else:
            # Sorry, a buildtree was never cached for this element
            result.assert_main_error(ErrorDomain.APP, "missing-buildtree-artifact-created-without-buildtree")
