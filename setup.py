from py2app.build_app import py2app as _py2app
from setuptools import setup


class py2app(_py2app):
    """py2app subclass that clears install_requires before finalize_options.

    setuptools populates install_requires from pyproject.toml's
    [project] dependencies, but py2app 0.28+ rejects it (packages are
    specified via OPTIONS["packages"] instead). Clear it early so the
    check passes.
    """

    def finalize_options(self):
        self.distribution.install_requires = []
        super().finalize_options()


APP = ["claudemon/app.py"]

DATA_FILES = [
    ("dashboard", [
        "claudemon/dashboard/index.html",
        "claudemon/dashboard/app.js",
        "claudemon/dashboard/style.css",
    ]),
]

OPTIONS = {
    "argv_emulation": False,
    "packages": [
        "rumps",
        "watchdog",
        "claudemon",
        "objc",
        "Foundation",
        "AppKit",
        "WebKit",
    ],
    "plist": {
        "CFBundleName": "claudemon",
        "CFBundleDisplayName": "claudemon",
        "CFBundleIdentifier": "com.claudemon.app",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
        # Menu-bar-only app: no Dock icon, no App Switcher entry.
        "LSUIElement": True,
        # Allow loading from localhost (127.0.0.1) inside WKWebView.
        "NSAppTransportSecurity": {
            "NSAllowsLocalNetworking": True,
        },
    },
}

setup(
    name="claudemon",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    cmdclass={"py2app": py2app},
)
