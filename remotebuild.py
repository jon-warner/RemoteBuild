import sublime
import sublime_plugin
import subprocess
import Queue
import re
import threading
import traceback


def get_settings():
    return sublime.load_settings("RemoteBuild.sublime-settings")


def get_setting(key, default=None):
    try:
        s = sublime.active_window().active_view().settings()
        if s.has(key):
            return s.get(key)
    except:
        pass
    return get_settings().get(key, default)

class RemoteBuildView(object):
    LINE = 0
    FOLD_ALL = 1
    CLEAR = 2
    SCROLL = 3
    VIEWPORT_POSITION = 4

    def __init__(self):
        self.queue = Queue.Queue()
        self.name = "RemoteBuild"
        self.closed = True
        self.view = None
        self.last_fold = None
        self.timer = None
        self.lines = ""
        self.lock = threading.RLock()

    def is_open(self):
        return not self.closed

    def open(self):
        if self.view == None or self.view.window() == None:
            self.create_view()
        self.maxlines = get_setting("remotebuild_maxlines", 20000)
        self.filter = re.compile(get_setting("remotebuild_filter", "."))
        self.doScroll = get_setting("remotebuild_auto_scroll", True)
        self.remote_host = get_setting("remotebuild_remote_host","")
        self.remote_directory = get_setting("remotebuild_directory", "")
        self.remote_setup_command = get_setting("remotebuild_setup_command", "")
        self.remote_build_command = get_setting("remotebuild_build_command", "")

    def timed_add(self):
        try:
            self.lock.acquire()
            line = self.lines
            self.lines = ""
            self.timer = None
            self.queue.put((RemoteBuildView.LINE, line))
            sublime.set_timeout(self.update, 0)
        finally:
            self.lock.release()

    def add_line(self, line):
        if self.is_open():
            try:
                self.lock.acquire()
                self.lines += line
                if self.timer:
                    self.timer.cancel()
                if self.lines.count("\n") > 10:
                    self.timed_add()
                else:
                    self.timer = threading.Timer(0.1, self.timed_add)
                    self.timer.start()
            finally:
                self.lock.release()

    def scroll(self, line):
        if self.is_open():
            self.queue.put((RemoteBuildView.SCROLL, line))
            sublime.set_timeout(self.update, 0)

    def set_viewport_position(self, pos):
        if self.is_open():
            self.queue.put((RemoteBuildView.VIEWPORT_POSITION, pos))
            sublime.set_timeout(self.update, 0)

    def clear(self):
        if self.is_open():
            self.queue.put((RemoteBuildView.CLEAR, None))
            sublime.set_timeout(self.update, 0)

    def set_filter(self, filter):
        try:
            self.filter = re.compile(filter)
            self.apply_filter(self.view)
        except:
            sublime.error_message("invalid regex")

    def apply_filter(self, view):
        if is_remotebuild_syntax(view):
            view.run_command("unfold_all")
            endline, endcol = view.rowcol(view.size())
            line = 0
            currRegion = None
            regions = []
            while line < endline:
                region = view.full_line(view.text_point(line, 0))
                data = view.substr(region)
                if self.filter.search(data) == None:
                    if currRegion == None:
                        currRegion = region
                    else:
                        currRegion = currRegion.cover(region)
                else:
                    if currRegion:
                        # The -1 is to not include the \n and thus making the fold ... appear
                        # at the end of the last line in the fold, rather than at the
                        # beginning of the "accepted" line
                        currRegion = sublime.Region(currRegion.begin()-1, currRegion.end()-1)
                        regions.append(currRegion)
                        currRegion = None
                line += 1
            if currRegion:
                regions.append(currRegion)
            view.fold(regions)
            self.last_fold = currRegion

    def create_view(self):
        self.view = sublime.active_window().new_file()
        self.view.set_name(self.name)
        self.view.set_scratch(True)
        self.view.set_read_only(True)
        self.view.set_syntax_file("Packages/RemoteBuild/remotebuild.tmLanguage")
        self.closed = False

    def is_closed(self):
        return self.closed

    def was_closed(self):
        self.closed = True

    def fold_all(self):
        if self.is_open():
            self.queue.put((RemoteBuildView.FOLD_ALL, None))

    def get_view(self):
        return self.view

    def update(self):
        if not self.is_open():
            return
        try:
            while True:
                cmd, data = self.queue.get_nowait()
                if cmd == RemoteBuildView.LINE:
                    for line in data.split("\n"):
                        if len(line.strip()) == 0:
                            continue
                        line += "\n"
                        row, col = self.view.rowcol(self.view.size())
                        e = self.view.begin_edit()
                        self.view.set_read_only(False)

                        if row+1 > self.maxlines:
                            self.view.erase(e, self.view.full_line(0))
                        self.view.insert(e, self.view.size(), line)
                        self.view.end_edit(e)
                        self.view.set_read_only(True)

                        if self.filter.search(line) == None:
                            region = self.view.line(self.view.size()-1)
                            if self.last_fold != None:
                                self.view.unfold(self.last_fold)
                                self.last_fold = self.last_fold.cover(region)
                            else:
                                self.last_fold = region
                            foldregion = sublime.Region(self.last_fold.begin()-1, self.last_fold.end())
                            self.view.fold(foldregion)
                        else:
                            self.last_fold = None
                elif cmd == RemoteBuildView.FOLD_ALL:
                    self.view.run_command("fold_all")
                elif cmd == RemoteBuildView.CLEAR:
                    self.view.set_read_only(False)
                    e = self.view.begin_edit()
                    self.view.erase(e, sublime.Region(0, self.view.size()))
                    self.view.end_edit(e)
                    self.view.set_read_only(True)
                elif cmd == RemoteBuildView.SCROLL:
                    self.view.run_command("goto_line", {"line": data + 1})
                elif cmd == RemoteBuildView.VIEWPORT_POSITION:
                    self.view.set_viewport_position(data, True)
                self.queue.task_done()
        except Queue.Empty:
            # get_nowait throws an exception when there's nothing..
            pass
        except:
            traceback.print_exc()
        finally:
            if self.doScroll:
                self.view.show(self.view.size())


remotebuild_view = RemoteBuildView()
remotebuild_process = None

def untilprompt(proc, strinput = None):
    if strinput:
        remotebuild_process.stdin.write(strinput+'\n')
        remotebuild_process.stdin.flush()
    buff = ''
    while remotebuild_process.poll() == None:

        outputstr = remotebuild_process.stdout.read(1)
        buff += outputstr
        remotebuild_view.add_line("%s\n" % buff)

        if buff[-2:-1] == '$ ':
            break
    return buff

def output():
    """
    cmd = ''
    try:
        cmd = (yield untilprompt(p,cmd))
    except Exception as e:
        print e
    """
    cmd = 'cd '
    cmd += remotebuild_view.remote_directory

    remotebuild_process.stdin.write(cmd+'\n')
    """remotebuild_view.add_line("%s\n" % cmd)"""
    """untilprompt(remotebuild_process, cmd)"""

    cmd = remotebuild_view.remote_setup_command
    remotebuild_process.stdin.write(cmd+'\n')
    """remotebuild_view.add_line("%s\n" % cmd)"""
    """untilprompt(remotebuild_process, cmd)"""

    cmd = remotebuild_view.remote_build_command
    remotebuild_process.stdin.write(cmd+'\n')
    """remotebuild_view.add_line("%s\n" % cmd)"""
    """untilprompt(remotebuild_process, cmd)"""

    while True:
        try:
            if remotebuild_process.poll() != None:
                break
            line = remotebuild_process.stdout.readline().strip()

            if len(line) > 0:
                remotebuild_view.add_line("%s\n" % line)
        except:
            traceback.print_exc()


def is_remotebuild_syntax(view):
    sn = view.scope_name(view.sel()[0].a)
    return sn.startswith("source.remotebuild")

class RemoteBuildGotoFileLine(sublime_plugin.TextCommand):
    def run(self, edit):
        data = self.view.substr(self.view.full_line(self.view.sel()[0].a))
        match = re.match(r"^(.*)(.*)(.*)", data)
        file_and_line = ''
        if match != None:
            file_and_line =  match.group(1);
            print file_and_line
        else:
            sublime.error_message("Couldn't extract file and line")

    def is_enabled(self):
        return is_remotebuild_syntax(self.view) or (remotebuild_view.is_open() and remotebuild_view.get_view().id() == self.view.id())

    def is_visible(self):
        return self.is_enabled()

class RemoteBuildClearView(sublime_plugin.TextCommand):
    def run(self, edit):
        remotebuild_view.clear()
        cmd = remotebuild_view.remote_build_command
        remotebuild_process.stdin.write(cmd+'\n')

    def is_enabled(self):
        return is_remotebuild_syntax(self.view) or (remotebuild_view.is_open() and remotebuild_view.get_view().id() == self.view.id())

    def is_visible(self):
        return self.is_enabled()


class RemoteBuildFilterByProcessId(sublime_plugin.TextCommand):
    def run(self, edit):
        data = self.view.substr(self.view.full_line(self.view.sel()[0].a))
        match = re.match(r"[\-\d\s:.]*./.+\( *(\d+)\)", data)
        if match != None:
            remotebuild_view.set_filter("\( *%s\)" % match.group(1))
        else:
            sublime.error_message("Couldn't extract process id")

    def is_enabled(self):
        return is_remotebuild_syntax(self.view) or (remotebuild_view.is_open() and remotebuild_view.get_view().id() == self.view.id())

    def is_visible(self):
        return self.is_enabled()


class RemoteBuildFilterByProcessName(sublime_plugin.TextCommand):
    def run(self, edit):
        data = self.view.substr(self.view.full_line(self.view.sel()[0].a))
        match = re.match(r"[\-\d\s:.]*./(.+)\( *\d+\)", data)
        if match != None:
            remotebuild_view.set_filter("%s\( *\d+\)" % match.group(1))
        else:
            sublime.error_message("Couldn't extract process name")

    def is_enabled(self):
        return is_remotebuild_syntax(self.view) or (remotebuild_view.is_open() and remotebuild_view.get_view().id() == self.view.id())

    def is_visible(self):
        return self.is_enabled()


class RemoteBuildFilterByMessageLevel(sublime_plugin.TextCommand):
    def run(self, edit):
        data = self.view.substr(self.view.full_line(self.view.sel()[0].a))
        match = re.match(r"[\-\d\s:.]*(\w)/.+\( *\d+\)", data)
        if match != None:
            remotebuild_view.set_filter("%s/.+\( *\d+\)" % match.group(1))
        else:
            sublime.error_message("Couldn't extract Message level")

    def is_enabled(self):
        return is_remotebuild_syntax(self.view) or (remotebuild_view.is_open() and remotebuild_view.get_view().id() == self.view.id())

    def is_visible(self):
        return self.is_enabled()


class RemoteBuildLaunch(sublime_plugin.WindowCommand):
    def run(self):
        global remotebuild_process
        if remotebuild_process != None and remotebuild_process.poll() == None:
            remotebuild_process.kill()
        cmd = get_setting("remotebuild_command", "plink")
        cmd += " "
        cmd += get_setting("remotebuild_userid", "")
        cmd += "@"
        cmd += get_setting("remotebuild_remote_host", "")
        cmd += " -pw "
        cmd += get_setting("remotebuild_password")
        print "running: %s" % cmd
        remotebuild_process = subprocess.Popen(cmd, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE)
        remotebuild_view.open()
        t = threading.Thread(target=output)
        t.start()

    def is_enabled(self):
        return not (remotebuild_view.is_open() and remotebuild_view.view.window() != None)


class RemoteBuildSetFilter(sublime_plugin.WindowCommand):
    def set_filter(self, data):
        remotebuild_view.set_filter(data)

    def run(self):
        self.window.show_input_panel("RemoteBuild Regex filter", remotebuild_view.filter.pattern, self.set_filter, None, None)

    def is_enabled(self):
        return is_remotebuild_syntax(sublime.active_window().active_view()) or (remotebuild_process != None and remotebuild_view.is_open())

    def is_visible(self):
        return self.is_enabled()


class RemoteBuildClearView(sublime_plugin.WindowCommand):
    def run(self):
        remotebuild_view.clear()

    def is_enabled(self):
        return remotebuild_process != None and remotebuild_view.is_open()

    def is_visible(self):
        return self.is_enabled()


class RemoteBuildEventListener(sublime_plugin.EventListener):
    def on_close(self, view):
        if remotebuild_view.is_open() and view.id() == remotebuild_view.get_view().id():
            remotebuild_view.was_closed()
            remotebuild_process.kill()
