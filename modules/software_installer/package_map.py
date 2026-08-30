from __future__ import annotations

import re

# Local "known program -> how to install it" table. Keyed by a normalized
# lowercase name; the value maps a package-manager id per backend. A None
# means "this backend has no first-party package for it" (installer.py then
# falls through to flatpak/snap on Linux). Deliberately small and hand-kept
# — the common programs a person asks for by voice, not an exhaustive index.

_PackageIds = dict[str, str | None]

PACKAGE_MAP: dict[str, _PackageIds] = {
    "vlc": {"apt": "vlc", "dnf": "vlc", "pacman": "vlc", "flatpak": "org.videolan.VLC", "snap": "vlc", "winget": "VideoLAN.VLC"},
    "firefox": {"apt": "firefox", "dnf": "firefox", "pacman": "firefox", "flatpak": "org.mozilla.firefox", "snap": "firefox", "winget": "Mozilla.Firefox"},
    "chrome": {"apt": None, "dnf": None, "pacman": None, "flatpak": "com.google.Chrome", "snap": None, "winget": "Google.Chrome"},
    "chromium": {"apt": "chromium-browser", "dnf": "chromium", "pacman": "chromium", "flatpak": "org.chromium.Chromium", "snap": "chromium", "winget": "Hibbiki.Chromium"},
    "telegram": {"apt": None, "dnf": None, "pacman": "telegram-desktop", "flatpak": "org.telegram.desktop", "snap": "telegram-desktop", "winget": "Telegram.TelegramDesktop"},
    "discord": {"apt": None, "dnf": None, "pacman": "discord", "flatpak": "com.discordapp.Discord", "snap": "discord", "winget": "Discord.Discord"},
    "spotify": {"apt": None, "dnf": None, "pacman": None, "flatpak": "com.spotify.Client", "snap": "spotify", "winget": "Spotify.Spotify"},
    "obs": {"apt": "obs-studio", "dnf": "obs-studio", "pacman": "obs-studio", "flatpak": "com.obsproject.Studio", "snap": "obs-studio", "winget": "OBSProject.OBSStudio"},
    "gimp": {"apt": "gimp", "dnf": "gimp", "pacman": "gimp", "flatpak": "org.gimp.GIMP", "snap": "gimp", "winget": "GIMP.GIMP"},
    "inkscape": {"apt": "inkscape", "dnf": "inkscape", "pacman": "inkscape", "flatpak": "org.inkscape.Inkscape", "snap": "inkscape", "winget": "Inkscape.Inkscape"},
    "krita": {"apt": "krita", "dnf": "krita", "pacman": "krita", "flatpak": "org.kde.krita", "snap": "krita", "winget": "KDE.Krita"},
    "blender": {"apt": "blender", "dnf": "blender", "pacman": "blender", "flatpak": "org.blender.Blender", "snap": "blender", "winget": "BlenderFoundation.Blender"},
    "audacity": {"apt": "audacity", "dnf": "audacity", "pacman": "audacity", "flatpak": "org.audacityteam.Audacity", "snap": "audacity", "winget": "Audacity.Audacity"},
    "vscode": {"apt": None, "dnf": None, "pacman": None, "flatpak": "com.visualstudio.code", "snap": "code", "winget": "Microsoft.VisualStudioCode"},
    "libreoffice": {"apt": "libreoffice", "dnf": "libreoffice", "pacman": "libreoffice-fresh", "flatpak": "org.libreoffice.LibreOffice", "snap": "libreoffice", "winget": "TheDocumentFoundation.LibreOffice"},
    "steam": {"apt": "steam", "dnf": "steam", "pacman": "steam", "flatpak": "com.valvesoftware.Steam", "snap": "steam", "winget": "Valve.Steam"},
    "zoom": {"apt": None, "dnf": None, "pacman": None, "flatpak": "us.zoom.Zoom", "snap": "zoom-client", "winget": "Zoom.Zoom"},
    "thunderbird": {"apt": "thunderbird", "dnf": "thunderbird", "pacman": "thunderbird", "flatpak": "org.mozilla.Thunderbird", "snap": "thunderbird", "winget": "Mozilla.Thunderbird"},
    "keepassxc": {"apt": "keepassxc", "dnf": "keepassxc", "pacman": "keepassxc", "flatpak": "org.keepassxc.KeePassXC", "snap": "keepassxc", "winget": "KeePassXCTeam.KeePassXC"},
    "7zip": {"apt": "p7zip-full", "dnf": "p7zip", "pacman": "p7zip", "flatpak": None, "snap": None, "winget": "7zip.7zip"},
    "git": {"apt": "git", "dnf": "git", "pacman": "git", "flatpak": None, "snap": None, "winget": "Git.Git"},
    "htop": {"apt": "htop", "dnf": "htop", "pacman": "htop", "flatpak": None, "snap": None, "winget": None},
    "node": {"apt": "nodejs", "dnf": "nodejs", "pacman": "nodejs", "flatpak": None, "snap": "node", "winget": "OpenJS.NodeJS"},
    "python": {"apt": "python3", "dnf": "python3", "pacman": "python", "flatpak": None, "snap": None, "winget": "Python.Python.3.12"},
    "mpv": {"apt": "mpv", "dnf": "mpv", "pacman": "mpv", "flatpak": "io.mpv.Mpv", "snap": "mpv", "winget": "shinchiro.mpv"},
    "handbrake": {"apt": "handbrake", "dnf": "HandBrake-gui", "pacman": "handbrake", "flatpak": "fr.handbrake.ghb", "snap": None, "winget": "HandBrake.HandBrake"},
}

# Spoken/typed forms that aren't the canonical key.
_ALIASES: dict[str, str] = {
    "вэ эл си": "vlc", "в л ц": "vlc", "влц": "vlc",
    "фаерфокс": "firefox", "файрфокс": "firefox", "мозила": "firefox", "мозилла": "firefox",
    "гугл хром": "chrome", "google chrome": "chrome", "хром": "chrome",
    "хромиум": "chromium", "хромий": "chromium",
    "телеграм": "telegram", "телега": "telegram", "telegram desktop": "telegram",
    "дискорд": "discord",
    "спотифай": "spotify", "спотифи": "spotify",
    "обс": "obs", "obs studio": "obs",
    "гимп": "gimp",
    "инкскейп": "inkscape",
    "крита": "krita",
    "блендер": "blender",
    "аудасити": "audacity", "аудэсити": "audacity",
    "vs code": "vscode", "vscode": "vscode", "visual studio code": "vscode", "вс код": "vscode",
    "либре офис": "libreoffice", "либреофис": "libreoffice", "libre office": "libreoffice",
    "стим": "steam",
    "зум": "zoom",
    "тандерберд": "thunderbird",
    "кипас": "keepassxc", "keepass": "keepassxc",
    "семь зип": "7zip", "seven zip": "7zip", "7 zip": "7zip", "winrar": "7zip",
    "гит": "git",
    "нода": "node", "нодежс": "node", "nodejs": "node", "node js": "node",
    "питон": "python", "пайтон": "python", "python3": "python",
    "мпв": "mpv",
    "хендбрейк": "handbrake", "хэндбрейк": "handbrake",
}

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize(name: str) -> str:
    return _NON_WORD.sub("", name).strip().lower()


def resolve(name: str) -> str | None:
    """Maps a spoken program name to a PACKAGE_MAP key, or None when it
    isn't one this module knows how to install directly."""
    normalized = _normalize(name)
    if not normalized:
        return None
    if normalized in PACKAGE_MAP:
        return normalized
    if normalized in _ALIASES:
        return _ALIASES[normalized]
    # Tolerate a trailing filler word ("установи вэлси плеер").
    collapsed = normalized.replace(" ", "")
    for key in PACKAGE_MAP:
        if collapsed == key.replace(" ", ""):
            return key
    for alias, key in _ALIASES.items():
        if collapsed == alias.replace(" ", ""):
            return key
    return None


def package_ids(key: str) -> _PackageIds:
    return PACKAGE_MAP[key]
