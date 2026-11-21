// AiCode for macOS — native slim shell (AppKit + WKWebView)
// Launches the bundled Python backend, then loads the local web UI.

#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

static NSString *const kAppName = @"AiCode";

@interface AppDelegate : NSObject <NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate>
@property (nonatomic, strong) NSWindow *window;
@property (nonatomic, strong) WKWebView *webView;
@property (nonatomic, strong) NSTask *server;
@property (nonatomic, strong) NSMutableString *outBuf;
@property (nonatomic, strong) NSFileHandle *outHandle;
@property (nonatomic, assign) BOOL didLoad;
@property (nonatomic, assign) NSInteger retries;
@property (nonatomic, strong) NSURL *pendingURL;
@end

@implementation AppDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    self.outBuf = [NSMutableString string];
    [self buildMenu];
    [self buildWindow];
    [self launchServer];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return YES; }

- (void)applicationWillTerminate:(NSNotification *)notification {
    [self stopServer];
}

- (void)stopServer {
    self.outHandle.readabilityHandler = nil;
    self.outHandle = nil;
    NSTask *task = self.server;
    if (!task || !task.isRunning) return;
    [task terminate];
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:3.0];
    while (task.isRunning && [deadline timeIntervalSinceNow] > 0) {
        usleep(50000);
    }
    if (task.isRunning) kill(task.processIdentifier, SIGKILL);
}

#pragma mark - UI

- (void)buildWindow {
    NSRect rect = NSMakeRect(0, 0, 1280, 840);
    self.window = [[NSWindow alloc] initWithContentRect:rect
                                              styleMask:(NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                                                         NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable |
                                                         NSWindowStyleMaskFullSizeContentView)
                                                backing:NSBackingStoreBuffered
                                                  defer:NO];
    self.window.title = kAppName;
    self.window.titlebarAppearsTransparent = YES;
    self.window.titleVisibility = NSWindowTitleHidden;
    self.window.minSize = NSMakeSize(960, 620);
    self.window.releasedWhenClosed = NO;
    [self.window center];

    WKWebViewConfiguration *cfg = [[WKWebViewConfiguration alloc] init];
    [cfg.preferences setValue:@YES forKey:@"developerExtrasEnabled"];
    cfg.defaultWebpagePreferences.allowsContentJavaScript = YES;
    cfg.websiteDataStore = [WKWebsiteDataStore defaultDataStore];

    self.webView = [[WKWebView alloc] initWithFrame:rect configuration:cfg];
    self.webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.webView.navigationDelegate = self;
    self.webView.UIDelegate = self;

    self.window.contentView = self.webView;
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    [self splash:@"正在启动 AiCode 后端…"];
}

- (void)loadHTML:(NSString *)html {
    [self.webView loadHTMLString:html baseURL:nil];
}

- (void)splash:(NSString *)text {
    NSString *html = [NSString stringWithFormat:
        @"<!doctype html><meta charset='utf-8'>"
         "<style>html,body{height:100%%;margin:0;background:#0f1115;color:#e6e8ef;"
         "font:14px -apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif;"
         "display:flex;align-items:center;justify-content:center;-webkit-user-select:none}"
         ".box{text-align:center}.logo{width:76px;height:76px;margin:0 auto 18px;border-radius:20px;"
         "background:linear-gradient(140deg,#5b5bf5,#8b4cf0);display:flex;align-items:center;"
         "justify-content:center;font-weight:700;font-size:26px;color:#fff}"
         ".sub{margin-top:8px;color:#8d93a5;font-size:12px}</style>"
         "<div class='box'><div class='logo'>AI</div><div>%@</div>"
         "<div class='sub'>AiCode for macOS</div></div>", text];
    [self loadHTML:html];
}

- (NSString *)escape:(NSString *)s {
    return [[s stringByReplacingOccurrencesOfString:@"&" withString:@"&amp;"]
                stringByReplacingOccurrencesOfString:@"<" withString:@"&lt;"];
}

- (void)fail:(NSString *)text {
    NSString *html = [NSString stringWithFormat:
        @"<!doctype html><meta charset='utf-8'>"
         "<style>html,body{height:100%%;margin:0;background:#0f1115;color:#e6e8ef;"
         "font:13px ui-monospace,SFMono-Regular,Menlo,monospace;display:flex;align-items:center;"
         "justify-content:center}.box{max-width:640px}h3{color:#ff6b81;"
         "font-family:-apple-system,'PingFang SC',sans-serif}"
         "pre{white-space:pre-wrap;background:#171a21;padding:14px;border-radius:10px;color:#c9cede}</style>"
         "<div class='box'><h3>AiCode 启动失败</h3><pre>%@</pre></div>", [self escape:text]];
    [self loadHTML:html];
}

#pragma mark - backend

- (NSString *)findPython {
    NSArray<NSString *> *candidates = @[
        @"/opt/homebrew/bin/python3",
        @"/usr/local/bin/python3",
        @"/usr/bin/python3",
    ];
    NSFileManager *fm = [NSFileManager defaultManager];
    for (NSString *path in candidates) {
        if ([fm isExecutableFileAtPath:path]) return path;
    }
    return nil;
}

- (void)launchServer {
    NSURL *resURL = [[NSBundle mainBundle] resourceURL];
    NSString *script = [[resURL URLByAppendingPathComponent:@"app/server/main.py"] path];
    if (![[NSFileManager defaultManager] fileExistsAtPath:script]) {
        [self fail:[NSString stringWithFormat:@"找不到后端脚本：%@", script]];
        return;
    }
    NSString *python = [self findPython];
    if (!python) {
        [self fail:@"未找到 python3。\n请先安装命令行工具：\n\n  xcode-select --install"];
        return;
    }

    NSTask *task = [[NSTask alloc] init];
    task.executableURL = [NSURL fileURLWithPath:python];
    task.arguments = @[ script ];
    task.currentDirectoryURL = [NSURL fileURLWithPath:NSHomeDirectory()];

    NSMutableDictionary *env = [[[NSProcessInfo processInfo] environment] mutableCopy];
    env[@"PYTHONUNBUFFERED"] = @"1";
    env[@"PYTHONDONTWRITEBYTECODE"] = @"1";
    env[@"PATH"] = @"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
    task.environment = env;

    NSPipe *pipe = [NSPipe pipe];
    task.standardOutput = pipe;
    task.standardError = pipe;
    self.outHandle = [pipe fileHandleForReading];

    __weak AppDelegate *weakSelf = self;
    self.outHandle.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *data = [handle availableData];
        if (data.length == 0) return;
        NSString *text = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
        if (!text) return;
        dispatch_async(dispatch_get_main_queue(), ^{
            [weakSelf consume:text];
        });
    };

    task.terminationHandler = ^(NSTask *t) {
        dispatch_async(dispatch_get_main_queue(), ^{
            AppDelegate *self_ = weakSelf;
            if (!self_) return;
            self_.server = nil;
            if (!self_.didLoad) {
                [self_ fail:[NSString stringWithFormat:
                    @"后端进程已退出（status %d）。\n请确认 python3 可用。", t.terminationStatus]];
            }
        });
    };

    NSError *error = nil;
    if (![task launchAndReturnError:&error]) {
        [self fail:[NSString stringWithFormat:@"无法启动后端：%@", error.localizedDescription]];
        return;
    }
    self.server = task;
}

- (void)consume:(NSString *)chunk {
    [self.outBuf appendString:chunk];
    while (YES) {
        NSRange nl = [self.outBuf rangeOfString:@"\n"];
        if (nl.location == NSNotFound) break;
        NSString *line = [self.outBuf substringToIndex:nl.location];
        [self.outBuf deleteCharactersInRange:NSMakeRange(0, nl.location + nl.length)];
        if ([line hasPrefix:@"AICODE_URL="] && !self.didLoad) {
            self.didLoad = YES;
            self.pendingURL = [NSURL URLWithString:[line substringFromIndex:11]];
            [self loadWhenReady];
        }
    }
}

- (void)loadWhenReady {
    if (!self.pendingURL) return;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.2 * NSEC_PER_SEC)),
                   dispatch_get_main_queue(), ^{
        if (!self.pendingURL) return;
        [self.webView loadRequest:[NSURLRequest requestWithURL:self.pendingURL]];
    });
}

#pragma mark - navigation

- (void)webView:(WKWebView *)webView
    didFailProvisionalNavigation:(WKNavigation *)navigation
                       withError:(NSError *)error {
    if (!self.didLoad || !self.pendingURL || self.retries >= 20) {
        [self fail:[NSString stringWithFormat:@"无法连接本地服务：%@", error.localizedDescription]];
        return;
    }
    self.retries += 1;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.4 * NSEC_PER_SEC)),
                   dispatch_get_main_queue(), ^{
        [webView loadRequest:[NSURLRequest requestWithURL:self.pendingURL]];
    });
}

- (void)webView:(WKWebView *)webView
    decidePolicyForNavigationAction:(WKNavigationAction *)action
                    decisionHandler:(void (^)(WKNavigationActionPolicy))handler {
    NSURL *url = action.request.URL;
    NSString *host = url.host ?: @"";
    BOOL external = action.navigationType == WKNavigationTypeLinkActivated &&
                    ![host isEqualToString:@"127.0.0.1"] &&
                    ![host isEqualToString:@"localhost"];
    if (external) {
        [[NSWorkspace sharedWorkspace] openURL:url];
        handler(WKNavigationActionPolicyCancel);
        return;
    }
    handler(WKNavigationActionPolicyAllow);
}

- (WKWebView *)webView:(WKWebView *)webView
    createWebViewWithConfiguration:(WKWebViewConfiguration *)configuration
               forNavigationAction:(WKNavigationAction *)action
                    windowFeatures:(WKWindowFeatures *)features {
    if (action.request.URL) [[NSWorkspace sharedWorkspace] openURL:action.request.URL];
    return nil;
}

#pragma mark - menu

- (void)buildMenu {
    NSMenu *mainMenu = [[NSMenu alloc] init];

    NSMenuItem *appItem = [[NSMenuItem alloc] init];
    [mainMenu addItem:appItem];
    NSMenu *appMenu = [[NSMenu alloc] init];
    appItem.submenu = appMenu;
    [appMenu addItemWithTitle:[NSString stringWithFormat:@"关于 %@", kAppName]
                       action:@selector(orderFrontStandardAboutPanel:)
                keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:[NSString stringWithFormat:@"隐藏 %@", kAppName]
                       action:@selector(hide:)
                keyEquivalent:@"h"];
    NSMenuItem *hideOthers = [appMenu addItemWithTitle:@"隐藏其他"
                                                action:@selector(hideOtherApplications:)
                                         keyEquivalent:@"h"];
    hideOthers.keyEquivalentModifierMask = NSEventModifierFlagCommand | NSEventModifierFlagOption;
    [appMenu addItemWithTitle:@"显示全部" action:@selector(unhideAllApplications:) keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:[NSString stringWithFormat:@"退出 %@", kAppName]
                       action:@selector(terminate:)
                keyEquivalent:@"q"];

    NSMenuItem *editItem = [[NSMenuItem alloc] init];
    [mainMenu addItem:editItem];
    NSMenu *editMenu = [[NSMenu alloc] initWithTitle:@"编辑"];
    editItem.submenu = editMenu;
    [editMenu addItemWithTitle:@"撤销" action:@selector(undo:) keyEquivalent:@"z"];
    NSMenuItem *redo = [editMenu addItemWithTitle:@"重做" action:@selector(redo:) keyEquivalent:@"z"];
    redo.keyEquivalentModifierMask = NSEventModifierFlagCommand | NSEventModifierFlagShift;
    [editMenu addItem:[NSMenuItem separatorItem]];
    [editMenu addItemWithTitle:@"剪切" action:@selector(cut:) keyEquivalent:@"x"];
    [editMenu addItemWithTitle:@"拷贝" action:@selector(copy:) keyEquivalent:@"c"];
    [editMenu addItemWithTitle:@"粘贴" action:@selector(paste:) keyEquivalent:@"v"];
    [editMenu addItemWithTitle:@"全选" action:@selector(selectAll:) keyEquivalent:@"a"];

    NSMenuItem *viewItem = [[NSMenuItem alloc] init];
    [mainMenu addItem:viewItem];
    NSMenu *viewMenu = [[NSMenu alloc] initWithTitle:@"显示"];
    viewItem.submenu = viewMenu;
    [viewMenu addItemWithTitle:@"重新载入" action:@selector(reloadPage) keyEquivalent:@"r"];
    [viewMenu addItem:[NSMenuItem separatorItem]];
    [viewMenu addItemWithTitle:@"进入全屏" action:@selector(toggleFullScreen:) keyEquivalent:@"f"];

    NSMenuItem *winItem = [[NSMenuItem alloc] init];
    [mainMenu addItem:winItem];
    NSMenu *winMenu = [[NSMenu alloc] initWithTitle:@"窗口"];
    winItem.submenu = winMenu;
    [winMenu addItemWithTitle:@"最小化" action:@selector(performMiniaturize:) keyEquivalent:@"m"];
    [winMenu addItemWithTitle:@"缩放" action:@selector(performZoom:) keyEquivalent:@""];

    NSApp.mainMenu = mainMenu;
}

- (void)reloadPage {
    if ([self.webView.URL.scheme isEqualToString:@"http"]) [self.webView reload];
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        AppDelegate *delegate = [[AppDelegate alloc] init];
        app.delegate = delegate;
        [app run];
    }
    return 0;
}
