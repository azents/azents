"""Explicit native SDK types and errors shared by the product browser surface."""

from patchright.async_api import BrowserContext as ChromiumBrowserContext
from patchright.async_api import Dialog as ChromiumDialog
from patchright.async_api import Download as ChromiumDownload
from patchright.async_api import ElementHandle as ChromiumElementHandle
from patchright.async_api import Error as ChromiumError
from patchright.async_api import Frame as ChromiumFrame
from patchright.async_api import JSHandle as ChromiumJSHandle
from patchright.async_api import Page as ChromiumPage
from patchright.async_api import Playwright as ChromiumDriver
from patchright.async_api import TimeoutError as ChromiumTimeoutError
from playwright.async_api import BrowserContext as FirefoxBrowserContext
from playwright.async_api import Dialog as FirefoxDialog
from playwright.async_api import Download as FirefoxDownload
from playwright.async_api import ElementHandle as FirefoxElementHandle
from playwright.async_api import Error as FirefoxError
from playwright.async_api import Frame as FirefoxFrame
from playwright.async_api import JSHandle as FirefoxJSHandle
from playwright.async_api import Page as FirefoxPage
from playwright.async_api import Playwright as FirefoxDriver
from playwright.async_api import TimeoutError as FirefoxTimeoutError

type BrowserContext = ChromiumBrowserContext | FirefoxBrowserContext
type Dialog = ChromiumDialog | FirefoxDialog
type Download = ChromiumDownload | FirefoxDownload
type ElementHandle = ChromiumElementHandle | FirefoxElementHandle
type Frame = ChromiumFrame | FirefoxFrame
type JSHandle = ChromiumJSHandle | FirefoxJSHandle
type Page = ChromiumPage | FirefoxPage
type BrowserDriver = ChromiumDriver | FirefoxDriver
type BrowserSDKError = ChromiumError | FirefoxError

BROWSER_SDK_ERRORS = (ChromiumError, FirefoxError)
BROWSER_SDK_TIMEOUTS = (ChromiumTimeoutError, FirefoxTimeoutError)
