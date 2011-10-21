# vim: set fileencoding=utf-8 :
#
# (C) 2007,2009 Guido Guenther <agx@sigxcpu.org>
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""
Simple class wrappers for the various external commands needed by
git-buildpackage and friends
"""

import subprocess
import os
import os.path
import signal
import log
from errors import GbpError

class CommandExecFailed(Exception):
    """Exception raised by the Command class"""
    pass


class Command(object):
    """
    Wraps a shell command, so we don't have to store any kind of command line options in 
    one of the git-buildpackage commands
    """

    def __init__(self, cmd, args=[], shell=False, extra_env=None, cwd=None):
        self.cmd = cmd
        self.args = args
        self.run_error = "Couldn't run '%s'" % (" ".join([self.cmd] + self.args))
        self.shell = shell
        self.retcode = 1
        self.cwd = cwd
        if extra_env is not None:
            self.env = os.environ.copy()
            self.env.update(extra_env)
        else:
            self.env = None

    def __call(self, args):
        """wraps subprocess.call so we can be verbose and fix python's SIGPIPE handling"""
        def default_sigpipe():
            "restore default signal handler (http://bugs.python.org/issue1652)"
            signal.signal(signal.SIGPIPE, signal.SIG_DFL)

        log.debug("%s %s %s" % (self.cmd, self.args, args))
        cmd = [ self.cmd ] + self.args + args
        if self.shell: # subprocess.call only cares about the first argument if shell=True
            cmd = " ".join(cmd)
        return subprocess.call(cmd, cwd=self.cwd, shell=self.shell,
                               env=self.env, preexec_fn=default_sigpipe)

    def __run(self, args):
        """
        run self.cmd adding args as additional arguments

        Be verbose about errors and encode them in the return value, don't pass
        on exceptions.
        """
        try:
            retcode = self.__call(args)
            if retcode < 0:
                log.err("%s was terminated by signal %d" % (self.cmd,  -retcode))
            elif retcode > 0:
                log.err("%s returned %d" % (self.cmd,  retcode))
        except OSError, e:
            log.err("Execution failed: " + e.__str__())
            retcode = 1
        if retcode:
            log.err(self.run_error)
        self.retcode = retcode
        return retcode

    def __call__(self, args=[]):
        """Run the command, convert all errors into CommandExecFailed, assumes
        that the lower levels printed an error message - only useful if you
        only expect 0 as result
        >>> Command("/bin/true")(["foo", "bar"])
        >>> Command("/foo/bar")()
        Traceback (most recent call last):
        ...
        CommandExecFailed
        """
        if self.__run(args):
            raise CommandExecFailed

    def call(self, args):
        """like __call__ but don't use stderr and let the caller handle the return status
        >>> Command("/bin/true").call(["foo", "bar"])
        0
        >>> Command("/foo/bar").call(["foo", "bar"]) # doctest:+ELLIPSIS
        Traceback (most recent call last):
        ...
        CommandExecFailed: Execution failed: ...
        """
        try:
            ret = self.__call(args)
        except OSError, e:
            raise CommandExecFailed, "Execution failed: %s" % e
        return ret


class RunAtCommand(Command):
    """Run a command in a specific directory"""
    def __call__(self, dir='.', *args):
        curdir = os.path.abspath(os.path.curdir)
        try:
            os.chdir(dir)
            Command.__call__(self, list(*args))
            os.chdir(curdir)
        except Exception:
            os.chdir(curdir)
            raise


class PristineTar(Command):
    cmd='/usr/bin/pristine-tar'
    branch='pristine-tar'

    def __init__(self):
        if not os.access(self.cmd, os.X_OK):
            raise GbpError, "%s not found - cannot use pristine-tar" % self.cmd
        Command.__init__(self, self.cmd)

    def commit(self, archive, branch):
        self.run_error = 'Couldn\'t commit to "%s"' % branch
        self.__call__(['commit', archive, branch])

    def checkout(self, archive):
        self.run_error = 'Couldn\'t checkout "%s"' % os.path.basename(archive)
        self.__call__(['checkout', archive])


class UnpackTarArchive(Command):
    """Wrap tar to unpack a compressed tar archive"""
    def __init__(self, archive, dir, filters=[], compression=None):
        self.archive = archive
        self.dir = dir
        exclude = [("--exclude=%s" % filter) for filter in filters]

        if not compression:
            compression = '-a'

        Command.__init__(self, 'tar', exclude + ['-C', dir, compression, '-xf', archive ])
        self.run_error = 'Couldn\'t unpack "%s"' % self.archive


class PackTarArchive(Command):
    """Wrap tar to pack a compressed tar archive"""
    def __init__(self, archive, dir, dest, filters=[], compression=None):
        self.archive = archive
        self.dir = dir
        exclude = [("--exclude=%s" % filter) for filter in filters]

        if not compression:
            compression = '-a'

        Command.__init__(self, 'tar', exclude + ['-C', dir, compression, '-cf', archive, dest])
        self.run_error = 'Couldn\'t repack "%s"' % self.archive


class CatenateTarArchive(Command):
    """Wrap tar to catenate a tar file with the next"""
    def __init__(self, archive, **kwargs):
        self.archive = archive
        Command.__init__(self, 'tar', ['-A', '-f', archive], **kwargs)

    def __call__(self, target):
        Command.__call__(self, [target])


class RemoveTree(Command):
    "Wrap rm to remove a whole directory tree"
    def __init__(self, tree):
        self.tree = tree
        Command.__init__(self, 'rm', [ '-rf', tree ])
        self.run_error = 'Couldn\'t remove "%s"' % self.tree


class Dch(Command):
    """Wrap dch and set a specific version"""
    def __init__(self, version, msg):
        args = ['-v', version]
        if msg:
            args.append(msg)
        Command.__init__(self, 'dch', args)
        self.run_error = "Dch failed."


class DpkgSourceExtract(Command):
    """
    Wrap dpkg-source to extract a Debian source package into a certain
    directory, this needs
    """
    def __init__(self):
        Command.__init__(self, 'dpkg-source', ['-x'])

    def __call__(self, dsc, output_dir):
        self.run_error = 'Couldn\'t extract "%s"' % dsc
        Command.__call__(self, [dsc, output_dir])


class UnpackZipArchive(Command):
    """Wrap zip to Unpack a zip file"""
    def __init__(self, archive, dir):
        self.archive = archive
        self.dir = dir

        Command.__init__(self, 'unzip', [ "-q", archive, '-d', dir ])
        self.run_error = 'Couldn\'t unpack "%s"' % self.archive


class GitCommand(Command):
    "Mother/Father of all git commands"
    def __init__(self, cmd, args=[], **kwargs):
        Command.__init__(self, 'git', [cmd] + args, **kwargs)
        self.run_error = "Couldn't run git %s" % cmd


# FIXME: move to gbp.git.__init__
class GitClone(GitCommand):
    """Wrap git clone"""
    def __init__(self):
        GitCommand.__init__(self, 'clone')
        self.run_error = "Couldn't clone git repository"

# FIXME: move to  gbp.git.create_branch
class GitBranch(GitCommand):
    """Wrap git branch"""
    def __init__(self):
        GitCommand.__init__(self, 'branch')

    def __call__(self, branch, remote=None):
        self.run_error = 'Couldn\'t create branch "%s"' % (branch,)
        options = [branch]
        if remote:
            options += [ remote ]
        GitCommand.__call__(self, options)


# FIXME: move to gbp.git.fetch
class GitFetch(GitCommand):
    """Wrap git fetch"""
    def __init__(self, remote = None):
        opts = []
        if remote:
            opts += [remote]
        GitCommand.__init__(self, 'fetch', opts)


# FIXME: move to gbp.git.merge
class GitMerge(GitCommand):
    """Wrap git merge"""
    def __init__(self, branch, verbose=False):
        verbose = [ ['--no-summary'], [] ][verbose]
        GitCommand.__init__(self, 'merge', [branch] + verbose)
        self.run_error = 'Couldn\'t merge from "%s"' % (branch,)


# FIXME: move to gbp.git.create_tag
class GitTag(GitCommand):
    """Wrap git tag"""
    def __init__(self, sign_tag=False, keyid=None):
        GitCommand.__init__(self,'tag')
        self.sign_tag = sign_tag
        self.keyid = keyid

    def __call__(self, version, msg="Tagging %(version)s", commit=None):
        self.run_error = 'Couldn\'t tag "%s"' % (version,)
        if self.sign_tag:
            if self.keyid:
                sign_opts = [ '-u', self.keyid ]
            else:
                sign_opts = [ '-s' ]
        else:
            sign_opts = []
        cmd = sign_opts + [ '-m', msg % locals(), version]
        if commit:
            cmd += [ commit ]
        GitCommand.__call__(self, cmd)


def copy_from(orig_dir, filters=[]):
    """
    copy a source tree over via tar
    @param orig_dir: where to copy from
    @type orig_dir: string
    @param filters: tar exclude pattern
    @type filters: list of strings
    @return: list of copied files
    @rtype: list
    """
    exclude = [("--exclude=%s" % filter) for filter in filters]

    try:
        p1 = subprocess.Popen(["tar"] + exclude + ["-cSpf", "-", "." ], stdout=subprocess.PIPE, cwd=orig_dir)
        p2 = subprocess.Popen(["tar", "-xvSpf", "-" ], stdin=p1.stdout, stdout=subprocess.PIPE)
        files = p2.communicate()[0].split('\n')
    except OSError, err:
        raise GbpError, "Cannot copy files: %s" % err
    except ValueError, err:
        raise GbpError, "Cannot copy files: %s" % err
    if p1.wait() or p2.wait():
        raise GbpError, "Cannot copy files, pipe failed."
    return [ os.path.normpath(f) for f in files if files ]

# vim:et:ts=4:sw=4:et:sts=4:ai:set list listchars=tab\:»·,trail\:·:
