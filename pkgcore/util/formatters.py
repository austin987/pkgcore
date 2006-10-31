# Copyright: 2006 Marien Zwart <marienz@gentoo.org>
# License: GPL2

"""Classes wrapping a file-like object to do fancy output on it."""

import os
import errno


class StreamClosed(KeyboardInterrupt):
    """Raised by L{Formatter.write} if the stream it prints to was closed.

    This inherits from C{KeyboardInterrupt} because it should usually
    be handled the same way: a common way of triggering this exception
    is by closing a pager before the script finished outputting, which
    should be handled like control+c, not like an error.
    """


# "Invalid name" (for fg and bg methods, too short)
# pylint: disable-msg=C0103


class Formatter(object):

    """Abstract formatter base class.

    The types of most of the instance attributes is undefined (depends
    on the implementation of the particular Formatter subclass).

    @ivar bold: object to pass to L{write} to switch to bold mode.
    @ivar underline: object to pass to L{write} to switch to underlined mode.
    @ivar reset: object to pass to L{write} to turn off bold and underline.
    @ivar wrap: boolean indicating we auto-linewrap (defaults to off).
    @ivar autoline: boolean indicating we are in auto-newline mode
        (defaults to on).
    """

    def __init__(self):
        self.autoline = True
        self.wrap = False

    def write(self, *args, **kwargs):
        """Write something to the stream.

        Acceptable arguments are:
          - Strings are simply written to the stream.
          - C{None} is ignored.
          - Functions are called with the formatter as argument.
            Their return value is then used the same way as the other
            arguments.
          - Formatter subclasses might special-case certain objects.

        Also accepts wrap and autoline as keyword arguments. Effect is
        the same as setting them before the write call and resetting
        them afterwards.

        The formatter has a couple of attributes that are useful as argument
        to write.
        """

    def fg(self, color=None):
        """Change foreground color.

        @type  color: a string or C{None}.
        @param color: color to change to. A default is used if omitted.
                      C{None} resets to the default color.
        """

    def bg(self, color=None):
        """Change background color.

        @type  color: a string or C{None}.
        @param color: color to change to. A default is used if omitted.
                      C{None} resets to the default color.
        """


class PlainTextFormatter(Formatter):

    """Formatter writing plain text to a file-like object.

    @ivar width: contains the current maximum line length.
    """

    bold = underline = reset = ''

    def __init__(self, stream, width=79):
        """Initialize.

        @type  stream: file-like object.
        @param stream: stream to output to.
        @param width: maximum line width.
        """
        Formatter.__init__(self)
        self.stream = stream
        self.width = width
        self._pos = 0
        self._in_first_line = True
        self._wrote_something = False
        self.first_prefix = ['']
        self.later_prefix = ['']


    def _write_prefix(self, wrap):
        if self._in_first_line:
            prefix = self.first_prefix
        else:
            prefix = self.later_prefix
        # This is a bit braindead since it duplicates a lot of code
        # from write. Avoids fun things like word wrapped prefix though.

        # Work if encoding is not set or is set to the empty string
        encoding = getattr(self.stream, 'encoding', '') or 'ascii'
        for thing in prefix:
            while callable(thing):
                thing = thing(self)
            if thing is None:
                continue
            if not isinstance(thing, basestring):
                thing = str(thing)
            self._pos += len(thing)
            if isinstance(thing, unicode):
                thing = thing.encode(encoding, 'replace')
            self.stream.write(thing)
        if wrap and self._pos >= self.width:
            # XXX What to do? Our prefix does not fit.
            # This makes sure we still output something,
            # but it is completely arbitrary.
            self._pos = self.width - 10


    def write(self, *args, **kwargs):
        # Work if encoding is not set or is set to the empty string
        encoding = getattr(self.stream, 'encoding', '') or 'ascii'
        wrap = kwargs.get('wrap', self.wrap)
        autoline = kwargs.get('autoline', self.autoline)
        try:
            for arg in args:
                # If we're at the start of the line, write our prefix.
                # There is a deficiency here: if neither our arg nor our
                # prefix affect _pos (both are escape sequences or empty)
                # we will write prefix more than once. This should not
                # matter.
                if not self._pos:
                    self._write_prefix(wrap)
                while callable(arg):
                    arg = arg(self)
                if arg is None:
                    continue
                if not isinstance(arg, basestring):
                    arg = str(arg)
                is_unicode = isinstance(arg, unicode)
                while wrap and self._pos + len(arg) > self.width:
                    # We have to split.
                    maxlen = self.width - self._pos
                    space = arg.rfind(' ', 0, maxlen)
                    if space == -1:
                        # No space to split on.

                        # If we are on the first line we can simply go to
                        # the next (this helps if the "later" prefix is
                        # shorter and should not really matter if not).

                        # If we are on the second line and have already
                        # written something we can also go to the next
                        # line.
                        if self._in_first_line or self._wrote_something:
                            bit = ''
                        else:
                            # Forcibly split this as far to the right as
                            # possible.
                            bit = arg[:maxlen]
                            arg = arg[maxlen:]
                    else:
                        bit = arg[:space]
                        # Omit the space we split on.
                        arg = arg[space+1:]
                    if isinstance(bit, unicode):
                        bit = bit.encode(encoding, 'replace')
                    self.stream.write(bit)
                    self.stream.write('\n')
                    self._pos = 0
                    self._in_first_line = False
                    self._wrote_something = False
                    self._write_prefix(wrap)

                # This fits.
                self._wrote_something = True
                self._pos += len(arg)
                if is_unicode:
                    arg = arg.encode(encoding, 'replace')
                self.stream.write(arg)
            if autoline:
                self.stream.write('\n')
                self._wrote_something = False
                self._pos = 0
                self._in_first_line = True
        except IOError, e:
            if e.errno == errno.EPIPE:
                raise StreamClosed(e)
            raise

    def fg(self, color=None):
        return ''

    def bg(self, color=None):
        return ''


# This is necessary because the curses module is optional (and we
# should run on a very minimal python for bootstrapping).
try:
    import curses
except ImportError:
    TerminfoColor = None
else:
    class TerminfoColor(object):

        def __init__(self, mode, color):
            self.mode = mode
            self.color = color

        def __call__(self, formatter):
            if self.color is None:
                formatter._current_colors[self.mode] = None
                res = formatter._color_reset
                # slight abuse of boolean True/False and 1/0 equivalence
                other = formatter._current_colors[not self.mode]
                if other is not None:
                    res = res + other
            else:
                if self.mode == 0:
                    default = curses.COLOR_WHITE
                else:
                    default = curses.COLOR_BLACK
                color = formatter._colors.get(self.color, default)
                # The curses module currently segfaults if handed a
                # bogus template so check explicitly.
                template = formatter._set_color[self.mode]
                if template:
                    res = curses.tparm(template, color)
                else:
                    res = ''
                formatter._current_colors[self.mode] = res
            formatter.stream.write(res)


    class TerminfoCode(object):
        def __init__(self, value):
            self.value = value

    class TerminfoMode(TerminfoCode):
        def __call__(self, formatter):
            formatter._modes.add(self)
            formatter.stream.write(self.value)

    class TerminfoReset(TerminfoCode):
        def __call__(self, formatter):
            formatter._modes.clear()
            formatter.stream.write(self.value)


    class TerminfoFormatter(PlainTextFormatter):

        """Formatter writing to a tty, using terminfo to do colors."""

        _colors = dict(
            black = curses.COLOR_BLACK,
            red = curses.COLOR_RED,
            green = curses.COLOR_GREEN,
            yellow = curses.COLOR_YELLOW,
            blue = curses.COLOR_BLUE,
            magenta = curses.COLOR_MAGENTA,
            cyan = curses.COLOR_CYAN,
            white = curses.COLOR_WHITE)

        def __init__(self, stream, term=None, forcetty=False):
            """Initialize.

            @type  stream: file-like object.
            @param stream: stream to output to, defaulting to C{sys.stdout}.
            @type  term: string.
            @param term: terminal type, pulled from the environment if omitted.
            @type  forcetty: bool
            @param forcetty: force output of colors even if the wrapped stream
                             is not a tty.
            """
            PlainTextFormatter.__init__(self, stream)
            fd = stream.fileno()
            curses.setupterm(fd=fd, term=term)
            self.width = curses.tigetnum('cols')
            self.reset = TerminfoReset(curses.tigetstr('sgr0'))
            self.bold = TerminfoMode(curses.tigetstr('bold'))
            self.underline = TerminfoMode(curses.tigetstr('smul'))
            self._color_reset = curses.tigetstr('op')
            self._set_color = (
                curses.tigetstr('setaf'), curses.tigetstr('setab'))
            self._width = curses.tigetstr('cols')
            # [fg, bg]
            self._current_colors = [None, None]
            self._modes = set()
            self._pos = 0

        def fg(self, color=None):
            return TerminfoColor(0, color)

        def bg(self, color=None):
            return TerminfoColor(1, color)

        def write(self, *args, **kwargs):
            try:
                PlainTextFormatter.write(self, *args, **kwargs)
                if self._modes:
                    self.reset(self)
                if self._current_colors != [None, None]:
                    self._current_colors = [None, None]
                    self.stream.write(self._color_reset)
            except IOError, e:
                if e.errno == errno.EPIPE:
                    raise StreamClosed(e)
                raise

class ObserverFormatter(object):

    def __init__(self, real_formatter):
        self._formatter = real_formatter

    def write(self, *args):
        self._formatter.write(autoline=False, *args)

    def __getattr__(self, attr):
        return getattr(self._formatter, attr)


def get_formatter(stream):
    """TerminfoFormatter if the stream is a tty, else PlainTextFormatter."""
    if TerminfoColor is None:
        return PlainTextFormatter(stream)
    try:
        fd = stream.fileno()
    except AttributeError:
        pass
    else:
        # We do this instead of stream.isatty() because TerminfoFormatter
        # needs an fd to pass to curses, not just a filelike talking to a tty.
        if os.isatty(fd):
            try:
                return TerminfoFormatter(stream)
            except curses.error:
                # This happens if TERM is unset and possibly in more cases.
                # Just fall back to the PlainTextFormatter.
                pass
    return PlainTextFormatter(stream)
