import logging

from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSPanel,
    NSScreen,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSURL, NSURLRequest, NSURLRequestReloadIgnoringLocalCacheData
from WebKit import WKWebsiteDataStore, WKWebView, WKWebViewConfiguration

log = logging.getLogger(__name__)

# NSViewWidthSizable | NSViewHeightSizable
_AUTORESIZE = 18


class Popover:
    """Resizable floating NSPanel containing a WKWebView for the local dashboard."""

    DEFAULT_WIDTH = 520
    DEFAULT_HEIGHT = 800

    def __init__(self, port: int):
        self._url = f"http://127.0.0.1:{port}/"
        self._panel = None
        self._webview = None
        # Defer panel creation to first show so NSApp is fully running.

    def _ensure_panel(self) -> None:
        if self._panel is not None:
            return
        log.info("popover: creating NSPanel")
        try:
            style = (
                NSWindowStyleMaskTitled
                | NSWindowStyleMaskClosable
                | NSWindowStyleMaskResizable
            )
            panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                ((0, 0), (self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)),
                style,
                NSBackingStoreBuffered,
                False,
            )
            panel.setTitle_("claudemon")
            panel.setReleasedWhenClosed_(False)
            panel.setHidesOnDeactivate_(False)

            config = WKWebViewConfiguration.alloc().init()
            config.setWebsiteDataStore_(WKWebsiteDataStore.nonPersistentDataStore())
            webview = WKWebView.alloc().initWithFrame_configuration_(
                panel.contentView().bounds(), config
            )
            webview.setAutoresizingMask_(_AUTORESIZE)
            panel.contentView().addSubview_(webview)

            self._panel = panel
            self._webview = webview
            log.info("popover: NSPanel created OK")
        except Exception:
            log.exception("popover: NSPanel creation failed")

    def toggle(self, button) -> None:
        log.info("popover: toggle called")
        self._ensure_panel()
        if self._panel is None:
            log.error("popover: panel is None, cannot show")
            return

        if self._panel.isVisible():
            log.info("popover: hiding panel")
            self._panel.orderOut_(None)
            return

        log.info("popover: loading URL %s", self._url)
        url = NSURL.URLWithString_(self._url)
        req = NSURLRequest.requestWithURL_cachePolicy_timeoutInterval_(
            url, NSURLRequestReloadIgnoringLocalCacheData, 30
        )
        self._webview.loadRequest_(req)

        try:
            self._position_near_button(button)
        except Exception:
            log.exception("popover: position failed, using fallback")
            self._position_fallback()

        # Activate the app so the panel accepts key events, then bring it front.
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self._panel.makeKeyAndOrderFront_(None)
        log.info("popover: panel shown, visible=%s", self._panel.isVisible())

    def _position_near_button(self, button) -> None:
        if button is None:
            self._position_fallback()
            return
        btn_in_window = button.convertRect_toView_(button.bounds(), None)
        btn_on_screen = button.window().convertRectToScreen_(btn_in_window)
        log.info("popover: button screen rect origin=(%s,%s) size=(%s,%s)",
                 btn_on_screen.origin.x, btn_on_screen.origin.y,
                 btn_on_screen.size.width, btn_on_screen.size.height)

        pw = self._panel.frame().size.width
        ph = self._panel.frame().size.height

        x = btn_on_screen.origin.x + btn_on_screen.size.width - pw
        y = btn_on_screen.origin.y - ph

        screen = NSScreen.mainScreen()
        vis = screen.visibleFrame()
        log.info("popover: visibleFrame origin=(%s,%s) size=(%s,%s)",
                 vis.origin.x, vis.origin.y, vis.size.width, vis.size.height)

        x = max(vis.origin.x, min(x, vis.origin.x + vis.size.width - pw))
        y = max(vis.origin.y, y)

        log.info("popover: setting frame origin (%s, %s)", x, y)
        self._panel.setFrameOrigin_((x, y))

    def _position_fallback(self) -> None:
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        vis = screen.visibleFrame()
        pw = self.DEFAULT_WIDTH
        ph = self.DEFAULT_HEIGHT
        x = vis.origin.x + vis.size.width - pw - 10
        y = vis.origin.y + vis.size.height - ph
        log.info("popover: fallback position (%s, %s)", x, y)
        self._panel.setFrameOrigin_((x, y))

    def close(self) -> None:
        if self._panel is not None and self._panel.isVisible():
            self._panel.orderOut_(None)
