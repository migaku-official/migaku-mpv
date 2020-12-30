import platform


# Windows
if platform.system() == 'Windows':

    import winreg

    def get_exe_path_registry(exe_name):

        key_path = 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\%s.exe' % exe_name
        try:
            reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(reg_key, '')
            winreg.CloseKey(reg_key)
            return value
        except WindowsError:
            return None

    def expand_browser_name(name):

        name_lower = name.lower()

        associations = {
            'chrome':   'chrome',
            'edge':     'msedge',
        }

        if name_lower not in associations:
            return name

        exe_name = associations[name_lower]
        exe_path = get_exe_path_registry(exe_name)

        if exe_path is None:
            return name

        exe_path = exe_path.replace('\\', '/')
        exe_command = exe_path + ' %s &'

        return exe_command


# MacOS
elif platform.system() == 'Darwin':

    def expand_browser_name(name):
        
        associations = {
            'chrome':   '/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome %s &',
        }

        name_lower = name.lower()

        if name_lower in associations:
            return associations[name_lower]

        return name


# Non Windows
else:

    def expand_browser_name(name):
        return name
