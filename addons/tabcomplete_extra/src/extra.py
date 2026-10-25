from leapsh.api import Addon

TOOLS = {
    "docker": ["run", "ps", "images", "build", "pull", "push", "exec", "logs", "stop", "start", "restart", "rm", "rmi",
               "compose", "network", "volume", "inspect", "login", "tag", "cp"],
    "npm": ["install", "run", "start", "test", "init", "update", "uninstall", "ls", "publish", "audit", "ci", "outdated"],
    "pip": ["install", "uninstall", "list", "show", "freeze", "search", "download", "check", "config", "cache"],
    "pip3": ["install", "uninstall", "list", "show", "freeze", "download", "check"],
    "cargo": ["build", "run", "test", "check", "new", "init", "add", "update", "clippy", "fmt", "doc", "publish", "install"],
    "systemctl": ["start", "stop", "restart", "status", "enable", "disable", "reload", "daemon-reload", "is-active", "list-units"],
}


class TabcompleteExtra(Addon):
    def on_load(self):
        self.extend("tab_providers", self.add_tools)

    def add_tools(self, providers, **ctx):
        for tool, subs in TOOLS.items():
            providers.setdefault(tool, lambda c, s=subs: s if c.n == 1 else None)
        providers.setdefault("python", lambda c: ["-m", "-c", "-V", "-h"] if c.n == 1 and c.word.startswith("-") else None)
        providers.setdefault("python3", providers["python"])
        return providers
