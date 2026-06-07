from AppKit import NSPopover, NSPopoverBehaviorTransient, NSRectEdgeMinY, NSSize, NSViewController
from Foundation import NSURL, NSURLRequest
from WebKit import WKWebView, WKWebViewConfiguration


class Popover:
    """NSPopover containing a WKWebView that loads the local dashboard."""

    WIDTH = 380
    HEIGHT = 620

    def __init__(self, port: int):
        self._url = f"http://127.0.0.1:{port}/"
        self._popover = self._build_popover()

    def _build_popover(self) -> NSPopover:
        config = WKWebViewConfiguration.alloc().init()
        webview = WKWebView.alloc().initWithFrame_configuration_(
            ((0, 0), (self.WIDTH, self.HEIGHT)), config
        )

        vc = NSViewController.alloc().init()
        vc.setView_(webview)
        vc.view().setFrameSize_(NSSize(self.WIDTH, self.HEIGHT))

        popover = NSPopover.alloc().init()
        popover.setContentViewController_(vc)
        popover.setBehavior_(NSPopoverBehaviorTransient)
        popover.setContentSize_(NSSize(self.WIDTH, self.HEIGHT))

        self._webview = webview
        return popover

    def toggle(self, sender) -> None:
        """Show or close the popover anchored to the status item button."""
        if self._popover.isShown():
            self._popover.close()
        else:
            url = NSURL.URLWithString_(self._url)
            self._webview.loadRequest_(NSURLRequest.requestWithURL_(url))

            button = getattr(sender, '_status_item', None)
            if button is not None:
                button = button.button()
                self._popover.showRelativeToRect_ofView_preferredEdge_(
                    button.bounds(), button, NSRectEdgeMinY
                )

    def close(self) -> None:
        if self._popover.isShown():
            self._popover.close()
