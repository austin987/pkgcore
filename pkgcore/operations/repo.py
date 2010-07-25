# Copyright: 2005-2008 Brian Harring <ferringb@gmail.com>
# License: GPL2/BSD

"""
repository modifications (installing, removing, replacing)
"""

from snakeoil.dependant_methods import ForcedDepends
from snakeoil.weakrefs import WeakRefFinalizer
from snakeoil.demandload import demandload
from snakeoil.currying import partial, post_curry
demandload(globals(), "pkgcore.log:logger",
    "pkgcore.operations:observer@observer_mod",
    "pkgcore:sync",
    "pkgcore.package.mutated:MutatedPkg",
    )


class fake_lock(object):
    def __init__(self):
        pass

    acquire_write_lock = acquire_read_lock = __init__
    release_read_lock = release_write_lock = __init__


class finalizer_base(WeakRefFinalizer, ForcedDepends):

    pass

class Failure(Exception):
    pass


class base(object):

    __metaclass__ = ForcedDepends

    stage_depends = {}

    def __init__(self, repo, observer):
        self.repo = repo
        self.underway = False
        self.observer = observer
        try:
            self.lock = getattr(repo, "lock")
        except AttributeError:
            raise
        if self.lock is None:
            self.lock = fake_lock()

    def start(self):
        self.underway = True
        self.lock.acquire_write_lock()
        return True

    def finalize_data(self):
        raise NotImplementedError(self, 'finalize_data')

    def finish(self):
        self.lock.release_write_lock()
        self.underway = False
        return True


class install(base):

    stage_depends = {'finish': '_notify_repo_add',
        '_notify_repo_add': 'finalize_data',
        'finalize_data': 'add_data',
        'add_data':'start'}

    def __init__(self, repo, pkg, observer):
        base.__init__(self, repo, observer)
        self.new_pkg = pkg

    def _notify_repo_add(self):
        self.repo.notify_add_package(self.new_pkg)
        return True

    def add_data(self):
        raise NotImplementedError(self, 'add_data')

    def _update_pkg_contents(self, contents):
        self.new_pkg = MutatedPkg(self.new_pkg,
            {"contents":contents})


class uninstall(base):

    stage_depends = {'finish': '_notify_repo_remove',
        '_notify_repo_remove': 'finalize_data',
        'finalize_data': 'remove_data',
        'remove_data':'start'}

    def __init__(self, repo, pkg, observer):
        base.__init__(self, repo, observer)
        self.old_pkg = pkg

    def _notify_repo_remove(self):
        self.repo.notify_remove_package(self.old_pkg)
        return True

    def remove_data(self):
        raise NotImplementedError(self, 'remove_data')


class replace(install, uninstall):

    stage_depends = {'finish': '_notify_repo_add',
        '_notify_repo_add': 'finalize_data',
        'finalize_data': ('add_data', '_notify_repo_remove'),
        '_notify_repo_remove': 'remove_data',
        'remove_data': 'start',
        'add_data': 'start'}

    def __init__(self, repo, oldpkg, newpkg, observer):
        # yes there is duplicate initialization here.
        uninstall.__init__(self, repo, oldpkg, observer)
        install.__init__(self, repo, newpkg, observer)


class operations(object):

    def __init__(self, repository, disable_overrides=(), enable_overrides=()):
        self.repo = repository
        enabled_ops = set(self._filter_disabled_commands(
            self._collect_operations()))
        enabled_ops.update(enable_overrides)
        enabled_ops.difference_update(disable_overrides)

        for op in enabled_ops:
            self._enable_operation(op)

        self._enabled_ops = frozenset(enabled_ops)

    def _filter_disabled_commands(self, sequence):
        for command in sequence:
            check_f = getattr(self, '_cmd_check_support_%s' % command, None)
            if check_f is not None and not check_f():
                continue
            yield command

    def _enable_operation(self, operation):
        setattr(self, operation,
            getattr(self, '_cmd_enabled_%s' % operation))

    def _disabled_if_frozen(self, command):
        if self.repo.frozen:
            logger.debug("disabling repo(%r) command(%r) due to repo being frozen",
                self.repo, command)
        return not self.repo.frozen

    @classmethod
    def _collect_operations(cls):
        for x in dir(cls):
            if x.startswith("_cmd_") and not x.startswith("_cmd_enabled_") \
                and not x.startswith("_cmd_check_support_"):
                yield x[len("_cmd_"):]

    def supports(self, operation_name=None, raw=False):
        if not operation_name:
            if not raw:
                return self._enabled_ops
            return frozenset(self._collect_operations())
        if raw:
            return hasattr(self, '_cmd_enabled_%s' % operation_name)
        return hasattr(self, operation_name)

    #def __dir__(self):
    #    return list(self._enabled_ops)

    def _default_observer(self, observer):
        if observer is None:
            observer = observer_mod.repo_observer()
        return observer

    def _cmd_enabled_install(self, pkg, observer=None):
        return self._cmd_install(pkg,
            self._default_observer(observer))

    def _cmd_enabled_uninstall(self, pkg, observer=None):
        return self._cmd_uninstall(pkg,
            self._default_observer(observer))

    def _cmd_enabled_replace(self, oldpkg, newpkg, observer=None):
        return self._cmd_replace(oldpkg, newpkg,
            self._default_observer(observer))

    for x in ("install", "uninstall", "replace"):
        locals()["_cmd_check_support_%s" % x] = post_curry(
            _disabled_if_frozen, x)

    del x

    def _cmd_enabled_configure(self, pkg, observer=None):
        return self._cmd_configure(self.repository, pkg,
            self._default_observer(observer))

    def _cmd_enabled_sync(self, observer=None):
        # often enough, the syncer is a lazy_ref
        return self._cmd_sync(self._default_observer(observer))

    def _cmd_sync(self, observer):
        return self._get_syncer().sync()
        return syncer.sync()

    def _get_syncer(self):
        syncer = self.repo._syncer
        if not isinstance(syncer, sync.base.syncer):
            syncer = syncer.instantiate()
        return syncer

    def _cmd_check_support_sync(self):
        return getattr(self.repo, '_syncer', None) is not None \
            and not self._get_syncer().disabled


class operations_proxy(operations):

    def __init__(self, repository, *args, **kwds):
        self.repo = repository
        for attr in self._get_target_attrs():
            if attr.startswith("_cmd_"):
                if attr.startswith("_cmd_check_support_"):
                    setattr(self, attr, partial(self._proxy_op_support, attr))
                elif not attr.startswith("_cmd_enabled_"):
                    setattr(self, attr, partial(self._proxy_op, attr))
        operations.__init__(self, repository, *args, **kwds)

    def _get_target_attrs(self):
        return dir(self.repo.raw_repo.operations)

    def _proxy_op(self, op_name, *args, **kwds):
        return getattr(self.repo.raw_repo.operations, op_name)(*args, **kwds)

    _proxy_op_support = _proxy_op

    def _collect_operations(self):
        return self.repo.raw_repo.operations._collect_operations()