"""Systém událostí – základ celého pluginového systému."""

KNOWN_EVENTS = {
    "startup": "shell se spustil (interactive)",
    "shutdown": "shell se ukončuje",
    "prompt_before": "těsně před vykreslením promptu",
    "prompt_render": "hotový prompt; změň ev.data['prompt']",
    "idle": "uživatel nic nepíše (seconds, editor); po obsluze zavolej editor.reset_idle()",
    "key": "stisk klávesy (key, char, buffer, cursor, editor); ev.cancel() zruší výchozí akci",
    "input_change": "uživatel mění text na řádku (buffer, previous, cursor, editor)",
    "input_render": "vykreslení řádku; ghost = šedý návrh, styler = funkce text->obarvený text",
    "complete": "doplňování tabulátorem (word, first, candidates); přidej do ev.data['candidates']",
    "command_before": "před spuštěním příkazu (line); lze změnit ev.data['line'] nebo ev.cancel()",
    "command_after": "po dokončení příkazu (line, command, rc, duration)",
    "command_not_found": "příkaz neexistuje (line, command)",
    "dir_change": "změna adresáře (old, new)",
    "theme_change": "změna tématu (old, new)",
    "config_change": "změna config.json (key, old, new) – příkaz config set",
    "plugin_setting_change": "změna nastavení pluginu (plugin, key, old, new)",
    "plugin_loaded": "plugin/addon načten (name, kind)",
    "plugin_unloaded": "plugin/addon odebrán (name, kind)",
    "*": "wildcard: dostane všechny události",
}


class Event:
    def __init__(self, name, data):
        self.name = name
        self.data = data
        self.cancelled = False
        self.stopped = False

    def cancel(self):
        """Zruší výchozí akci (např. spuštění příkazu nebo zpracování klávesy)."""
        self.cancelled = True

    def stop(self):
        """Zastaví předávání události dalším handlerům."""
        self.stopped = True

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key):
        return self.data[key]

    def __getattr__(self, item):
        data = self.__dict__.get("data", {})
        if item in data:
            return data[item]
        raise AttributeError(item)


class EventBus:
    def __init__(self, on_error=None):
        self._handlers = {}
        self._seq = 0
        self.on_error = on_error

    def on(self, name, fn, priority=0, owner=None):
        """Registruje handler. Vyšší priority běží dřív."""
        self._seq += 1
        lst = self._handlers.setdefault(name, [])
        lst.append((-priority, self._seq, fn, owner))
        lst.sort(key=lambda h: (h[0], h[1]))
        return fn

    def off(self, name=None, fn=None, owner=None):
        for ev_name in list(self._handlers):
            if name is not None and ev_name != name:
                continue
            self._handlers[ev_name] = [
                h for h in self._handlers[ev_name]
                if not ((fn is None or h[2] is fn) and (owner is None or h[3] == owner)
                        and (fn is not None or owner is not None))
            ]

    def emit(self, event_name, /, **data):
        name = event_name
        ev = Event(name, data)
        handlers = list(self._handlers.get(name, [])) + list(self._handlers.get("*", []))
        for _, _, fn, owner in handlers:
            if ev.stopped:
                break
            try:
                fn(ev)
            except Exception as exc:  # plugin nesmí shodit shell
                if self.on_error:
                    self.on_error(owner or "?", f"event:{name}", exc)
        return ev

    def count(self, name):
        return len(self._handlers.get(name, []))

    def owned_by(self, owner):
        out = {}
        for ev_name, lst in self._handlers.items():
            n = sum(1 for h in lst if h[3] == owner)
            if n:
                out[ev_name] = n
        return out
